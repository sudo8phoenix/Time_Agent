from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from ...db.models import Job, Observation, ProjectMembership, Proposal, User
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

@router.get("/{job_id}")
def status(job_id: UUID, db: Session=Depends(get_session), user: User=Depends(current_user)):
    job = _job_for_user(db, job_id, user)
    if not job: raise HTTPException(404,"Job not found")
    proposal_ids = db.scalars(
        select(Proposal.id)
        .join(Observation, Observation.id == Proposal.observation_id)
        .where(Observation.job_id == job.id, Proposal.review_state == "pending")
        .order_by(Proposal.created_at)
    ).all()
    return {"job_id":str(job.id),"project_id":str(job.project_id),"report_id":str(job.report_id),"schedule_version_id":str(job.schedule_version_id),"state":job.state,"stage":job.stage,"attempts":job.attempts,"extracted_count":job.extracted_count,"proposal_count":job.proposal_count,"proposal_ids":[str(value) for value in proposal_ids],"error_code":job.error_code}

@router.post("/{job_id}/retry", status_code=202)
def retry(job_id: UUID, db: Session=Depends(get_session), reviewer: User=Depends(require_reviewer)):
    job = _job_for_user(db, job_id, reviewer, lock=True)
    if not job: raise HTTPException(404,"Job not found")
    try: retry_job(db, job)
    except ValueError as exc: raise HTTPException(409, detail={"code":str(exc)}) from exc
    return {"job_id":str(job.id),"state":job.state,"attempts":job.attempts}
