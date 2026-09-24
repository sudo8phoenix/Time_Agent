"""Durable queue primitives. Pipeline work is deliberately injected by the worker."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session
from ..db.models import Job, Project, Report

LEASE_SECONDS = 120
MAX_ATTEMPTS = 3
TERMINAL = {"ready_for_review", "needs_transcription", "failed", "stale"}

def _now() -> datetime:
    return datetime.now(timezone.utc)

def enqueue_job(db: Session, project: Project, report: Report) -> tuple[Job, bool]:
    """Create or reuse the report's job. Caller commits report and job together."""
    job = db.scalar(select(Job).where(Job.project_id == project.id, Job.report_id == report.id))
    if job:
        return job, True
    if project.active_schedule_version_id is None:
        raise ValueError("PROJECT_HAS_NO_ACTIVE_SCHEDULE")
    job = Job(project_id=project.id, report_id=report.id,
              schedule_version_id=project.active_schedule_version_id,
              state="queued", stage="parse", attempts=0)
    db.add(job); db.flush()
    return job, False

def claim_job(db: Session, *, now: datetime | None = None) -> tuple[Job, str] | None:
    """Atomically claim one queued or expired-running job with a fresh random token."""
    now = now or _now()
    job = db.scalar(select(Job).where(
        or_(Job.state == "queued", (Job.state == "running") & (Job.lease_expires_at < now)),
        Job.attempts < MAX_ATTEMPTS).order_by(Job.created_at).with_for_update(skip_locked=True))
    if not job:
        return None
    token = uuid4().hex
    job.state = "running"; job.attempts += 1; job.lease_token = token
    job.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS); job.heartbeat_at = now
    db.flush()
    return job, token

def heartbeat(db: Session, job_id: UUID, token: str, *, now: datetime | None = None) -> bool:
    now = now or _now()
    result = db.execute(update(Job).where(Job.id == job_id, Job.state == "running",
        Job.lease_token == token, Job.lease_expires_at > now).values(
            lease_expires_at=now + timedelta(seconds=LEASE_SECONDS), heartbeat_at=now))
    db.flush(); return result.rowcount == 1

def release_job(db: Session, job_id: UUID, token: str) -> bool:
    """Return an owned running job to the queue during graceful shutdown."""
    result = db.execute(update(Job).where(Job.id == job_id, Job.state == "running",
        Job.lease_token == token).values(state="queued", lease_token=None,
        lease_expires_at=None, heartbeat_at=_now()))
    db.flush()
    return result.rowcount == 1

def publish_stage(db: Session, job_id: UUID, token: str, *, stage: str,
                  state: str = "running", extracted_count: int | None = None,
                  proposal_count: int | None = None, error_code: str | None = None,
                  error_message: str | None = None, now: datetime | None = None) -> Job:
    """Publish only while the same unexpired lease owns the job."""
    now = now or _now()
    job = db.scalar(select(Job).where(Job.id == job_id, Job.state == "running",
                                      Job.lease_token == token, Job.lease_expires_at > now).with_for_update())
    if not job: raise RuntimeError("JOB_LEASE_LOST")
    # A job is tied to the schedule snapshot used for extraction.  If the
    # project was activated onto a newer snapshot while the worker was away,
    # do not publish proposals against the old schedule.
    project = db.scalar(select(Project).where(Project.id == job.project_id).with_for_update())
    if project is None:
        raise RuntimeError("PROJECT_NOT_FOUND")
    if project.active_schedule_version_id != job.schedule_version_id:
        job.stage = "persist"
        job.state = "stale"
        job.error_code = "SCHEDULE_VERSION_STALE"
        job.error_message = "Project active schedule changed while job was running"
        job.lease_token = None
        job.lease_expires_at = None
        db.flush()
        return job
    job.stage=stage; job.state=state; job.error_code=error_code; job.error_message=error_message
    if extracted_count is not None: job.extracted_count=extracted_count
    if proposal_count is not None: job.proposal_count=proposal_count
    if state in TERMINAL: job.lease_token=None; job.lease_expires_at=None
    db.flush(); return job

def retry_job(db: Session, job: Job) -> Job:
    if job.state not in {"failed", "stale"}: raise ValueError("JOB_NOT_RETRYABLE")
    if job.attempts >= MAX_ATTEMPTS: raise ValueError("JOB_ATTEMPT_LIMIT")
    job.state="queued"; job.error_code=None; job.error_message=None; job.lease_token=None; job.lease_expires_at=None
    db.flush(); return job
