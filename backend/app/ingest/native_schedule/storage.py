"""Atomic persistence for reviewed native schedule imports and provenance."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import FileRecord, Project, ScheduleImport, ScheduleSourceMetadata
from app.ingest.native_schedule.dispatch import preview_schedule
from app.ingest.native_schedule.normalise import normalise_schedule
from app.ingest.reports import _remove_original, _store_original
from app.ingest.schedules import stage_schedule
from app.schemas.native_schedule import ReviewedScheduleMapping
from app.settings import get_settings


def _mapping_hash(mapping: ReviewedScheduleMapping) -> str:
    return hashlib.sha256(
        json.dumps(mapping.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def create_import(
    db: Session, project: Project, raw: bytes, *, filename: str, mime_type: str, creator_id=None
) -> ScheduleImport:
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise ValueError("SCHEDULE_TOO_LARGE")
    digest = hashlib.sha256(raw).hexdigest()
    existing = db.scalar(
        select(ScheduleImport)
        .join(FileRecord)
        .where(ScheduleImport.project_id == project.id, FileRecord.sha256 == digest)
    )
    if existing:
        return existing
    name = Path(filename).name
    storage_key = f"{project.id}/native/{uuid.uuid4().hex}-{name}"
    _store_original(storage_key, raw)
    try:
        file_record = FileRecord(
            project_id=project.id,
            original_filename=name,
            storage_key=storage_key,
            sha256=digest,
            mime_type=mime_type,
            size=len(raw),
            source_kind="native_schedule",
            uploader_id=creator_id,
        )
        db.add(file_record)
        db.flush()
        preview = preview_schedule(Path(get_settings().upload_dir).resolve() / storage_key)
        record = ScheduleImport(
            project_id=project.id,
            file_id=file_record.id,
            source_format=preview.source_format,
            parser_version=preview.parser_version,
            selected_source_project_id=preview.selected_project_id,
            preview=preview.model_dump(mode="json"),
            state="needs_mapping" if preview.selected_project_id else "needs_project",
            creator_id=creator_id,
        )
        db.add(record)
        db.flush()
        return record
    except Exception:
        _remove_original(storage_key)
        raise


def stage_import(db: Session, record: ScheduleImport, mapping: ReviewedScheduleMapping):
    if record.state == "staged":
        return record, True
    if record.project_id is None:
        raise ValueError("SCHEDULE_IMPORT_CONFLICT")
    preview = record.preview
    from app.schemas.native_schedule import SchedulePreview

    normalised = normalise_schedule(SchedulePreview.model_validate(preview), mapping)
    mapping_hash = _mapping_hash(mapping)
    version, digest, errors, existing = stage_schedule(
        db, db.get(Project, record.project_id), normalised.canonical_csv
    )
    if errors or version is None:
        raise ValueError("SCHEDULE_MAPPING_INVALID")
    existing_metadata = db.get(ScheduleSourceMetadata, version.id)
    if existing_metadata and existing_metadata.schedule_import_id != record.id:
        raise ValueError("SCHEDULE_PROVENANCE_CONFLICT")
    if existing and not existing_metadata:
        raise ValueError("SCHEDULE_PROVENANCE_CONFLICT")
    if not existing_metadata:
        db.add(
            ScheduleSourceMetadata(
                schedule_version_id=version.id,
                schedule_import_id=record.id,
                source_project_id=mapping.source_project_id,
                source_file_hash=preview["source_sha256"],
                parser_version=preview["parser_version"],
                reviewed_mapping=mapping.model_dump(mode="json"),
                mapping_hash=mapping_hash,
                task_metadata={
                    key: value.model_dump(mode="json")
                    for key, value in normalised.task_metadata.items()
                },
                wbs=[value.model_dump(mode="json") for value in normalised.wbs],
                relationships=[value.model_dump(mode="json") for value in normalised.relationships],
            )
        )
    record.reviewed_mapping = mapping.model_dump(mode="json")
    record.mapped_content_hash = digest
    record.staged_schedule_version_id = version.id
    record.state = "staged"
    record.revision += 1
    db.flush()
    return record, existing
