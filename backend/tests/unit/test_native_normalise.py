from datetime import date
from pathlib import Path

import pytest

from app.ingest.native_schedule.microsoft import read_schedule
from app.ingest.native_schedule.normalise import MappingError, normalise_schedule
from app.schemas.native_schedule import ReviewedScheduleMapping


ROOT = Path(__file__).resolve().parents[3]


def test_reviewer_mapping_produces_valid_csv_without_inventing_quantities():
    preview = read_schedule(ROOT / "backend/tests/fixtures/native_schedule/tiny_mspdi.xml")
    mapping = ReviewedScheduleMapping(
        baseline_date=date(2026, 9, 19),
        source_project_id=preview.selected_project_id,
        task_overrides={
            "24": {
                "discipline": "piping",
                "work_type": "pipe_spool_erection",
                "measurement_basis": "quantity_ratio",
                "planned_quantity": "12",
                "unit": "spool",
                "baseline_quantity": "0",
            }
        },
        reason="human_confirmed: synthetic demo mapping",
    )
    result = normalise_schedule(preview, mapping)
    assert "24,Erect spools" in result.canonical_csv
    assert "25,Inspect line" in result.canonical_csv
    assert result.task_metadata["24"].source_task_id == "24"


def test_unknown_override_and_quantity_basis_are_rejected():
    preview = read_schedule(ROOT / "backend/tests/fixtures/native_schedule/tiny_mspdi.xml")
    mapping = ReviewedScheduleMapping(
        baseline_date=date(2026, 9, 19),
        source_project_id=preview.selected_project_id,
        task_overrides={"missing": {}},
        reason="reviewed",
    )
    with pytest.raises(MappingError, match="unknown"):
        normalise_schedule(preview, mapping)
