"""GT10 source bytes through mapping, stage, activation and retrieval."""
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.endpoints.schedules import ActivationRequest, activate_schedule
from app.agent.schedule_decision import shortlist_activities
from app.db.models import Activity, Base, Project, ScheduleSourceMetadata, User
from app.ingest.native_schedule.normalise import normalise_schedule
from app.ingest.native_schedule.storage import create_import, stage_import
from app.schemas.native_schedule import ReviewedScheduleMapping, SchedulePreview
from app.settings import get_settings

SOURCE = Path(__file__).resolve().parents[4] / "data/GT10BLDG-P6-Schedule/exports/GT10BLDG_v1_P6_export.xlsx"


def test_gt10_explicit_stage_activate_and_retrieve(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'gt10.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    with Session(engine) as db:
        reviewer = User(username="gt10-reviewer", password_hash="unused", role="reviewer")
        project = Project(name="GT10 development", timezone="Asia/Kolkata")
        db.add_all([reviewer, project])
        db.flush()
        record = create_import(db, project, SOURCE.read_bytes(), filename=SOURCE.name,
                               mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               creator_id=reviewer.id)
        assert record.source_format == "gt10_xlsx"
        preview = SchedulePreview.model_validate(record.preview)
        assert len(preview.tasks) == 140 and len(preview.relationships) == 176
        mapping = ReviewedScheduleMapping(baseline_date=date(2026, 10, 1),
                                          source_project_id="GT10BLDG", task_overrides={},
                                          reason="reviewed development snapshot; discrepancies remain flagged")
        normalise_schedule(preview, mapping)
        record.reviewed_mapping = mapping.model_dump(mode="json")
        record.state = "ready"
        record.revision += 1
        staged, existing = stage_import(db, record, mapping)
        assert not existing and staged.state == "staged"
        assert project.active_schedule_version_id is None
        metadata = db.get(ScheduleSourceMetadata, staged.staged_schedule_version_id)
        assert metadata.source_file_hash == preview.source_sha256
        assert metadata.task_metadata["SUB-010"]["planned_start"] == "2026-10-22 08:00:00"
        assert metadata.task_metadata["SUB-010"]["source_fields"]["raw_cells"]["start_date"]["raw"] == "2026-10-22 08:00:00"
        assert metadata.relationships[0]["lag_unit"] == "source_header_lag_hr_cnt_unverified"
        result = activate_schedule(1, ActivationRequest(expected_active_version=None),
                                   project=project, db=db, _reviewer=reviewer)
        assert result["state"] == "active"
        db.refresh(project)
        assert project.active_schedule_version_id == staged.staged_schedule_version_id
        activities = list(db.scalars(select(Activity).where(Activity.schedule_version_id == staged.staged_schedule_version_id)))
        assert len(activities) == 140
        target = next(activity for activity in activities if activity.external_id == "SUB-010")
        assert target.name == "Excavation for Foundation"
        assert target.actual_start is None and target.actual_finish is None
        assert target.planned_start.isoformat() == "2026-10-22"
        matches = shortlist_activities(
            {"summary": "Excavation for Foundation", "explicit_activity_id": "SUB-010"},
            staged.staged_schedule_version_id, activities,
            model_call=lambda **kwargs: {"candidate_ids": [str(target.id)] if str(target.id) in kwargs["schema"]["properties"]["candidate_ids"]["items"]["enum"] else []},
        )
        assert matches and matches[0].external_id == "SUB-010"
    engine.dispose()
