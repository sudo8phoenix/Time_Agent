"""Integrity checks for the isolated, pending-review W-29 native dataset."""
import hashlib
import json
import pytest
from collections import Counter
from pathlib import Path

from app.ingest.native_schedule.microsoft import read_schedule as read_microsoft
from app.ingest.native_schedule.primavera import read_schedule as read_primavera


ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "synthetic" / "native_import"


def load(name):
    return [json.loads(line) for line in (DATA / name).read_text().splitlines() if line]


def test_native_dataset_sources_categories_hashes_and_family_splits():
    reports, labels = load("reports.jsonl"), load("labels.jsonl")
    manifest = json.loads((DATA / "manifest.json").read_text())
    splits = json.loads((DATA / "splits.json").read_text())
    assert len(reports) == len(labels) == 40
    assert {r["report_id"] for r in reports} == {l["report_id"] for l in labels}
    expected = {"unambiguous_actual": 8, "ambiguous_match": 4, "unmatched": 2, "planned_no_work": 2, "duplicate_correction": 2, "missing_unit_date": 2}
    for source in manifest["sources"]:
        rows = [x for x in labels if x["schedule_source"] == source]
        assert len(rows) == 20
        assert Counter(x["primary_case_type"] for x in rows) == expected
    assert all(x["origin"] == "synthetic" and x["reviewer_status"] == "pending" for x in reports + labels)
    assert all(x["expected_quantity"] is None and x["expected_unit"] is None for x in labels)
    assignment = {family: split for split in ("development", "validation", "held_out") for family in splits[split]}
    assert Counter(assignment[x["event_family_id"]] for x in labels) == {"development": 24, "validation": 8, "held_out": 8}
    for family in {x["event_family_id"] for x in labels}:
        assert len({assignment[x["event_family_id"]] for x in labels if x["event_family_id"] == family}) == 1
    for filename, digest in manifest["hashes_sha256"].items():
        assert hashlib.sha256((DATA / filename).read_bytes()).hexdigest() == digest


def test_labels_resolve_to_actual_native_source_ids_when_parsers_are_available():
    workspace_fixture = next(
        (candidate for candidate in (ROOT.parent / "PROJECT.xer", ROOT / "PROJECT.xer") if candidate.is_file()),
        None,
    )
    if workspace_fixture is None:
        pytest.skip("workspace PROJECT.xer is an optional native-parser fixture")
    p6 = read_primavera(workspace_fixture)
    mpp = read_microsoft(ROOT / "backend/tests/fixtures/native_schedule/public_sample.mpp")
    actual = {
        "workspace_PROJECT_xer": {(str(x.external_id), str(x.source_task_id)) for x in p6.tasks},
        "microsoft_public_sample_mpp": {(str(x.external_id), str(x.source_task_id)) for x in mpp.tasks},
    }
    for label in load("labels.jsonl"):
        assert len(label["expected_activity_ids"]) == len(label["expected_source_task_ids"])
        for pair in zip(label["expected_activity_ids"], label["expected_source_task_ids"]):
            assert pair in actual[label["schedule_source"]]
