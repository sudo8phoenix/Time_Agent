"""Versioned provenance stored in observation JSON, shared by all intake paths.

Current extractors/selectors do not emit calibrated probabilities. Null is deliberate:
match strength, retrieval rank and a quote substring check are not probabilities.
"""
from __future__ import annotations

VERSION = "proposal-provenance-v1"


def unavailable(stage: str, *, version: str | None = None) -> dict:
    return {"score": None, "method": "not_estimated", "version": version,
            "validation_status": "unavailable", "stage": stage,
            "reason": "No independently validated probability estimator is available."}


def capture(fields: dict, selection: dict, *, metadata: dict | None = None) -> dict:
    metadata = metadata or {}
    evidence = fields.get("evidence", [])
    return {
        "version": VERSION,
        "confidence": {
            "extraction": unavailable("extraction", version=metadata.get("prompt_version") or metadata.get("extraction_prompt_version")),
            "linking": unavailable("linking", version=metadata.get("selection_prompt_version")),
        },
        "validation": {
            "status": "requires_authorized_review",
            "field_issues": [{"field": None, "code": warning} for warning in fields.get("warnings", [])],
            "missing_information": selection.get("missing_information", []),
            "evidence_check": "source_quote_check_only_not_correctness",
        },
        "original_fields": fields,
        "original_selection": selection,
        "evidence": evidence,
        "model_metadata": metadata,
    }


def context(db, observation) -> dict:
    from app.db.models import Job, Report, Fragment
    job = db.get(Job, observation.job_id) if observation else None
    report = db.get(Report, job.report_id) if job else None
    stored = (observation.field_evidence or {}).get("provenance") if observation else None
    value = dict(stored) if stored else capture(
        observation.fields or {} if observation else {},
        (observation.field_evidence or {}).get("selection", {}) if observation else {},
    )
    value["capture_status"] = "recorded" if stored else "legacy_metadata_unavailable"
    value["source"] = {
        "report_id": str(job.report_id) if job else None,
        "report_hash": report.content_hash if report else None,
        "source_label": report.source_label if report else None,
        "source_revision": report.source_revision if report else None,
        "job_id": str(job.id) if job else None,
        "schedule_version_id": str(job.schedule_version_id) if job else None,
        "model_version": job.model_version if job else None,
        "prompt_version": job.prompt_version if job else None,
        "config_version": job.config_version if job else None,
    }
    metadata = report.ingestion_metadata or {} if report else {}
    value["intake"] = metadata
    original_id = metadata.get("source_report_id") or (str(report.id) if report else None)
    value["source"]["original_url"] = f"/api/v1/projects/{job.project_id}/reports/{original_id}/original" if job and original_id else None
    locators = []
    for item in value.get("evidence", []):
        from uuid import UUID
        try:
            fragment = db.get(Fragment, UUID(str(item.get("fragment_id"))))
        except (ValueError, TypeError):
            fragment = None
        locators.append({**item, "locator": fragment.locator if fragment else None})
    value["evidence"] = locators
    return value


def call_metadata(kwargs: dict, response) -> dict:
    """Record non-secret model identity and prompt/config hashes, never credentials."""
    import hashlib
    import json
    def hash_value(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
    return {"model": getattr(response, "model", None),
            "model_digest": getattr(response, "model_digest", None),
            "runtime": getattr(response, "runtime", None),
            "system_prompt_hash": hash_value(kwargs.get("system")),
            "schema_hash": hash_value(kwargs.get("schema")),
            "settings_hash": getattr(response, "settings_hash", None) or hash_value(kwargs.get("settings")),
            "adapter_prompt_hash": getattr(response, "prompt_hash", None)}
