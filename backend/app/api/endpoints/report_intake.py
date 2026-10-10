"""Project-authorized preview, mapping reuse, original download and transcription."""
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartParser

from ...db.models import FileRecord, Fragment, Project, Report, ReportMapping
from ...db.session import get_session
from ...ingest.report_mapping import MappingSpec, mapped_rows, preview
from ...ingest.reports import MAX_BYTES, ingest_report
from ...jobs.service import enqueue_job
from ...settings import get_settings
from ..dependencies import current_reviewer, project_access, require_reviewer
from .reports import _bounded_stream

router = APIRouter(prefix='/projects/{project_id}/reports', tags=['reports'])


def report_for(db, project, report_id):
    report = db.scalar(select(Report).where(Report.id == report_id, Report.project_id == project.id))
    if report is None:
        raise HTTPException(404, 'Report not found')
    return report


@router.post('/preview')
async def preview_report(request: Request, project: Project = Depends(project_access),
                         db: Session = Depends(get_session), user=Depends(require_reviewer)):
    form = await MultiPartParser(request.headers, _bounded_stream(request), max_files=1, max_fields=3).parse()
    try:
        upload = form.get('file')
        if upload is None or not hasattr(upload, 'read'):
            raise ValueError('file required')
        raw = await upload.read(MAX_BYTES + 1)
        sheets = await run_in_threadpool(preview, raw)
        spec_json = form.get('mapping')
        result = {'sheets': sheets, 'mappings': [
            {'id': str(m.id), 'template': m.template, 'revision': m.revision,
             'header_signature': m.header_signature, 'spec': m.spec}
            for m in db.scalars(select(ReportMapping).where(ReportMapping.project_id == project.id)
                                .order_by(ReportMapping.created_at.desc()))]}
        if spec_json:
            parts, errors, metadata = await run_in_threadpool(mapped_rows, raw, MappingSpec.model_validate_json(str(spec_json)))
            result.update({'row_errors': errors, 'valid_rows': len(parts), 'header_signature': metadata['header_signature']})
        return result
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        await form.close()


class SaveMapping(BaseModel):
    model_config = ConfigDict(extra='forbid')
    template: str = Field(min_length=1, max_length=100)
    header_signature: str = Field(pattern='^[0-9a-f]{64}$')
    spec: MappingSpec


@router.post('/mappings', status_code=201)
def save_mapping(body: SaveMapping, project: Project = Depends(project_access),
                 db: Session = Depends(get_session), user=Depends(require_reviewer)):
    # Serialize revisions per project, including the first revision.
    db.scalar(select(Project).where(Project.id == project.id).with_for_update())
    latest = db.scalar(select(ReportMapping).where(ReportMapping.project_id == project.id,
        ReportMapping.template == body.template, ReportMapping.header_signature == body.header_signature)
        .order_by(ReportMapping.revision.desc()))
    row = ReportMapping(project_id=project.id, template=body.template, header_signature=body.header_signature,
                        revision=latest.revision + 1 if latest else 1, spec=body.spec.model_dump(), actor_id=user.id)
    db.add(row)
    db.flush()
    return {'id': str(row.id), 'revision': row.revision}


@router.get('/{report_id}/original')
def original(report_id: UUID, project: Project = Depends(project_access), db: Session = Depends(get_session),
             user=Depends(current_reviewer)):
    report = report_for(db, project, report_id)
    file = db.get(FileRecord, report.file_id)
    if file is None or file.project_id != project.id:
        raise HTTPException(404, 'Original unavailable')
    root = Path(get_settings().upload_dir).resolve()
    path = (root / file.storage_key).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, 'Original unavailable')
    return FileResponse(path, media_type="application/pdf" if file.source_kind == "pdf" else "application/octet-stream",
                        content_disposition_type="inline" if file.source_kind == "pdf" else "attachment", filename=file.original_filename,
                        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


class Transcription(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pages: dict[int, str]


@router.post('/{report_id}/transcriptions', status_code=202)
def transcribe(report_id: UUID, body: Transcription, project: Project = Depends(project_access),
               db: Session = Depends(get_session), user=Depends(require_reviewer)):
    report = report_for(db, project, report_id)
    fragments = list(db.scalars(select(Fragment).where(Fragment.report_id == report.id).order_by(Fragment.ordinal)))
    available = {int(f.locator.split(':')[1]): f for f in fragments if f.locator.startswith('page:')}
    if not body.pages or set(body.pages) - set(available):
        raise HTTPException(422, 'Transcription must reference original PDF pages')
    missing = {p for p, f in available.items() if f.ocr_status == 'NEEDS_TRANSCRIPTION'} - set(body.pages)
    if missing:
        raise HTTPException(422, f'Transcribe all unreadable pages: {sorted(missing)}')
    if any(not text.strip() or len(text) > 100000 for text in body.pages.values()):
        raise HTTPException(422, 'Each transcription must contain 1–100,000 characters')
    parts = [(f.locator, body.pages.get(int(f.locator.split(':')[1]), f.original_text)) for f in fragments]
    # Identity is independent of actor/time, so retries do not create another job.
    raw = json.dumps({'source_report_id': str(report.id), 'pages': body.pages}, sort_keys=True).encode()
    child, existing = ingest_report(db, project, raw, filename='transcription.txt',
        report_date=report.report_date, report_date_evidence=report.report_date_evidence,
        uploader_id=user.id, source_label=f'Transcription of {report.id}',
        ingestion_metadata={'source_report_id': str(report.id), 'source_file_id': str(report.file_id),
                            'quality': 'human_transcribed', 'pages': sorted(body.pages)}, parsed_parts=parts)
    if not existing:
        child.ingestion_metadata = {**child.ingestion_metadata, 'transcriber_id': str(user.id),
                                   'transcribed_at': datetime.now(timezone.utc).isoformat()}
    job, _ = enqueue_job(db, project, child)
    return {'report_id': str(child.id), 'job_id': str(job.id), 'project_id': str(project.id),
            'state': job.state, 'stage': job.stage, 'existing': existing}
