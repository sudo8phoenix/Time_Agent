import pytest
from pydantic import ValidationError

from app.schemas.native_schedule import SchedulePreview, SourceRelation


def preview_payload():
    return {
        "source_format": "p6_xml", "source_sha256": "a" * 64, "parser_version": "mpxj-test",
        "projects": [{"source_project_id": "P1", "name": "Demo"}], "selected_project_id": "P1",
        "tasks": [{"source_task_id": "1001", "external_id": "00024", "name": "Erect spools",
                    "source_wbs_id": "W1", "is_summary": False, "is_milestone": False,
                    "planned_start": "2026-09-20", "planned_finish": "2026-09-25",
                    "actual_start": None, "actual_finish": None, "source_fields": {"calendar_id": "CAL1"}}],
        "wbs": [{"source_wbs_id": "W1", "parent_source_wbs_id": None, "code": "UTIL",
                 "name": "Utilities", "path": ["Utilities"]}],
        "relationships": [], "issues": []}


def test_worked_mapping_preview_shape_validates():
    model = SchedulePreview.model_validate(preview_payload())
    assert model.tasks[0].external_id == "00024"


def test_all_keys_required_and_extras_forbidden():
    value = preview_payload(); del value["selected_project_id"]
    with pytest.raises(ValidationError): SchedulePreview.model_validate(value)
    value = preview_payload(); value["unexpected"] = 1
    with pytest.raises(ValidationError): SchedulePreview.model_validate(value)


def test_decimal_lag_is_string_and_finite():
    base = {"predecessor_source_task_id": "1", "successor_source_task_id": "2",
            "relation_type": "FS", "lag_value": "1.25", "lag_unit": "day", "external_project_id": None}
    assert SourceRelation.model_validate(base).lag_value == "1.25"
    for bad in ("NaN", "Infinity", 1.25):
        with pytest.raises(ValidationError): SourceRelation.model_validate({**base, "lag_value": bad})
    missing = dict(base); del missing["external_project_id"]
    with pytest.raises(ValidationError): SourceRelation.model_validate(missing)


def test_source_fields_reject_nonfinite_json():
    with pytest.raises(ValidationError):
        SchedulePreview.model_validate({**preview_payload(), "tasks": [{**preview_payload()["tasks"][0], "source_fields": {"x": float("nan")}}]})
