from datetime import date
import json
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession
from starlette.datastructures import UploadFile
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartParser, MultiPartException
from ...db.models import Project, Fragment, Observation, Proposal, Report, Job
from ...db.session import get_session
from ...ingest.reports import MAX_BYTES, ingest_report
from ...jobs.service import enqueue_job, enqueue_reanalysis
from ..dependencies import current_reviewer, project_access, require_reviewer

router=APIRouter(prefix="/projects/{project_id}/reports", tags=["reports"])
class TextReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=10*1024*1024)
    report_date: date|None=None
    report_date_evidence: str|None=None
    source_label: str|None=None

class ReanalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def reason_is_nonblank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("reason must contain at least three non-whitespace characters")
        return value


async def _multipart_input(form):
    """Validate the mutually exclusive multipart report inputs."""
    upload = form.get("file")
    text = form.get("text")
    report_date = form.get("report_date") or None
    if report_date:
        try:
            report_date = date.fromisoformat(str(report_date))
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "REPORT_INVALID", "message": "report_date must be ISO date YYYY-MM-DD"}) from exc
    if upload is not None and isinstance(upload, UploadFile):
        if text:
            raise HTTPException(422, detail={"code": "REPORT_INPUT_AMBIGUOUS"})
        raw = await upload.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, detail={"code": "REPORT_TOO_LARGE"})
        return (raw, upload.filename, upload.content_type or "application/octet-stream", report_date,
                form.get("report_date_evidence") or None, form.get("source_label") or None)
    if text:
        return (str(text).encode("utf-8"), "pasted-report.txt", "text/plain", report_date,
                form.get("report_date_evidence") or None, form.get("source_label") or None)
    raise HTTPException(422, detail={"code": "REPORT_INPUT_REQUIRED"})


async def _bounded_stream(request: Request):
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BYTES + 64 * 1024:
            raise HTTPException(413, detail={"code": "REPORT_TOO_LARGE"})
        yield chunk

@router.post("", status_code=202)
async def create_report(request: Request, project: Project=Depends(project_access), db: DBSession=Depends(get_session), reviewer=Depends(require_reviewer)):
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_BYTES + 64 * 1024:
        raise HTTPException(413, detail={"code": "REPORT_TOO_LARGE"})
    mapping = None
    intake_metadata = None
    if content_type == "application/json":
        try:
            body = TextReport.model_validate(json.loads(b"".join([chunk async for chunk in _bounded_stream(request)])))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, detail={"code": "REPORT_INVALID", "message": "invalid text report body"}) from exc
        raw, name, mime = body.text.encode("utf-8"), "pasted-report.txt", "text/plain"
        report_date, report_date_evidence, source_label = body.report_date, body.report_date_evidence, body.source_label
    elif content_type == "multipart/form-data":
        try:
            form = await MultiPartParser(request.headers, _bounded_stream(request), max_files=1, max_fields=8).parse()
        except MultiPartException as exc:
            raise HTTPException(422, detail={"code": "REPORT_INVALID", "message": str(exc)}) from exc
        try:
            raw, name, mime, report_date, report_date_evidence, source_label = await _multipart_input(form)
            if form.get("mapping_id"):
                from ...db.models import ReportMapping
                from ...ingest.report_mapping import MappingSpec, mapped_rows
                try:
                    mapping_id = UUID(str(form.get("mapping_id")))
                except ValueError as exc:
                    raise HTTPException(422, "Invalid mapping ID") from exc
                saved = db.scalar(select(ReportMapping).where(ReportMapping.id == mapping_id, ReportMapping.project_id == project.id))
                if saved is None:
                    raise HTTPException(404, "Mapping not found")
                mapping = MappingSpec.model_validate(saved.spec)
                _, _, metadata = await run_in_threadpool(mapped_rows, raw, mapping)
                if metadata["header_signature"] != saved.header_signature:
                    raise HTTPException(422, "Headers changed; preview and confirm a new mapping")
                intake_metadata = {"mapping_id": str(saved.id), "mapping_revision": saved.revision}
            elif form.get("mapping"):
                from ...ingest.report_mapping import MappingSpec
                mapping = MappingSpec.model_validate_json(str(form.get("mapping")))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            await form.close()
    else:
        raise HTTPException(415, detail={"code": "REPORT_CONTENT_TYPE_UNSUPPORTED"})
    try:
        report,existing=await run_in_threadpool(ingest_report,db,project,raw,filename=name,mime=mime,report_date=report_date,report_date_evidence=report_date_evidence,source_label=source_label,uploader_id=reviewer.id,mapping=mapping,ingestion_metadata=intake_metadata)
        job,job_existing=enqueue_job(db,project,report)
    except ValueError as exc: raise HTTPException(409 if str(exc)=="PROJECT_HAS_NO_ACTIVE_SCHEDULE" else 422, detail={"code":str(exc) if str(exc)=="PROJECT_HAS_NO_ACTIVE_SCHEDULE" else "REPORT_INVALID","message":str(exc)}) from exc
    except OSError as exc:
        raise HTTPException(503, detail={"code": "REPORT_STORAGE_FAILED", "message": "report storage is unavailable"}) from exc
    proposal_ids = db.scalars(
        select(Proposal.id)
        .join(Observation, Observation.id == Proposal.observation_id)
        .where(Observation.job_id == job.id, Proposal.review_state == "pending")
        .order_by(Proposal.created_at)
    ).all()
    return {
        "report_id": str(report.id),
        "job_id": str(job.id),
        "project_id": str(job.project_id),
        "schedule_version_id": str(job.schedule_version_id),
        "existing": existing or job_existing,
        "state": job.state,
        "stage": job.stage,
        "attempts": job.attempts,
        "extracted_count": job.extracted_count,
        "proposal_count": job.proposal_count,
        "proposal_ids": [str(value) for value in proposal_ids],
        "error_code": job.error_code,
        "fragments_url": f"/api/v1/reports/{report.id}",
    }

