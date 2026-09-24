from uuid import UUID
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import select
from ...db.models import Activity, ActivityState, Project, Proposal, ScheduleVersion
from ...db.session import get_session
from ...ingest.schedules import stage_schedule
from ..dependencies import project_access, require_reviewer

router = APIRouter(prefix="/projects/{project_id}/schedules", tags=["schedules"])

@router.post("")
async def import_schedule(project: Project = Depends(project_access), upload: UploadFile = File(...), db: DBSession = Depends(get_session), _reviewer=Depends(require_reviewer)):
    raw = await upload.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, detail={"code": "SCHEDULE_TOO_LARGE"})
    db.execute(select(Project).where(Project.id == project.id).with_for_update())
    version, digest, errors, existing = stage_schedule(db, project, raw)
    if errors: raise HTTPException(422, detail={"code": "SCHEDULE_INVALID", "errors": errors})
    return {"id": str(version.id), "project_id": str(project.id), "version": version.version_number, "state": version.state, "content_sha256": digest, "existing": existing, "activity_count": len(version.activities)}

class ActivationRequest(BaseModel):
    expected_active_version: int | None = None

@router.post("/{version}/activate")
def activate_schedule(version: int, body: ActivationRequest, project: Project = Depends(project_access), db: DBSession = Depends(get_session), _reviewer=Depends(require_reviewer)):
    project = db.scalar(select(Project).where(Project.id == project.id).with_for_update().execution_options(populate_existing=True))
    current = db.get(ScheduleVersion, project.active_schedule_version_id) if project.active_schedule_version_id else None
    if body.expected_active_version != (current.version_number if current else None):
        raise HTTPException(409, detail={"code": "SCHEDULE_VERSION_CONFLICT"})
    target = db.query(ScheduleVersion).filter(ScheduleVersion.project_id == project.id, ScheduleVersion.version_number == version).first()
    if not target: raise HTTPException(404, "Schedule version not found")
    if current and target.id == current.id:
        return {"id": str(target.id), "version": target.version_number, "state": target.state}
    # ActivityState revisions represent accepted progress in the current persistence foundation.
    if current and db.query(ActivityState).join(ActivityState.activity).filter(
        Activity.schedule_version_id == current.id,
        ActivityState.revision > 0,
    ).first():
        raise HTTPException(409, detail={"code": "SCHEDULE_REBASE_REQUIRED"})
    if current: current.state = "superseded"
    db.query(Proposal).filter(Proposal.project_id == project.id, Proposal.review_state == "pending").update({"review_state": "stale"}, synchronize_session=False)
    target.state = "active"; project.active_schedule_version_id = target.id
    db.flush()
    return {"id": str(target.id), "version": target.version_number, "state": target.state}
