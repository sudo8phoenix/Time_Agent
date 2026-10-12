import json
import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ingest.schedule_datasets.cambridge import read_cambridge
from app.ingest.schedule_datasets.cambridge_preview import read_schedule
from app.ingest.native_schedule.runner import ParserRuntimeError
from app.schemas.native_schedule import SchedulePreview


def _write(tmp_path, value):
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_reader_rejects_heterogeneous_task_and_relationship_values(tmp_path):
    malformed_task = _write(tmp_path, {"Projects": {"p": {"Activities": {"a": [1]}}}})
    with pytest.raises(ValueError, match="invalid task object"):
        list(read_cambridge(malformed_task))
    malformed_relation = _write(tmp_path, {"Projects": {"p": {"Activities": {"a": {
        "Task_ID": "a", "Activity_Relationships": {"r": "unexpected"}}}}}})
    with pytest.raises(ValueError, match="invalid relationship object"):
        list(read_cambridge(malformed_relation))
    malformed_container = _write(tmp_path, {"Projects": {"p": {"Activities": {"a": {
        "Task_ID": "a", "Activity_Relationships": [1]}}}}})
    with pytest.raises(ValueError, match="invalid relationship container"):
        list(read_cambridge(malformed_container))


def test_snapshot_preview_preserves_raw_rows_and_flags_uncertainty(tmp_path):
    raw_task = {"Task_ID": "A", "Activity_Description": "Dig", "WBS_ID": 4,
                "Planned_Start_Date": "2025-02-30", "Planned_Finish_Date": "2025-03-01",
                "Actual_Start_Date": "", "Actual_Finish_Date": "", "Calendar_ID": 7,
                "Activity_Relationships": {
                    "x": {"Predecessor_ID": "B", "Relationship_Type": "RANDOM", "Lag": "2"},
                    "y": {"Predecessor_ID": "B", "Relationship_Type": "PR_FS", "Lag": "2"}}}
    snapshot = _write(tmp_path, {"_cambridge_snapshot": {"kind": "derived_project_snapshot",
        "derived_from_parent": True, "parent_source_sha256": "a" * 64,
        "parent_source_locator": "$.Projects[\"p\"]", "parent_sha256_status": "computed_from_local_parent_bytes",
        "snapshot_project_id": "p", "upstream_identity_verified": False,
        "upstream_identity_verification": "not_performed"},
        "Projects": {"p": {"Project_ID": "P", "Status_Data_Date": "2025-04-01",
                            "Activities": {"A": raw_task, "B": {
                                "Task_ID": "B", "Activity_Description": "Earlier",
                                "Planned_Start_Date": "2025-04-01 10:00", "Planned_Finish_Date": "2025-04-01 09:00",
                                "Actual_Start_Date": "2025-04-01 10:00", "Actual_Finish_Date": "2025-04-01 09:00",
                                "Activity_Relationships": {}}, "C": {
                                "Task_ID": "C", "Activity_Description": "After status",
                                "Actual_Start_Date": "2025-04-02", "Actual_Finish_Date": "2025-04-03",
                                "Activity_Relationships": {}}},
                            "Work_Breakdown_Structure": {"3": {"WBS_ID": "3", "WBS_Description": "Parent", "WBS_Parent_ID": "null"},
                                                          "4": {"WBS_ID": "4", "WBS_Description": "Child", "WBS_Parent_ID": "3"}}}},
        "Calendars": {"7": {"raw": True}}})
    preview = read_schedule(snapshot)
    task = preview.tasks[0]
    assert task.source_task_id == "A" and task.external_id == "A"
    assert task.planned_start is None and task.actual_start is None
    assert task.source_fields["raw_fields"] == raw_task
    assert preview.tasks[1].actual_start is None and preview.tasks[1].actual_finish is None
    assert preview.tasks[1].planned_start is None and preview.tasks[1].planned_finish is None
    assert preview.tasks[2].actual_start is None and preview.tasks[2].actual_finish is None
    assert preview.wbs[1].parent_source_wbs_id == "3" and preview.wbs[1].path == ["3", "4"]
    assert [rel.relation_type for rel in preview.relationships] == ["FS"]
    assert preview.relationships[0].lag_unit == "unknown_unreviewed"
    codes = {issue.code for issue in preview.issues}
    assert {"invalid_source_date", "invalid_date_chronology", "actual_after_status_date",
            "unknown_relationship_type", "cambridge_provenance_unverified",
            "cambridge_lag_units_unreviewed", "cambridge_calendar_semantics_unreviewed"} <= codes
    assert preview.source_metadata["calendars"] == {"7": {"raw": True}}
    assert preview.source_metadata["raw_wbs"]["4"]["WBS_Parent_ID"] == "3"


def test_json_adapter_rejects_arbitrary_json(tmp_path):
    path = _write(tmp_path, {"Projects": {}})
    with pytest.raises(Exception, match="derived Cambridge snapshot"):
        read_schedule(path)


@pytest.mark.parametrize("field,value", [
    ("snapshot_project_id", "other"),
    ("parent_source_locator", "$.Projects[\"other\"]"),
    ("parent_source_sha256", "not-a-hash"),
    ("upstream_identity_verified", True),
])
def test_snapshot_rejects_inconsistent_provenance(tmp_path, field, value):
    payload = {"_cambridge_snapshot": {"kind": "derived_project_snapshot", "derived_from_parent": True,
        "parent_source_sha256": "a" * 64, "parent_source_locator": "$.Projects[\"p\"]",
        "parent_sha256_status": "computed_from_local_parent_bytes", "snapshot_project_id": "p",
        "upstream_identity_verified": False, "upstream_identity_verification": "not_performed"},
        "Projects": {"p": {"Activities": {}}}, "Calendars": {}}
    payload["_cambridge_snapshot"][field] = value
    path = _write(tmp_path, payload)
    with pytest.raises(ParserRuntimeError, match="provenance"):
        read_schedule(path)


def test_snapshot_rejects_duplicate_json_keys_and_oversize_before_read(tmp_path):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"Projects":{},"Projects":{}}', encoding="utf-8")
    with pytest.raises(ParserRuntimeError, match="invalid"):
        read_schedule(duplicate)
    oversized = tmp_path / "large.json"
    with oversized.open("wb") as handle:
        handle.truncate(10 * 1024 * 1024 + 1)
    with pytest.raises(ParserRuntimeError, match="10 MiB"):
        read_schedule(oversized)


def test_schedule_source_metadata_rejects_non_finite_json_values():
    with pytest.raises(ValidationError, match="finite"):
        SchedulePreview(source_format="cambridge_json", source_sha256="a" * 64,
            parser_version="test", projects=[], selected_project_id=None, tasks=[], wbs=[],
            relationships=[], issues=[], source_metadata={"bad": float("nan")})


def test_snapshot_cli_does_not_overwrite_existing_or_parent_source(tmp_path):
    ops = Path(__file__).resolve().parents[3] / "ops/prepare_cambridge_import.py"
    spec = importlib.util.spec_from_file_location("prepare_cambridge_import", ops)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "parent.json"
    source.write_text('{"Projects":{"p":{"Activities":{}}},"Calendars":{}}', encoding="utf-8")
    existing = tmp_path / "already-there.json"
    existing.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        module.prepare(source, "p", existing)
    with pytest.raises(ValueError, match="must not be the Cambridge parent"):
        module.prepare(source, "p", source)
    assert existing.read_text(encoding="utf-8") == "keep"
    assert source.read_text(encoding="utf-8").startswith('{"Projects"')
