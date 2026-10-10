"""Server-side lifecycle validation and state projection for review transactions."""
from __future__ import annotations
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.db.models import Activity, ActivityState, Fragment, Job, Observation, ProgressEvent, Proposal
from app.progress.lifecycle import LifecycleEvent, recompute_lifecycle
from app.schemas.events import Endpoint, LifecycleEffect, LifecycleKind, LifecycleScope


def _invalid(code: str) -> HTTPException:
    return HTTPException(422, detail={"code": code})


def lifecycle_effect(db: Session, proposal: Proposal, activity: Activity, effects: dict) -> LifecycleEffect:
    allowed = {"event_type", "scope", "endpoint", "evidence", "effective_date", "source_version_id", "observation_id", "proposal_id", "subactivity_key", "scheduled_parent_id", "supersedes_event_id", "correction_of"}
    if set(effects) - allowed:
        raise _invalid("INVALID_EFFECT")
    observation = db.get(Observation, proposal.observation_id)
    job = db.get(Job, observation.job_id) if observation else None
    if not job or not activity.is_leaf or job.schedule_version_id != activity.schedule_version_id:
        raise _invalid("INVALID_LIFECYCLE_TARGET")
    if effects.get("source_version_id") and str(effects["source_version_id"]) != str(job.schedule_version_id):
        raise _invalid("INVALID_SOURCE_VERSION")
    if effects.get("observation_id") and str(effects["observation_id"]) != str(observation.id):
        raise _invalid("INVALID_OBSERVATION")
    if effects.get("proposal_id") and str(effects["proposal_id"]) != str(proposal.id):
        raise _invalid("INVALID_PROPOSAL")
    try:
        parsed = LifecycleEffect.model_validate({
            "kind": effects["event_type"], "scope": effects["scope"], "endpoint": effects["endpoint"],
            "evidence": effects["evidence"], "source_version_id": job.schedule_version_id,
            "observation_id": observation.id, "proposal_id": proposal.id,
            "subactivity_key": effects.get("subactivity_key"),
            "scheduled_parent_id": effects.get("scheduled_parent_id"),
        })
    except (KeyError, ValueError) as exc:
        raise _invalid("INVALID_LIFECYCLE_EFFECT") from exc
    if effects.get("effective_date") != parsed.endpoint.local_date.isoformat():
        raise _invalid("INVALID_EFFECTIVE_DATE")
    if parsed.scope == LifecycleScope.subactivity:
        if effects.get("scheduled_parent_id") and str(effects["scheduled_parent_id"]) != str(activity.id):
            raise _invalid("INVALID_SUBACTIVITY_PARENT")
        effects["scheduled_parent_id"] = str(activity.id)
        if not any(("scope" in e.fields or "subactivity_key" in e.fields) and
                   parsed.subactivity_key.casefold() in e.quote.casefold() for e in parsed.evidence):
            raise _invalid("SUBACTIVITY_EVIDENCE_REQUIRED")
    elif effects.get("subactivity_key") or effects.get("scheduled_parent_id"):
        raise _invalid("INVALID_SUBACTIVITY_SCOPE")
    for evidence in parsed.evidence:
        try:
            fragment_id = UUID(evidence.fragment_id)
        except ValueError as exc:
            raise _invalid("INVALID_EVIDENCE") from exc
        fragment = db.get(Fragment, fragment_id)
        if not fragment or fragment.report_id != job.report_id or evidence.quote not in fragment.original_text:
            raise _invalid("INVALID_EVIDENCE")
    return parsed


def endpoint_from_event(event: ProgressEvent) -> Endpoint:
    values = event.approved_values or {}
    return Endpoint.model_validate(values["endpoint"])


def project_lifecycle(db: Session, activity: Activity, prior: list[ProgressEvent], candidate: LifecycleEvent | None):
    by_id = {event.id: event for event in prior}
    retracted = {UUID(str(event.supersedes_event_id)) for event in prior
                 if event.effect_kind == "lifecycle_retraction" and event.supersedes_event_id}
    for event_id in list(retracted):
        current = by_id.get(event_id)
        while current and current.supersedes_event_id:
            retracted.add(current.supersedes_event_id)
            current = by_id.get(current.supersedes_event_id)
    events = []
    for event in prior:
        if event.id in retracted or event.effect_kind not in {"actual_start", "actual_finish"}:
            continue
        values = event.approved_values or {}
        events.append(LifecycleEvent(
            str(event.id), LifecycleKind(event.effect_kind), endpoint_from_event(event),
            LifecycleScope(values.get("scope", "whole_activity")), event.source_key, True,
            str(event.supersedes_event_id) if event.supersedes_event_id else None,
            values.get("subactivity_key"),
        ))
    def baseline(value):
        return Endpoint(local_date=value, precision="date", basis="imported_baseline", raw_expression=value.isoformat()) if value else None
    result = recompute_lifecycle(baseline(activity.actual_start), baseline(activity.actual_finish), events + ([candidate] if candidate else []))
    if not result.valid:
        raise HTTPException(422, detail={"code": "CONFLICTING_EFFECT", "conflicts": result.conflicts})
    return result


def apply_lifecycle_state(state: ActivityState, result, source_version_id: UUID, event_id: UUID, kind: str) -> None:
    state.actual_start = result.actual_start.local_date if result.actual_start else None
    state.actual_finish = result.actual_finish.local_date if result.actual_finish else None
    state.actual_start_time = result.actual_start.local_time if result.actual_start else None
    state.actual_finish_time = result.actual_finish.local_time if result.actual_finish else None
    state.actual_start_precision = result.actual_start.precision.value if result.actual_start else None
    state.actual_finish_precision = result.actual_finish.precision.value if result.actual_finish else None
    state.lifecycle_status = result.status
    state.lifecycle_source_version_id = source_version_id
    if "candidate" not in result.applied_event_ids and str(event_id) not in result.applied_event_ids:
        return
    if kind == "actual_start":
        state.lifecycle_start_event_id = event_id
    else:
        state.lifecycle_finish_event_id = event_id