@router.post("/{report_id}/reanalysis", status_code=202)
def reanalyze_report(report_id: UUID, body: ReanalysisRequest, project: Project=Depends(project_access),
                     db: DBSession=Depends(get_session), reviewer=Depends(require_reviewer)):
    report = db.scalar(select(Report).where(Report.id == report_id, Report.project_id == project.id))
    if report is None:
        raise HTTPException(404, "Report not found")
    try:
        job, existing = enqueue_reanalysis(db, project, report, actor_id=reviewer.id,
                                           reason=body.reason.strip(), idempotency_key=body.idempotency_key)
    except ValueError as exc:
        code = str(exc)
        status = 409 if code in {"PROJECT_HAS_NO_ACTIVE_SCHEDULE", "REPORT_SCHEDULE_NOT_ACTIVE", "REANALYSIS_KEY_CONFLICT"} else 404
        raise HTTPException(status, detail={"code": code}) from exc
    proposal_ids = db.scalars(select(Proposal.id).join(Observation, Observation.id == Proposal.observation_id)
                              .where(Observation.job_id == job.id, Proposal.review_state == "pending")
                              .order_by(Proposal.created_at)).all()
    return {"report_id": str(report.id), "job_id": str(job.id), "parent_job_id": str(job.parent_job_id),
            "project_id": str(job.project_id), "schedule_version_id": str(job.schedule_version_id),
            "existing": existing, "reanalysis": {"actor_id": str(job.reanalysis_actor_id),
            "reason": job.reanalysis_reason, "config": job.config_snapshot}, "state": job.state,
            "stage": job.stage, "attempts": job.attempts, "extracted_count": job.extracted_count,
            "proposal_count": job.proposal_count, "proposal_ids": [str(value) for value in proposal_ids]}

@router.get("/{report_id}/runs")
def report_runs(report_id: UUID, project: Project=Depends(project_access),
                db: DBSession=Depends(get_session), _reviewer=Depends(current_reviewer)):
    report = db.scalar(select(Report).where(Report.id == report_id, Report.project_id == project.id))
    if report is None:
        raise HTTPException(404, "Report not found")
    jobs = db.scalars(select(Job).where(Job.report_id == report.id).order_by(Job.created_at, Job.id)).all()
    return {"report_id": str(report.id), "items": [{"job_id": str(job.id),
            "parent_job_id": str(job.parent_job_id) if job.parent_job_id else None,
            "reanalysis_actor_id": str(job.reanalysis_actor_id) if job.reanalysis_actor_id else None,
            "reanalysis_reason": job.reanalysis_reason, "reanalysis_config": job.config_snapshot,
            "schedule_version_id": str(job.schedule_version_id), "state": job.state,
            "stage": job.stage, "attempts": job.attempts, "created_at": job.created_at}
            for job in jobs]}

@router.get("/{report_id}")
def get_report(report_id: UUID, project: Project=Depends(project_access), db: DBSession=Depends(get_session), _reviewer=Depends(current_reviewer)):
    from ...db.models import Report
    report=db.query(Report).filter(Report.id==report_id,Report.project_id==project.id).first()
    if not report: raise HTTPException(404,"Report not found")
    fragments=db.query(Fragment).filter(Fragment.report_id==report.id).order_by(Fragment.ordinal).all()
    return {"report_id":str(report.id),"project_id":str(project.id),"report_date":report.report_date,"report_date_evidence":report.report_date_evidence,"content_hash":report.content_hash,"ingestion_metadata":report.ingestion_metadata,"original_url":f"/api/v1/projects/{project.id}/reports/{report.id}/original","parsing_warnings":__import__('json').loads(report.parsing_warnings or '[]'),"fragments":[{"id":str(f.id),"locator":f.locator,"original_text":f.original_text,"normalised_text":f.normalised_text,"ocr_status":f.ocr_status} for f in fragments]}
