from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.models import Job, Project, Report, ScheduleVersion
from app.db.session import engine
from app.jobs.service import claim_job, enqueue_job, publish_stage, retry_job
from app.jobs.worker import run_once


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    session = factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _rows(db):
    project = Project(name=f"job-test-{uuid4().hex}")
    db.add(project)
    db.flush()
    version = ScheduleVersion(project_id=project.id, version_number=1, content_sha256=uuid4().hex)
    db.add(version)
    db.flush()
    project.active_schedule_version_id = version.id
    report = Report(project_id=project.id, content_hash=uuid4().hex)
    db.add(report)
    db.flush()
    return project, version, report


def test_duplicate_enqueue_and_terminal_not_reclaimed(db):
    project, _, report = _rows(db)
    first, existing = enqueue_job(db, project, report)
    second, reused = enqueue_job(db, project, report)
    assert existing is False and reused is True and first.id == second.id
    assert run_once(db, lambda *_: {"state": "ready_for_review"}) is True
    assert run_once(db, lambda *_: pytest.fail("terminal job reclaimed")) is False


def test_expired_lease_replaced_and_old_publish_rejected(db):
    project, _, report = _rows(db)
    job, _ = enqueue_job(db, project, report)
    old, old_token = claim_job(db, now=datetime.now(timezone.utc))
    old.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    replacement, new_token = claim_job(db, now=datetime.now(timezone.utc))
    assert replacement.id == old.id and replacement.lease_token != old_token
    with pytest.raises(RuntimeError, match="JOB_LEASE_LOST"):
        publish_stage(db, old.id, old_token, stage="persist", now=datetime.now(timezone.utc))
    publish_stage(db, replacement.id, new_token, stage="persist", state="ready_for_review")


def test_pipeline_exception_can_retry_then_terminal(db):
    project, _, report = _rows(db)
    job, _ = enqueue_job(db, project, report)
    calls = []

    def broken(*_):
        calls.append(1)
        raise ValueError("bounded failure")

    assert run_once(db, broken) is True
    assert job.state == "failed" and len(calls) == 1
    retry_job(db, job)
    assert run_once(db, broken) is True
    assert job.attempts == 2 and len(calls) == 2
    retry_job(db, job)
    assert run_once(db, broken) is True
    assert job.attempts == 3
    with pytest.raises(ValueError, match="JOB_ATTEMPT_LIMIT"):
        retry_job(db, job)


def test_schedule_change_publishes_stale(db):
    project, version, report = _rows(db)
    job, _ = enqueue_job(db, project, report)
    claimed, token = claim_job(db)
    newer = ScheduleVersion(project_id=project.id, version_number=2, content_sha256=uuid4().hex)
    db.add(newer)
    db.flush()
    project.active_schedule_version_id = newer.id
    result = publish_stage(db, claimed.id, token, stage="persist", state="ready_for_review")
    assert result.state == "stale"
    assert result.error_code == "SCHEDULE_VERSION_STALE"
    assert result.lease_token is None
