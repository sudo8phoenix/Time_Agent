"""Rescore immutable captures into a separate, explicitly technical review artifact."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from evaluation.report_planner_eval import load_cases, score_case, summarize


def review_capture(capture, output, review_path):
    if output.exists():
        raise ValueError("Use a new output directory to preserve review evidence")
    config = json.loads((capture / "config.json").read_text())
    predictions = (capture / "predictions.jsonl").read_bytes()
    rows = [json.loads(line) for line in predictions.splitlines() if line]
    reviews = json.loads(review_path.read_text())
    if config.get("dataset") != "seed":
        raise ValueError("This technical review reference applies only to the seed dataset")
    cases = {c["case_id"]: c for c in load_cases(config["case_ids"], dataset="seed")}
    # Ensure retained source/labels still match the captured dataset, rather than
    # quietly scoring an old response against edited labels.
    for key in ("reports", "labels", "schedule"):
        expected = config.get("dataset_sha256", {}).get(key)
        path = Path(config["dataset_paths"][key])
        if expected and sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Captured dataset hash changed")
    output.mkdir(parents=True)
    issues = []
    for row in rows:
        case = cases[row["case_id"]]
        case["technical_review"] = {"status": reviews["status"], **reviews["cases"].get(row["case_id"], {})}
        row["original_scores"] = row.get("scores")
        row["scores"] = score_case(case, row)
        row["source_review_notes"] = case["technical_review"].get("notes")
        failures = [key for key in ("exact_mapping_correct", "atomic_events_correct",
                    "normalized_quantity_correct", "reviewed_work_date_correct") if row["scores"].get(key) is False]
        if failures:
            issues.append({"case_id": row["case_id"], "arm": row["arm"], "failed_checks": failures})
    (output / "reviewed-predictions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    result = {"capture_sha256": sha256(predictions).hexdigest(),
        "reference_review_sha256": sha256(review_path.read_bytes()).hexdigest(),
        "reference_status": reviews["status"], "original_capture_modified": False,
        "summary": summarize(rows), "technical_issues": issues,
        "semantic_evidence_adjudication": "pending_independent_human_review"}
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--review-json", type=Path,
        default=Path("evaluation/reviews/seed-source-review-2026-10-16.json"))
    args = parser.parse_args()
    print(json.dumps(review_capture(args.capture_dir, args.output_dir, args.review_json)))


if __name__ == "__main__":
    main()
