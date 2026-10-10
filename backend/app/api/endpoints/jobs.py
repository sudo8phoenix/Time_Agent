from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from ...db.models import Job, Observation, ProjectMembership, Proposal, User, Report, FileRecord
from ...db.session import get_session
from ...jobs.service import retry_job
from ..dependencies import current_user, require_reviewer

router=APIRouter(prefix="/jobs", tags=["jobs"])


def _job_for_user(db: Session, job_id: UUID, user: User, *, lock: bool = False) -> Job | None:
    statement = (
        select(Job)
        .join(ProjectMembership, ProjectMembership.project_id == Job.project_id)
        .where(Job.id == job_id, ProjectMembership.user_id == user.id)
    )
    if lock:
        statement = statement.with_for_update()
    return db.scalar(statement)

@router.get("")
def list_jobs(
    project_id: UUID,
    pending_only: bool = False,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    membership = db.get(ProjectMembership, (project_id, user.id))
    if not membership:
        raise HTTPException(403, "Project access denied")
    pending = (select(func.count(Proposal.id))
        .join(Observation, Observation.id == Proposal.observation_id)
        .where(Observation.job_id == Job.id, Proposal.review_state == "pending")
        .correlate(Job).scalar_subquery())
    statement = (select(Job, Report.source_label, FileRecord.original_filename, pending)
        .join(Report, Report.id == Job.report_id)
        .outerjoin(FileRecord, FileRecord.id == Report.file_id)
        .where(Job.project_id == project_id))
    if pending_only:
        statement = statement.where(pending > 0)
    rows = db.execute(statement.order_by(Job.created_at.desc(), Job.id.desc())
        .offset(offset).limit(limit + 1)).all()
    items = [{"job_id": str(job.id), "project_id": str(job.project_id),
        "state": job.state, "stage": job.stage, "proposal_count": job.proposal_count,
        "attempts": job.attempts,
        "pending_count": count, "report_name": label or filename or "Pasted field report",
        "created_at": job.created_at.isoformat(), "error_code": job.error_code}
        for job, label, filename, count in rows[:limit]]
    return {"items": items, "next_offset": offset + limit if len(rows) > limit else None}

@router.get("/{job_id}")
def status(job_id: UUID, db: Session=Depends(get_session), user: User=Depends(current_user)):
    job = _job_for_user(db, job_id, user)
    if not job: raise HTTPException(404,"Job not found")
    proposal_ids = db.scalars(
        select(Proposal.id)
        .join(Observation, Observation.id == Proposal.observation_id)
        .where(Observation.job_id == job.id, Proposal.review_state == "pending")
        .order_by(Observation.ordinal, Proposal.revision, Proposal.id)
    ).all()
    return {"job_id":str(job.id),"project_id":str(job.project_id),"report_id":str(job.report_id),"schedule_version_id":str(job.schedule_version_id),"parent_job_id":str(job.parent_job_id) if job.parent_job_id else None,"reanalysis_actor_id":str(job.reanalysis_actor_id) if job.reanalysis_actor_id else None,"reanalysis_reason":job.reanalysis_reason,"reanalysis_config":job.config_snapshot,"state":job.state,"stage":job.stage,"attempts":job.attempts,"extracted_count":job.extracted_count,"proposal_count":job.proposal_count,"proposal_ids":[str(value) for value in proposal_ids],"error_code":job.error_code}

@router.post("/{job_id}/retry", status_code=202)
def retry(job_id: UUID, db: Session=Depends(get_session), reviewer: User=Depends(require_reviewer)):
    job = _job_for_user(db, job_id, reviewer, lock=True)
    if not job: raise HTTPException(404,"Job not found")
    try: retry_job(db, job)
    except ValueError as exc: raise HTTPException(409, detail={"code":str(exc)}) from exc
    return {"job_id":str(job.id),"state":job.state,"attempts":job.attempts}
