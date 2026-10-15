"""Score completed Gemma captures, keeping benchmark scope explicit."""

import argparse
import json
from collections import Counter
from pathlib import Path
from evaluation.run import run
from evaluation.metrics import evaluate, latency_summary

ROOT = Path("evaluation/results/gemma4-12b-2026-10-12")


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", type=Path, default=ROOT / "compact")
    compact = parser.parse_args().capture_dir
    config = json.loads((compact / "config.json").read_text())
    result = run(
        compact / "predictions.jsonl",
        Path("data/synthetic/expanded/labels.jsonl"),
        Path("data/synthetic/expanded/splits.json"),
        "held_out",
        config,
    )
    predictions = lines(compact / "predictions.jsonl")
    labels = {r["case_id"]: r for r in lines(Path("data/synthetic/expanded/labels.jsonl"))}
    # No candidate retrieval occurs in this benchmark; the entire schedule is supplied.
    for key in (
        "candidate_recall",
        "recall_at_8",
        "recall_at_8_numerator",
        "recall_at_8_denominator",
    ):
        result["selection"][key] = None
    result["selection"]["retrieval_status"] = (
        "unavailable: full schedule supplied; no ranked shortlist"
    )
    result["event_type_accuracy"] = {
        "correct": sum(
            p.get("event_type") == labels[p["case_id"]]["expected_event_type"] for p in predictions
        ),
        "applicable": len(predictions),
    }
    result["case_failures"] = sum("failure" in p for p in predictions)
    successful = [p for p in predictions if "failure" not in p]
    successful_labels = [labels[p["case_id"]] for p in successful]
    result["successful_response_count"] = len(successful)
    result["successful_response_metrics"] = evaluate(successful_labels, successful)
    result["successful_response_metrics"]["extraction"] = {
        "status": "unavailable: missing atomic labels"
    }
    for key in (
        "candidate_recall",
        "recall_at_8",
        "recall_at_8_numerator",
        "recall_at_8_denominator",
    ):
        result["successful_response_metrics"]["selection"][key] = None
    safe_rows = [
        p
        for p in predictions
        if labels[p["case_id"]]["expected_mapping_state"] in {"ambiguous", "unmatched"}
    ]
    safe_correct = sum(
        "failure" not in p and p.get("selected_activity_id") is None for p in safe_rows
    )
    result["selection"]["safe_abstention"] = safe_correct / len(safe_rows) if safe_rows else None
    result["selection"]["safe_abstention_verified_numerator"] = safe_correct
    result["selection"]["safe_abstention_unverified_failures"] = sum(
        "failure" in p for p in safe_rows
    )
    result["selection"]["safe_abstention_note"] = (
        "Fraction of requested unmatched/ambiguous cases with verified valid abstention; failures are not verified abstentions. Successful-response metrics exclude failures."
    )
    result["batch_latency"] = latency_summary(
        [{"latency_ms": r["wall_ms"]} for r in lines(compact / "calls.jsonl")]
    )
    result["latency_note"] = (
        "Measured per ten-case request; per-case or UI-to-export latency is unavailable."
    )
    result["errors_by_case"] = []
    fields = ("event_type", "quantity", "quantity_kind", "unit")
    for p in predictions:
        label = labels[p["case_id"]]
        errors = [
            field
            for field in fields
            if (
                p.get(field) is not None
                if label.get("expected_" + field) is None
                else str(p.get(field)) != str(label.get("expected_" + field))
            )
        ]
        expected_id = (
            label["expected_activity_ids"] if label["expected_mapping_state"] == "suggested" else []
        )
        actual = [p["selected_activity_id"]] if p.get("selected_activity_id") else []
        if actual != expected_id:
            errors.append("activity_selection")
        if "failure" in p:
            errors.append("request_failure")
        if errors:
            result["errors_by_case"].append(
                {
                    "case_id": p["case_id"],
                    "fields": errors,
                    "expected": {k: label.get("expected_" + k) for k in fields},
                    "actual": {k: p.get(k) for k in fields},
                    "expected_selection": expected_id,
                    "actual_selection": actual,
                }
            )
    result["strict_case_correct"] = len(predictions) - len(result["errors_by_case"])
    result["error_field_counts"] = dict(
        Counter(field for r in result["errors_by_case"] for field in r["fields"])
    )
    result["extraction"] = {
        "status": "unavailable: labels contain no attribute-level atomic events",
        "precision": None,
        "recall": None,
        "f1": None,
    }
    result["quantity_null_preservation"] = {
        "applicable": sum(
            labels[p["case_id"]].get("expected_quantity") is None for p in predictions
        ),
        "correct": sum(
            labels[p["case_id"]].get("expected_quantity") is None
            and p.get("quantity") is None
            and "failure" not in p
            for p in predictions
        ),
    }
    result["prompt_limitations"] = [
        "Draft prompt suggests unknown/none for unclear or duplicate assertions; labels sometimes expect actual_progress/delta.",
        "Draft prompt includes equipment, tonne, percent as canonical units, which differ from production enum each, t, kg, m, m2, m3, spool, joint, point. Unit score is prompt-dependent and cannot isolate model quality.",
    ]
    (compact / "scored.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    production = lines(ROOT / "predictions.jsonl")
    subset = [labels[p["case_id"]] for p in production]
    diagnostic = evaluate(subset, production)
    diagnostic["scope"] = (
        "Incomplete production component diagnostic; one completed case, not a full held-out evaluation"
    )
    diagnostic["extraction"] = {"status": "unavailable: labels lack attribute-level atomic events"}
    (ROOT / "production-diagnostic.json").write_text(
        json.dumps(diagnostic, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "critical_fields",
                    "selection",
                    "event_type_accuracy",
                    "batch_latency",
                    "case_failures",
                    "strict_case_correct",
                    "error_field_counts",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
