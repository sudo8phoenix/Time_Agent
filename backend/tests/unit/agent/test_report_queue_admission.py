from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HostedProviderAdmission, Job, Project, Report, ScheduleVersion
from app.jobs.admission import report_admission_ready
from app.jobs.service import ADMISSION_RETRY_SECONDS, CLAIM_SCAN_LIMIT, claim_job
from app.jobs.worker import run_once
from app.settings import Settings
from test_agent_tools import Fixture


def queue(blocked_count):
    fixture = Fixture()
    now = datetime.now(timezone.utc)
    with Session(fixture.engine) as db, db.begin():
        first = db.get(Job, fixture.job_id)
        first.state, first.attempts = "queued", 0
        first.lease_token = first.lease_expires_at = None
        first.created_at = now - timedelta(hours=1)
        first.config_snapshot = {"provider": "groq"}
        for index in range(1, blocked_count):
            report = Report(project_id=fixture.project_id, content_hash=uuid4().hex)
            db.add(report)
            db.flush()
            db.add(Job(project_id=fixture.project_id, report_id=report.id,
                       schedule_version_id=fixture.schedule_id, state="queued", attempts=0,
                       created_at=first.created_at + timedelta(seconds=index),
                       config_snapshot={"provider": "groq"}))
        project = Project(name="Independent project")
        db.add(project)
        db.flush()
        schedule = ScheduleVersion(project_id=project.id, version_number=1,
                                   content_sha256=uuid4().hex, state="active")
        db.add(schedule)
        db.flush()
        project.active_schedule_version_id = schedule.id
        report = Report(project_id=project.id, content_hash=uuid4().hex)
        db.add(report)
        db.flush()
        ready = Job(project_id=project.id, report_id=report.id, schedule_version_id=schedule.id,
                    state="queued", attempts=0, created_at=now,
                    config_snapshot={"provider": "ollama"})
        db.add(ready)
        db.add(HostedProviderAdmission(provider="groq", state={
            "cooldown": (now + timedelta(minutes=20)).timestamp(),
        }))
        db.flush()
        ready_id = ready.id
    settings = Settings(_env_file=None, llm_provider="groq", groq_account_scopes_enabled=False)
    def gate(db, job):
        return report_admission_ready(db, job, settings=settings, now=now)
    return fixture, ready_id, now, gate


def test_cooled_head_does_not_block_another_projects_ready_job():
    fixture, ready_id, now, gate = queue(1)
    with Session(fixture.engine) as db:
        claimed, _ = claim_job(db, now=now, admission_check=gate)
        assert claimed.id == ready_id and claimed.attempts == 1
        blocked = db.get(Job, fixture.job_id)
        assert blocked.state == "queued" and blocked.attempts == 0
        assert blocked.lease_token is None and blocked.admission_retry_at is not None
        db.commit()


def test_backlog_larger_than_scan_makes_progress_even_after_deferrals_expire():
    fixture, ready_id, now, gate = queue(CLAIM_SCAN_LIMIT * 2 + 1)
    for poll in range(3):
        with Session(fixture.engine) as db:
            result = claim_job(db, now=now + timedelta(seconds=poll * (ADMISSION_RETRY_SECONDS + 1)),
                               admission_check=gate)
            db.commit()
            if poll < 2:
                assert result is None
            else:
                assert result[0].id == ready_id
    with Session(fixture.engine) as db:
        blocked = db.scalars(select(Job).where(Job.id != ready_id)).all()
        assert all(job.state == "queued" and job.attempts == 0 for job in blocked)


def test_idle_worker_commits_deferrals_without_claiming_or_spending_attempts():
    fixture, ready_id, _now, gate = queue(1)
    with Session(fixture.engine) as db:
        db.delete(db.get(Job, ready_id))
        db.commit()
        assert run_once(db, lambda *_: (_ for _ in ()).throw(AssertionError("no runnable job")),
                        admission_check=gate) is False
    with Session(fixture.engine) as db:
        blocked = db.get(Job, fixture.job_id)
        assert blocked.admission_retry_at is not None
        assert blocked.attempts == 0 and blocked.lease_token is None
