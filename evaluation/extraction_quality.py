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

from app.llm.extract import FragmentInput, extract_fragments, deduplicate_results
from app.llm.provider import create_adapter
from app.llm import hosted
from app.progress.effects import build_effects
from app.prompts.extraction_v1 import PROMPT_VERSION, SYSTEM_PROMPT
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
    passed = atomic and dates is not False and quantity is not False and non_actual_safe and blocker_safe and warning is not False
    return {"passed": passed, "atomic_events_correct": atomic, "work_date_correct": dates,
            "quantity_correct": quantity, "non_actual_effects_safe": non_actual_safe,
            "blocker_quantity_safe": blocker_safe, "required_warning_present": warning,
            "label_status": "synthetic_development_checks_not_human_adjudicated"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--case-ids", nargs="+")
    args = parser.parse_args()
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
    config = {"started_at": datetime.now(timezone.utc).isoformat(), "prompt_version": PROMPT_VERSION,
        "prompt_sha256": sha256(SYSTEM_PROMPT.encode()).hexdigest(), "fixture_sha256": sha256(args.fixtures.read_bytes()).hexdigest(),
        "provider": "groq", "model": settings.groq_model, "key_slot": 0, "transport_retries": 0, "admission_scope": "postgresql_deployment",
        "case_ids": [c["case_id"] for c in cases],
        "timeout_seconds": 60, "scope": "fresh wording synthetic component development checks; no persistence or approvals"}
    (args.output_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    rows = []
    for case in cases:
        started = perf_counter()
        row = {"case_id": case["case_id"], "state": "failed"}
        try:
            model = create_adapter(settings, timeout=60, role="extraction").chat
            fragments = [FragmentInput(str(uuid4()), "synthetic:1", case["text"], 1)]
            results = extract_fragments(fragments, model,
                report_date=date.fromisoformat(case["report_date"]) if case["report_date"] else None,
                report_date_trusted=case["trusted"], prompt_version=PROMPT_VERSION)
            observations = deduplicate_results(results)
            errors = [e for result in results for e in result.errors]
            row.update(state="completed", observations=[o.model_dump(mode="json") for o in observations],
                       extraction_errors=errors, scores=score(case, observations))
            if errors:
                row["scores"]["passed"] = False
        except Exception as error:
            row.update(error_type=type(error).__name__, error_code=getattr(error, "code", "EXTRACTION_CHECK_FAILED"),
                       retry_after_seconds=getattr(error, "retry_after_seconds", None))
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
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
