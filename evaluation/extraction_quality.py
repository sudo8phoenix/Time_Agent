"""Bounded live extraction check on fresh synthetic development wording.

Expected checks never enter model inputs. No database, schedules, approval or
ledger calls. This is a component diagnostic, not independently unseen acceptance.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from pydantic import ValidationError

from app.llm.extract import FragmentInput, extract_fragments, deduplicate_results
from app.llm.provider import create_adapter
from app.llm import hosted
from app.llm.metrics import capture_provider_metrics
from app.progress.effects import build_effects
from app.prompts.extraction_v1 import PROMPT_VERSION, get_extraction_prompt
from app.settings import get_settings


DEFAULT_FIXTURES = Path(__file__).parent / "fixtures/quality-wording-variants.json"


def score(case, observations):
    events = sorted(o.event_type.value for o in observations)
    atomic = events == sorted(case["expected_events"])
    dates = None
    if "expected_work_date" in case:
        dates = bool(observations) and all(
            (o.work_date.isoformat() if o.work_date else None) == case["expected_work_date"]
            for o in observations)
    quantity = None
    if "expected_quantity" in case:
        expected = case["expected_quantity"]
        quantity = any(o.event_type.value == expected["event"] and o.quantity is not None and
            o.quantity == Decimal(expected["quantity"]) and o.unit is not None and o.unit.value == expected["unit"]
            for o in observations)
    non_actual_safe = all(not build_effects(o) and o.quantity is None and o.unit is None and
        not o.actual_start and not o.actual_finish and not o.lifecycle_effects
        for o in observations if o.event_type.value in {"planned_work", "material_delivery", "no_work"})
    blocker_safe = all(o.quantity is None for o in observations if o.event_type.value == "blocker")
    warning = any(o.warnings for o in observations) if case.get("warning_required") else None
    field_checks = []
    for expected in case.get("expected_fields", []):
        matches = [o for o in observations if o.event_type.value == expected["event"]]
        correct = len(matches) == 1
        if correct:
            observed = matches[0]
            for field, value in expected.items():
                if field == "event":
                    continue
                actual = getattr(observed, field)
                actual = getattr(actual, "value", actual)
                correct = correct and actual == value
        field_checks.append({"event": expected["event"], "correct": correct})
    fields_correct = all(check["correct"] for check in field_checks) if field_checks else None
    passed = atomic and dates is not False and quantity is not False and non_actual_safe and blocker_safe and warning is not False and fields_correct is not False
    return {"passed": passed, "atomic_events_correct": atomic, "work_date_correct": dates,
            "fields_correct": fields_correct, "field_checks": field_checks,
            "quantity_correct": quantity, "non_actual_effects_safe": non_actual_safe,
            "blocker_quantity_safe": blocker_safe, "required_warning_present": warning,
            "label_status": "synthetic_development_checks_not_human_adjudicated"}


def main():
    from evaluation.live_pacing import wait_before_case
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--case-ids", nargs="+")
    parser.add_argument("--prompt-version", default=PROMPT_VERSION)
    parser.add_argument("--batch-size", type=int, choices=range(1, 6), default=5)
    args = parser.parse_args()
    prompt_version, system_prompt = get_extraction_prompt(args.prompt_version)
    cases = json.loads(args.fixtures.read_text())
    if args.case_ids:
        unknown = set(args.case_ids) - {c["case_id"] for c in cases}
        if unknown:
            raise SystemExit("Unknown quality check identifiers")
        cases = [c for c in cases if c["case_id"] in args.case_ids]
    if not 1 <= len(cases) <= 8:
        raise SystemExit("Use 1–8 synthetic checks per bounded capture")
    if args.output_dir.exists():
        raise SystemExit("Use a new capture directory")
    args.output_dir.mkdir(parents=True)
    settings = get_settings().model_copy(update={"extraction_provider": "groq",
        "extraction_model": get_settings().groq_model, "extraction_key_slot": 0})
    config = {"started_at": datetime.now(timezone.utc).isoformat(), "prompt_version": prompt_version,
        "prompt_sha256": sha256(system_prompt.encode()).hexdigest(), "fixture_sha256": sha256(args.fixtures.read_bytes()).hexdigest(),
        "provider": "groq", "model": settings.groq_model, "key_slot": 0, "transport_retries": 0, "admission_scope": "postgresql_deployment",
        "case_ids": [c["case_id"] for c in cases],
        "timeout_seconds": 60, "scope": "fresh wording synthetic component development checks; no persistence or approvals"}
    config["source_sha256"] = {str(p): sha256(p.read_bytes()).hexdigest() for p in (
        Path("backend/app/llm/extract.py"), Path("backend/app/prompts/extraction_v1.py"),
        Path('evaluation/live_pacing.py'), Path(__file__))}
    config.update(batch_size=args.batch_size, batch_pause_seconds=60,
        pre_submission_pacing_recorded=True)
    (args.output_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    rows = []
    for index, case in enumerate(cases):
        wait_before_case(args.output_dir, case['case_id'], index, batch_size=args.batch_size)
        started = perf_counter()
        row = {"case_id": case["case_id"], "state": "failed"}
        try:
            adapter = create_adapter(settings, timeout=60, role="extraction")

            def model(**kwargs):
                try:
                    with capture_provider_metrics() as metrics:
                        result = adapter.chat(**kwargs)
                finally:
                    with (args.output_dir / "provider-metrics.jsonl").open("a") as stream:
                        stream.write(json.dumps({"case_id": case["case_id"],
                            "provider_metrics": metrics}) + "\n")
                # Synthetic component evidence only: retain the response before
                # normalization/schema validation can reject it. Never store
                # request headers, adapter state or exception text here.
                with (args.output_dir / "model-outputs.jsonl").open("a") as stream:
                    stream.write(json.dumps({"case_id": case["case_id"],
                        "model": result.model, "value": result.value}) + "\n")
                return result
            fragments = [FragmentInput(str(uuid4()), "synthetic:1", case["text"], 1)]
            with (args.output_dir / "inputs.jsonl").open("a") as stream:
                stream.write(json.dumps({"case_id": case["case_id"], "report_date": case["report_date"],
                    "trusted": case["trusted"], "fragments": [vars(f) for f in fragments]}) + "\n")
            results = extract_fragments(fragments, model,
                report_date=date.fromisoformat(case["report_date"]) if case["report_date"] else None,
                report_date_trusted=case["trusted"], prompt_version=prompt_version)
            observations = deduplicate_results(results)
            errors = [e for result in results for e in result.errors]
            row.update(state="completed", observations=[o.model_dump(mode="json") for o in observations],
                       extraction_errors=errors, scores=score(case, observations))
            if errors:
                row["scores"]["passed"] = False
        except Exception as error:
            row.update(error_type=type(error).__name__, error_code=getattr(error, "code", "EXTRACTION_CHECK_FAILED"),
                       retry_after_seconds=getattr(error, "retry_after_seconds", None))
            if isinstance(error.__cause__, ValidationError):
                row["schema_errors"] = [{"location": list(item["loc"]), "type": item["type"]}
                    for item in error.__cause__.errors(include_input=False, include_context=False,
                                                     include_url=False)]
        with hosted.ADMISSION.condition:
            state = hosted.ADMISSION.states.get("groq")
            row["quota_headers"] = dict(state.headers) if state else {}
        row["elapsed_ms"] = round((perf_counter() - started) * 1000)
        rows.append(row)
        with (args.output_dir / "predictions.jsonl").open("a") as stream:
            stream.write(json.dumps(row) + "\n")
        print(json.dumps({"case_id": row["case_id"], "state": row["state"], "passed": row.get("scores", {}).get("passed"), "elapsed_ms": row["elapsed_ms"]}), flush=True)
    summary = {"cases": len(rows), "completed": sum(r["state"] == "completed" for r in rows),
        "passed": sum(r.get("scores", {}).get("passed", False) for r in rows),
        "failures": [r["case_id"] for r in rows if not r.get("scores", {}).get("passed")],
        "independent_human_adjudication": False, "domain_writes": 0}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.output_dir / "capture-manifest.json").write_text(json.dumps({
        "hashes": {p.name: sha256(p.read_bytes()).hexdigest() for p in args.output_dir.iterdir() if p.is_file()}
    }, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
