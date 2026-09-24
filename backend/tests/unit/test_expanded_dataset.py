"""Integrity checks for the isolated, pending-review W-03 expansion package."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "synthetic" / "expanded"


def _jsonl(name):
    return [json.loads(line) for line in (DATA / name).read_text(encoding="utf-8").splitlines() if line]


def test_w03_expansion_is_complete_isolated_and_pending_human_review():
    schedule = list(csv.DictReader((DATA / "schedule.csv").open(encoding="utf-8", newline="")))
    leaves = {row["activity_id"] for row in schedule if row["is_leaf"] == "true"}
    summaries = [row for row in schedule if row["is_leaf"] == "false"]
    reports, labels = _jsonl("reports.jsonl"), _jsonl("labels.jsonl")
    split = json.loads((DATA / "splits.json").read_text(encoding="utf-8"))
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))

    assert len(leaves) == 60
    assert len(summaries) == 3
    assert {row["area"] for row in schedule} == {"AREA-A", "AREA-B", "AREA-C"}
    assert len(reports) == 100
    assert {report["report_style"] for report in reports} == {
        "daily_narrative", "supervisor_short_note", "tabular_daily_quantity_sheet",
        "weekly_cumulative_summary", "correction_note",
    }
    assert len(labels) == 300
    assert Counter(x["primary_case_type"] for x in labels) == {
        "unambiguous_actual": 120, "ambiguous_match": 45, "unmatched": 30,
        "future_plan_or_no_work": 30, "duplicate_correction_quantity": 30,
        "messy_date_unit": 30, "injection_or_unreadable": 15,
    }
    assert all(x["origin"] == "synthetic" and x["provenance"] == "authored_synthetic_w03_expansion" for x in labels)
    assert all(x["reviewer_status"] == "pending" for x in labels)
    assert all(set(x["expected_activity_ids"]) <= leaves for x in labels)
    assert all(x["expected_match_reason"] for x in labels if not x["expected_activity_ids"])

    family_split = {family: name for name, families in split["splits"].items() for family in families}
    assert Counter(family_split.values()) == {"development": 60, "validation": 20, "held_out": 20}
    assert len(family_split) == 100
    assert all(split["case_assignment"][x["case_id"]] == family_split[x["event_family_id"]] for x in labels)
    assert manifest["reviewer_status"] == "pending_human_review"
    assert manifest["human_review_completed"] is False
    for filename, expected in manifest["hashes_sha256"].items():
        assert hashlib.sha256((DATA / filename).read_bytes()).hexdigest() == expected
