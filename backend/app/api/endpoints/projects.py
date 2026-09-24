"""Authenticated project selection and creation endpoints."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from ...db.models import Project, ProjectMembership, User
from ...db.session import get_session
from ..dependencies import current_user, require_reviewer


router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=64)


def _project_payload(project: Project) -> dict[str, str | None]:
    return {
        "id": str(project.id),
        "name": project.name,
        "timezone": project.timezone,
        "active_schedule_version_id": (
            str(project.active_schedule_version_id) if project.active_schedule_version_id else None
        ),
    }


@router.get("")
def list_projects(user: User = Depends(current_user), db: DBSession = Depends(get_session)):
    projects = db.scalars(
        select(Project)
        .join(ProjectMembership)
        .where(ProjectMembership.user_id == user.id)
        .order_by(Project.name)
    ).all()
    return {"items": [_project_payload(project) for project in projects], "next_cursor": None}


@router.post("", status_code=201)
def create_project(
    body: CreateProjectRequest,
    reviewer: User = Depends(require_reviewer),
    db: DBSession = Depends(get_session),
):
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(422, detail={"code": "PROJECT_TIMEZONE_INVALID"}) from exc
    project = Project(name=body.name, timezone=body.timezone)
    db.add(project)
    db.flush()
    db.add(ProjectMembership(project_id=project.id, user_id=reviewer.id))
    db.flush()
    return _project_payload(project)
