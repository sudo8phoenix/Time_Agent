"""Run label-free inputs through production extraction and schedule decisions."""

from __future__ import annotations
import argparse
import csv
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.llm.ollama import OllamaChatAdapter
from app.llm.extract import BatchInput, FragmentInput, extract_batch
from app.agent.schedule_decision import shortlist_activities, select_activity


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--inputs", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    adapter = OllamaChatAdapter(args.endpoint, "gemma4:12b", timeout=180, max_retries=0)
    health = adapter.health()
    if not health["ok"]:
        raise RuntimeError("Model is not installed")
    schedule = Path("data/synthetic/expanded/schedule.csv")
    activities = []
    for row in csv.DictReader(schedule.open()):
        activities.append(
            {
                **row,
                "id": row["activity_id"],
                "external_id": row["activity_id"],
                "name": row["activity_name"],
                "wbs": row["wbs_path"],
                "is_leaf": row["is_leaf"].lower() == "true",
            }
        )
    config = {
        **health,
        "method": "production-extraction-model-shortlist-selection",
        "real_model": True,
        "temperature": 0,
        "num_ctx": 8192,
        "num_predict": 1536,
        "think": False,
        "timeout_seconds": 180,
        "transport_retries": 0,
        "input_sha256": digest(args.inputs),
        "schedule_sha256": digest(schedule),
        "scope": "isolated fragment component evaluation; no UI, database, approval or export",
    }
    (args.output_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    predictions = args.output_dir / "predictions.jsonl"
    completed = (
        {json.loads(line)["case_id"] for line in predictions.read_text().splitlines()}
        if predictions.exists()
        else set()
    )
    for line in args.inputs.read_text().splitlines():
        case = json.loads(line)
        if case["case_id"] in completed:
            continue
        started = time.monotonic()
        row = {
            "case_id": case["case_id"],
            "candidate_ids": [],
            "selected_activity_ids": [],
            "atomic_events": [],
            "atomic_count": 0,
            "model": adapter.model,
        }
        calls = []

        def model_call(**kwargs):
            result = adapter.chat(**kwargs)
            calls.append(
                {
                    "stage": stage,
                    "elapsed_ms": result.elapsed_ms,
                    "prompt_hash": result.prompt_hash,
                    "settings_hash": result.settings_hash,
                    "value": result.value,
                }
            )
            return result

        stage = "extraction"
        try:
            fragment = FragmentInput(case["case_id"], case["locator"], case["text"])
            batch = BatchInput(
                case["case_id"], (fragment,), date.fromisoformat(case["report_date"]), True
            )
            extracted = extract_batch(batch, model_call, model=adapter.model)
            row["validation_errors"] = list(extracted.errors)
            row["observations"] = [o.model_dump(mode="json") for o in extracted.observations]
            row["atomic_count"] = len(extracted.observations)
            for observation in extracted.observations:
                data = observation.model_dump(mode="json")
                row["atomic_events"].append(
                    {
                        k: data[k]
                        for k in ("event_type", "work_date", "quantity", "quantity_kind", "unit")
                    }
                )
            # Preserve multi-event outputs; case field scores use the first observed event.
            if extracted.observations:
                observation = extracted.observations[0]
                data = observation.model_dump(mode="json")
                row.update(
                    {
                        k: data[k]
                        for k in ("event_type", "quantity", "quantity_kind", "unit", "work_date")
                    }
                )
                stage = "shortlist"
                candidates = shortlist_activities(
                    observation, "expanded-snapshot", activities, model_call=model_call
                )
                row["candidate_ids"] = [str(c.candidate_id) for c in candidates]
                stage = "selection"
                proposal = select_activity(
                    observation,
                    candidates,
                    {fragment.fragment_id: fragment.text},
                    model_call=model_call,
                )
                row["proposal"] = proposal.model_dump(mode="json")
                row["mapping_state"] = proposal.mapping_state.value
                row["selected_activity_ids"] = (
                    [str(proposal.candidate_id)] if proposal.candidate_id else []
                )
        except Exception as exc:
            row["failure"] = {
                "stage": stage,
                "type": type(exc).__name__,
                "message": str(exc)[:2000],
            }
        row["calls"] = calls
        row["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
        with predictions.open("a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            json.dumps(
                {
                    "case_id": row["case_id"],
                    "seconds": round(row["latency_ms"] / 1000, 1),
                    "selected": row["selected_activity_ids"],
                    "failure": row.get("failure", {}).get("type"),
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
