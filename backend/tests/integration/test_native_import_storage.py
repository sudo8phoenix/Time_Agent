from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.models import Project, ScheduleImport, ScheduleSourceMetadata
from app.db.session import engine
from app.ingest.native_schedule.storage import create_import, stage_import
from app.schemas.native_schedule import ReviewedScheduleMapping
from app.settings import get_settings


ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def db(tmp_path, monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    session = factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_native_import_preserves_source_and_stages_provenance_atomically(db):
    project = Project(name=f"native-{uuid4().hex}", timezone="Asia/Kolkata")
    db.add(project)
    db.flush()
    raw = (ROOT / "PROJECT.xer").read_bytes()
    record = create_import(
        db, project, raw, filename="PROJECT.xer", mime_type="application/octet-stream"
    )
    assert record.state == "needs_mapping"
    assert record.preview["selected_project_id"] == "4507"
    duplicate = create_import(
        db, project, raw, filename="PROJECT.xer", mime_type="application/octet-stream"
    )
    assert duplicate.id == record.id
    mapping = ReviewedScheduleMapping(
        baseline_date=date(2026, 9, 19),
        source_project_id="4507",
        reason="human_confirmed: matching-only import",
    )
    staged, existing = stage_import(db, record, mapping)
    assert existing is False
    assert staged.state == "staged"
    assert db.get(ScheduleImport, record.id).staged_schedule_version_id is not None
    metadata = db.get(ScheduleSourceMetadata, staged.staged_schedule_version_id)
    assert metadata.schedule_import_id == record.id
    assert metadata.source_project_id == "4507"
    assert metadata.task_metadata
