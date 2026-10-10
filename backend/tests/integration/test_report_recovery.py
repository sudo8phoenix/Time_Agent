"""PostgreSQL constraint rollback must remove an intake's stored file."""
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models import Project, Report
from app.db.session import engine
from app.ingest import reports


@pytest.fixture
def intake_db(tmp_path, monkeypatch):
    connection = engine.connect()
    outer = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    monkeypatch.setattr(reports, "get_settings", lambda: type("Settings", (), {"upload_dir": str(tmp_path / "uploads")})())
    db = factory()
    project = Project(name=f"report-recovery-{uuid4().hex}", timezone="UTC")
    db.add(project)
    db.flush()
    try:
        yield db, project, tmp_path / "uploads"
    finally:
        db.rollback()
        db.close()
        outer.rollback()
        connection.close()


def test_unique_report_constraint_failure_rolls_back_rows_and_removes_artifact(intake_db, monkeypatch):
    db, project, upload_dir = intake_db
    raw = b"A report that will collide after its storage write."
    digest = __import__("hashlib").sha256(raw).hexdigest()
    # Ingestion scopes deduplication identity by report date (and metadata),
    # even when no date is supplied. Mirror that persisted identity so the
    # injected competing insert exercises the actual unique constraint.
    identity = __import__("hashlib").sha256(f"{digest}:".encode()).hexdigest()
    original_store = reports._store_original

    def store_then_create_racing_duplicate(storage_key, payload):
        original_store(storage_key, payload)
        # Simulate a competing intake inserting the same project/content hash
        # after this request's preflight lookup. PostgreSQL enforces the real
        # reports(project_id, content_hash) unique constraint below.
        db.add(Report(project_id=project.id, content_hash=identity))
        db.flush()

    monkeypatch.setattr(reports, "_store_original", store_then_create_racing_duplicate)
    with pytest.raises(IntegrityError):
        reports.ingest_report(db, project, raw, filename="daily.txt")

    db.rollback()
    assert not list(Path(upload_dir).rglob("*.pending"))
    assert not list(Path(upload_dir).rglob("*.txt"))
    assert db.query(Report).filter(Report.project_id == project.id, Report.content_hash == identity).count() == 0
