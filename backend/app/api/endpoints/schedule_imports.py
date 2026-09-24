"""Authenticated native schedule import preview, mapping and staging routes."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import select

from ...db.models import FileRecord, Project, ScheduleImport, ScheduleVersion, User
from ...db.session import get_session
from ...ingest.native_schedule.dispatch import preview_schedule
from ...ingest.native_schedule.normalise import MappingError, normalise_schedule
from ...ingest.native_schedule.runner import ParserRuntimeError
from ...ingest.native_schedule.storage import create_import, stage_import
from ...schemas.native_schedule import ReviewedScheduleMapping, SchedulePreview
from ...settings import get_settings
from ..dependencies import current_user, project_access, require_reviewer

router = APIRouter(
    prefix="/projects/{project_id}/schedule-imports", tags=["native-schedule-imports"]
)


class SelectProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    source_project_id: str = Field(min_length=1)


class MappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    mapping: ReviewedScheduleMapping


class StageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


def _error(exc: Exception) -> HTTPException:
    code = exc.code if isinstance(exc, ParserRuntimeError) else str(exc).split(":", 1)[0]
    status = {
        "SCHEDULE_FORMAT_UNSUPPORTED": 415,
        "SCHEDULE_TOO_LARGE": 413,
        "SCHEDULE_PARSER_UNAVAILABLE": 503,
        "SCHEDULE_PARSE_TIMEOUT": 504,
    }.get(code, 422)
    return HTTPException(status, detail={"code": code})


def _record(project: Project, import_id: UUID, db: DBSession, *, lock: bool = False) -> ScheduleImport:
    statement = select(ScheduleImport).where(ScheduleImport.id == import_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    record = db.scalar(statement)
    if record is None or record.project_id != project.id:
        raise HTTPException(404, "Schedule import not found")
    return record


def _payload(record: ScheduleImport) -> dict[str, object]:
    return {
        "id": str(record.id),
        "project_id": str(record.project_id),
        "revision": record.revision,
        "state": record.state,
        "source_format": record.source_format,
        "parser_version": record.parser_version,
        "selected_source_project_id": record.selected_source_project_id,
        "preview": record.preview,
        "reviewed_mapping": record.reviewed_mapping,
        "staged_schedule_version_id": str(record.staged_schedule_version_id)
        if record.staged_schedule_version_id
        else None,
        "error_code": record.error_code,
    }


@router.post("", status_code=201)
async def create_schedule_import(
    project: Project = Depends(project_access),
    upload: UploadFile = File(...),
    reviewer: User = Depends(require_reviewer),
    db: DBSession = Depends(get_session),
):
    try:
        db.execute(select(Project).where(Project.id == project.id).with_for_update())
        record = create_import(
            db,
            project,
            await upload.read(10 * 1024 * 1024 + 1),
            filename=upload.filename or "schedule",
            mime_type=upload.content_type or "application/octet-stream",
            creator_id=reviewer.id,
        )
        return _payload(record)
    except (ParserRuntimeError, MappingError, ValueError) as exc:
        raise _error(exc) from exc


@router.get("/{import_id}")
def get_schedule_import(
    import_id: UUID,
    project: Project = Depends(project_access),
    _user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
):
    return _payload(_record(project, import_id, db))


@router.post("/{import_id}/select-project")
def select_source_project(
    import_id: UUID,
    body: SelectProjectRequest,
    project: Project = Depends(project_access),
    _reviewer: User = Depends(require_reviewer),
    db: DBSession = Depends(get_session),
):
    record = _record(project, import_id, db, lock=True)
    if record.revision != body.expected_revision or record.state == "staged":
        raise HTTPException(
            409, detail={"code": "SCHEDULE_IMPORT_CONFLICT", "current_revision": record.revision}
        )
    file_record = db.get(FileRecord, record.file_id)
    if file_record is None:
        raise HTTPException(422, detail={"code": "SCHEDULE_PARSE_FAILED"})
    try:
        preview = preview_schedule(
            Path(get_settings().upload_dir).resolve() / file_record.storage_key,
            body.source_project_id,
        )
    except ParserRuntimeError as exc:
        raise _error(exc) from exc
    record.preview = preview.model_dump(mode="json")
    record.selected_source_project_id = preview.selected_project_id
    record.reviewed_mapping = None
    record.state = "needs_mapping"
    record.revision += 1
    db.flush()
    return _payload(record)


@router.post("/{import_id}/mapping")
def save_mapping(
    import_id: UUID,
    body: MappingRequest,
    project: Project = Depends(project_access),
    _reviewer: User = Depends(require_reviewer),
    db: DBSession = Depends(get_session),
):
    record = _record(project, import_id, db, lock=True)
    if record.revision != body.expected_revision or record.state == "staged":
        raise HTTPException(
            409, detail={"code": "SCHEDULE_IMPORT_CONFLICT", "current_revision": record.revision}
        )
    try:
        normalise_schedule(SchedulePreview.model_validate(record.preview), body.mapping)
    except (MappingError, ValueError) as exc:
        raise _error(exc) from exc
    record.reviewed_mapping = body.mapping.model_dump(mode="json")
    record.selected_source_project_id = body.mapping.source_project_id
    record.state = "ready"
    record.revision += 1
    db.flush()
    return _payload(record)


@router.post("/{import_id}/stage", status_code=201)
def stage_schedule_import(
    import_id: UUID,
    body: StageRequest,
    project: Project = Depends(project_access),
    _reviewer: User = Depends(require_reviewer),
    db: DBSession = Depends(get_session),
    response: Response = None,
):
    db.execute(select(Project).where(Project.id == project.id).with_for_update())
    record = _record(project, import_id, db, lock=True)
    if record.revision != body.expected_revision or record.state != "ready":
        raise HTTPException(
            409, detail={"code": "SCHEDULE_IMPORT_CONFLICT", "current_revision": record.revision}
        )
    try:
        staged, existing = stage_import(
            db, record, ReviewedScheduleMapping.model_validate(record.reviewed_mapping)
        )
    except (MappingError, ValueError) as exc:
        raise _error(exc) from exc
    result = _payload(staged)
    result.update(
        {
            "schedule_version_id": str(staged.staged_schedule_version_id),
            "version": db.get(ScheduleVersion, staged.staged_schedule_version_id).version_number,
            "existing": existing,
        }
    )
    if existing and response is not None:
        response.status_code = 200
    return result
