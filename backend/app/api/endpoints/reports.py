from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession
from starlette.datastructures import UploadFile
from ...db.models import Project, Fragment
from ...db.session import get_session
from ...ingest.reports import ingest_report
from ...jobs.service import enqueue_job
from ..dependencies import project_access, require_reviewer

router=APIRouter(prefix="/projects/{project_id}/reports", tags=["reports"])
class TextReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=10*1024*1024)
    report_date: date|None=None
    report_date_evidence: str|None=None
    source_label: str|None=None


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
        return (await upload.read(), upload.filename, upload.content_type or "application/octet-stream", report_date,
                form.get("report_date_evidence") or None, form.get("source_label") or None)
    if text:
        return (str(text).encode("utf-8"), "pasted-report.txt", "text/plain", report_date,
                form.get("report_date_evidence") or None, form.get("source_label") or None)
    raise HTTPException(422, detail={"code": "REPORT_INPUT_REQUIRED"})

@router.post("", status_code=202)
async def create_report(request: Request, project: Project=Depends(project_access), db: DBSession=Depends(get_session), reviewer=Depends(require_reviewer)):
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type == "application/json":
        try:
            body = TextReport.model_validate(await request.json())
        except Exception as exc:
            raise HTTPException(422, detail={"code": "REPORT_INVALID", "message": "invalid text report body"}) from exc
        raw, name, mime = body.text.encode("utf-8"), "pasted-report.txt", "text/plain"
        report_date, report_date_evidence, source_label = body.report_date, body.report_date_evidence, body.source_label
    elif content_type == "multipart/form-data":
        form = await request.form()
        raw, name, mime, report_date, report_date_evidence, source_label = await _multipart_input(form)
    else:
        raise HTTPException(415, detail={"code": "REPORT_CONTENT_TYPE_UNSUPPORTED"})
    try:
        report,existing=ingest_report(db,project,raw,filename=name,mime=mime,report_date=report_date,report_date_evidence=report_date_evidence,source_label=source_label,uploader_id=reviewer.id)
        job,job_existing=enqueue_job(db,project,report)
    except ValueError as exc: raise HTTPException(409 if str(exc)=="PROJECT_HAS_NO_ACTIVE_SCHEDULE" else 422, detail={"code":str(exc) if str(exc)=="PROJECT_HAS_NO_ACTIVE_SCHEDULE" else "REPORT_INVALID","message":str(exc)}) from exc
    except OSError as exc:
        raise HTTPException(503, detail={"code": "REPORT_STORAGE_FAILED", "message": "report storage is unavailable"}) from exc
    return {"report_id":str(report.id),"job_id":str(job.id),"existing":existing or job_existing,"state":job.state,"fragments_url":f"/api/v1/reports/{report.id}"}

@router.get("/{report_id}")
def get_report(report_id: UUID, project: Project=Depends(project_access), db: DBSession=Depends(get_session), _reviewer=Depends(require_reviewer)):
    from ...db.models import Report
    report=db.query(Report).filter(Report.id==report_id,Report.project_id==project.id).first()
    if not report: raise HTTPException(404,"Report not found")
    fragments=db.query(Fragment).filter(Fragment.report_id==report.id).order_by(Fragment.ordinal).all()
    return {"report_id":str(report.id),"project_id":str(project.id),"report_date":report.report_date,"report_date_evidence":report.report_date_evidence,"content_hash":report.content_hash,"parsing_warnings":__import__('json').loads(report.parsing_warnings or '[]'),"fragments":[{"id":str(f.id),"locator":f.locator,"original_text":f.original_text,"normalised_text":f.normalised_text,"ocr_status":f.ocr_status} for f in fragments]}
