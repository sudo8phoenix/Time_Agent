"""Verify and rescore the sanitized published model comparison without inference."""

from hashlib import sha256
import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures/model-comparison-2026-10-22"


def verify_and_score(directory=FIXTURE):
    directory = Path(directory)
    manifest = json.loads((directory / "publication-manifest.json").read_text())
    for name, expected in manifest.items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Unsafe evidence path")
        if sha256((directory / path).read_bytes()).hexdigest() != expected:
            raise ValueError("Published evidence changed: " + name)
    for prompt in json.loads((directory / "prompt-catalog.json").read_text()):
        if sha256(prompt["system"].encode()).hexdigest() != prompt["sha256"]:
            raise ValueError("Prompt digest mismatch")
    # Only this pure scorer is called; no adapters, sessions or transports run.
    from evaluation.assembled_development import full_case_score

    cases = {r["case_id"]: r for r in json.loads((directory / "cases.json").read_text())}
    labels = json.loads((directory / "labels.json").read_text())
    outcomes = json.loads((directory / "outcomes.json").read_text())
    latest = {}
    for row in outcomes:
        score = full_case_score(row, labels[row["case_id"]], cases[row["case_id"]]["report_date"])
        if score != row["full_case_score"]:
            raise ValueError("Scoped score mismatch")
        if row["planner_slot"] == row["worker_slot"]:
            raise ValueError("Roles must use distinct slots")
        if row["ledger_writes"] or any(s != "pending" for s in row["review_states"]):
            raise ValueError("Approval boundary violation")
        latest[row["planner_model"], row["worker_model"], row["case_id"], row["planner_slot"]] = row
    summary = json.loads((directory / "summary.json").read_text())
    results = {}
    for config in summary["configurations"]:
        selected = [
            r
            for r in latest.values()
            if (r["planner_model"], r["worker_model"]) == (config["planner"], config["worker"])
        ]
        exact = sum(r["full_case_score"]["full_report_exact"] for r in selected)
        if len(selected) != 4 or exact != config["exact"]:
            raise ValueError("Configuration total mismatch")
        results[config["name"]] = {"exact": exact, "planned": len(selected)}
    return {
        "configurations": results,
        "retained_report_attempts": len(outcomes),
        "latest_comparisons": len(latest),
        "release_accepted": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify_and_score(), indent=2))
