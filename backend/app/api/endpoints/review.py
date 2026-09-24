"""Evidence-first proposal review and atomic approval."""
from __future__ import annotations

from datetime import date
import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from ...db.models import (
    Activity, ActivityState, AuditEvent, Fragment, IdempotencyKey, Observation,
    Job, ProgressEvent, ProjectMembership, Proposal, ScheduleVersion, User,
)
from ...db.session import get_session
from ...progress.ledger import ActivityBaseline, ProgressEvent as LedgerEvent, recompute_progress
from ..dependencies import require_reviewer

router = APIRouter(prefix="/proposals", tags=["review"])


class ReviewChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_proposal_revision: int = Field(ge=1)
    chosen_activity_id: UUID | None = None
    field_changes: dict[str, object] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=2000)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_proposal_revision: int = Field(ge=1)
    expected_activity_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=200)
    resolution_notes: str | None = Field(default=None, max_length=2000)


def _proposal(db: DBSession, proposal_id: UUID, user: User) -> Proposal:
    proposal = db.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "Proposal not found")
    membership = db.scalar(select(ProjectMembership).where(
        ProjectMembership.project_id == proposal.project_id,
        ProjectMembership.user_id == user.id,
    ))
    if membership is None:
        raise HTTPException(403, "Project access denied")
    if proposal.chosen_activity_id is not None:
        _validate_pinned_activity(db, proposal, proposal.chosen_activity_id)
    return proposal


def _validate_pinned_activity(db: DBSession, proposal: Proposal, activity_id: UUID) -> Activity:
    activity = db.get(Activity, activity_id)
    observation = db.get(Observation, proposal.observation_id)
    job = db.get(Job, observation.job_id) if observation else None
    schedule = db.get(ScheduleVersion, activity.schedule_version_id) if activity else None
    if activity is None or schedule is None or schedule.project_id != proposal.project_id:
        raise HTTPException(422, detail={"code": "CROSS_PROJECT_ACTIVITY"})
    if job is None or job.project_id != proposal.project_id or job.schedule_version_id != schedule.id:
        raise HTTPException(422, detail={"code": "ACTIVITY_OUTSIDE_PINNED_SCHEDULE"})
    return activity


def _tags(value: object) -> list[str]:
    if isinstance(value, str):
        return [tag.strip() for tag in value.replace("|", ";").split(";") if tag.strip()]
    return [str(tag) for tag in value] if isinstance(value, list) else []


def _candidate_payload(candidate: object, rank: int) -> dict[str, object]:
    value = candidate if isinstance(candidate, dict) else {}
    return {
        "id": str(value.get("candidate_id", value.get("id", ""))),
        "name": value.get("activity_name", value.get("name", "Unnamed activity")),
        "area": value.get("area") or "Unspecified area",
        "work_type": value.get("work_type", "unknown"),
        "tags": _tags(value.get("asset_tags", value.get("tags", []))),
        "rank": value.get("retrieval_rank", value.get("rank", rank)),
    }


def _proposal_payload(db: DBSession, proposal: Proposal) -> dict[str, object]:
    observation = db.get(Observation, proposal.observation_id)
    fields = dict(observation.fields or {}) if observation else {}
    evidence_records = fields.get("evidence", [])
    evidence: list[dict[str, str]] = []
    if isinstance(evidence_records, list):
        for item in evidence_records:
            if not isinstance(item, dict) or not item.get("fragment_id") or not item.get("quote"):
                continue
            fragment = db.get(Fragment, UUID(str(item["fragment_id"])))
            evidence.append({
                "quote": str(item["quote"]),
                "locator": fragment.locator if fragment else "Stored source fragment",
                "fragment_id": str(item["fragment_id"]),
            })
    if not evidence and observation and observation.fragment_id:
        fragment = db.get(Fragment, observation.fragment_id)
        if fragment:
            evidence.append({"quote": fragment.original_text, "locator": fragment.locator, "fragment_id": str(fragment.id)})
    state = db.get(ActivityState, proposal.chosen_activity_id) if proposal.chosen_activity_id else None
    return {
        "id": str(proposal.id),
        "observation_id": str(proposal.observation_id),
        "revision": proposal.revision,
        "current_activity_revision": state.revision if state else 0,
        "candidates": [_candidate_payload(candidate, index) for index, candidate in enumerate(proposal.candidates or [], 1)],
        "chosen_activity_id": str(proposal.chosen_activity_id) if proposal.chosen_activity_id else None,
        "mapping_state": proposal.mapping_state,
        "match_strength": proposal.match_strength,
        "review_state": proposal.review_state,
        "warnings": proposal.warnings or [],
        "proposed_effects": proposal.proposed_effects or {},
        "missing_information": fields.get("missing_information", []),
        "observation": {
            "summary": fields.get("summary", "No observation summary was stored."),
            "quantity": str(fields["quantity"]) if fields.get("quantity") is not None else None,
            "unit": fields.get("unit"),
            "work_type": fields.get("work_type", "unknown"),
            "area": fields.get("area") or "Unspecified area",
            "tags": _tags(fields.get("asset_tags", [])),
            "event_type": fields.get("event_type", "unknown"),
        },
        "evidence": evidence,
    }


@router.get("/{proposal_id}")
def get_proposal(proposal_id: UUID, user: User = Depends(require_reviewer), db: DBSession = Depends(get_session)):
    return _proposal_payload(db, _proposal(db, proposal_id, user))


def _revise(db: DBSession, proposal: Proposal, body: ReviewChange, user: User) -> Proposal:
    if body.expected_proposal_revision != proposal.revision or proposal.review_state != "pending":
        raise HTTPException(409, detail={"code": "STALE_PROPOSAL", "current_revision": proposal.revision})
    if body.chosen_activity_id is not None:
        _validate_pinned_activity(db, proposal, body.chosen_activity_id)
    if set(body.field_changes) - {"proposed_effects", "resolve_warnings"}:
        raise HTTPException(422, detail={"code": "INVALID_REVIEW_CHANGE"})
    effects_change = body.field_changes.get("proposed_effects", {})
    if not isinstance(effects_change, dict):
        raise HTTPException(422, detail={"code": "INVALID_REVIEW_CHANGE"})
    existing_warnings = list(proposal.warnings or [])
    resolutions = body.field_changes.get("resolve_warnings", [])
    if not isinstance(resolutions, list) or any(not isinstance(item, str) for item in resolutions):
        raise HTTPException(422, detail={"code": "INVALID_WARNING_RESOLUTION"})
    if len(set(resolutions)) != len(resolutions) or not set(resolutions).issubset(existing_warnings):
        raise HTTPException(422, detail={"code": "INVALID_WARNING_RESOLUTION"})
    remaining_warnings = [warning for warning in existing_warnings if warning not in set(resolutions)]
    proposal.review_state = "superseded"
    effects = dict(proposal.proposed_effects or {})
    effects.update(effects_change)
    revision = Proposal(
        observation_id=proposal.observation_id, revision=proposal.revision + 1, project_id=proposal.project_id,
        chosen_activity_id=body.chosen_activity_id, candidates=proposal.candidates,
        mapping_state="suggested" if body.chosen_activity_id else "unmatched",
        match_strength="review" if body.chosen_activity_id else "unresolved", review_state="pending",
        warnings=remaining_warnings, proposed_effects=effects, base_activity_revision=proposal.base_activity_revision,
    )
    db.add(revision)
    db.flush()
    db.add(AuditEvent(
        actor_id=user.id, action="revise", target_type="proposal", target_id=proposal.id,
        before={"revision": proposal.revision},
        after={"proposal_id": str(revision.id), "revision": revision.revision}, reason=body.reason,
    ))
    return revision


@router.post("/{proposal_id}/revise")
def revise(proposal_id: UUID, body: ReviewChange, user: User = Depends(require_reviewer), db: DBSession = Depends(get_session)):
    return _proposal_payload(db, _revise(db, _proposal(db, proposal_id, user), body, user))


@router.post("/{proposal_id}/reject")
def reject(proposal_id: UUID, body: ReviewChange, user: User = Depends(require_reviewer), db: DBSession = Depends(get_session)):
    proposal = _proposal(db, proposal_id, user)
    if body.expected_proposal_revision != proposal.revision or proposal.review_state != "pending":
        raise HTTPException(409, detail={"code": "STALE_PROPOSAL", "current_revision": proposal.revision})
    proposal.review_state = "rejected"
    db.add(AuditEvent(
        actor_id=user.id, action="reject", target_type="proposal", target_id=proposal.id,
        after={"state": "rejected"}, reason=body.reason,
    ))
    return {"id": str(proposal.id), "revision": proposal.revision, "review_state": proposal.review_state}


def _effects(proposal: Proposal) -> tuple[dict[str, object], date | None]:
    effects = dict(proposal.proposed_effects or {})
    allowed = {"quantity", "unit", "quantity_semantics", "event_type", "effective_date", "source_id", "correction_of", "supersedes_event_id"}
    if set(effects) - allowed or "quantity" not in effects or "quantity_semantics" not in effects:
        raise HTTPException(422, detail={"code": "INVALID_EFFECT"})
    try:
        effective_date = date.fromisoformat(str(effects["effective_date"])) if effects.get("effective_date") else None
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_EFFECT"}) from exc
    return effects, effective_date


@router.post("/{proposal_id}/approve")
def approve(proposal_id: UUID, body: ApprovalRequest, user: User = Depends(require_reviewer), db: DBSession = Depends(get_session)):
    proposal = _proposal(db, proposal_id, user)
    request_hash = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    old = db.scalar(select(IdempotencyKey).where(
        IdempotencyKey.actor_id == user.id, IdempotencyKey.endpoint == "approve", IdempotencyKey.key == body.idempotency_key,
    ))
    if old:
        if old.request_hash != request_hash:
            raise HTTPException(409, "Idempotency key reused with different request")
        return old.result_reference

    # Serialize approvals for the proposal itself.  Without this lock two
    # transactions can both observe ``pending`` before either commits.  The
    # second transaction must re-read idempotency after waiting so a retry
    # returns the first committed response rather than creating a duplicate.
    proposal = db.scalar(select(Proposal).where(Proposal.id == proposal_id).with_for_update())
    if proposal is None:
        raise HTTPException(404, "Proposal not found")
    old = db.scalar(select(IdempotencyKey).where(
        IdempotencyKey.actor_id == user.id, IdempotencyKey.endpoint == "approve", IdempotencyKey.key == body.idempotency_key,
    ))
    if old:
        if old.request_hash != request_hash:
            raise HTTPException(409, "Idempotency key reused with different request")
        return old.result_reference
    if body.expected_proposal_revision != proposal.revision or proposal.review_state != "pending":
        raise HTTPException(409, detail={"code": "STALE_PROPOSAL", "current_revision": proposal.revision})
    if proposal.mapping_state != "suggested" or proposal.chosen_activity_id is None:
        raise HTTPException(422, detail={"code": "ACTIVITY_REQUIRED"})
    if proposal.warnings:
        raise HTTPException(422, detail={"code": "UNRESOLVED_WARNINGS", "warnings": proposal.warnings})
    activity = _validate_pinned_activity(db, proposal, proposal.chosen_activity_id)
    state = db.scalar(select(ActivityState).where(ActivityState.activity_id == activity.id).with_for_update())
    if state is None:
        state = ActivityState(activity_id=activity.id, revision=0)
        db.add(state)
        db.flush()
    if state.revision != body.expected_activity_revision:
        raise HTTPException(409, detail={"code": "STALE_ACTIVITY", "current_revision": state.revision})
    effects, effective_date = _effects(proposal)
    supersedes = UUID(str(effects["supersedes_event_id"])) if effects.get("supersedes_event_id") else None
    prior = db.scalars(select(ProgressEvent).where(ProgressEvent.activity_id == activity.id).with_for_update()).all()
    ledger = [
        LedgerEvent(
            str(event.id), event.effective_date, (event.approved_values or {}).get("quantity"),
            (event.approved_values or {}).get("unit"), (event.approved_values or {}).get("quantity_semantics", "unknown"),
            (event.approved_values or {}).get("event_type", event.effect_kind), str(event.observation_id), True,
            str(event.supersedes_event_id) if event.supersedes_event_id else None,
            (event.approved_values or {}).get("correction_of"),
        ) for event in prior
    ]
    candidate = LedgerEvent(
        "candidate", effective_date, effects.get("quantity"), effects.get("unit"),
        str(effects.get("quantity_semantics", "unknown")), str(effects.get("event_type", "actual_progress")),
        str(proposal.observation_id), True, str(supersedes) if supersedes else None,
        str(effects["correction_of"]) if effects.get("correction_of") else None,
    )
    result = recompute_progress(
        ActivityBaseline(activity.planned_quantity, activity.unit, activity.baseline_quantity, activity.baseline_date, activity.measurement_basis),
        ledger + [candidate],
    )
    if not result.valid:
        raise HTTPException(422, detail={"code": "CONFLICTING_EFFECT", "conflicts": result.conflicts})
    event = ProgressEvent(
        activity_id=activity.id, observation_id=proposal.observation_id, proposal_id=proposal.id,
        proposal_revision=proposal.revision, approved_values=effects,
        effect_kind=str(effects.get("event_type", "actual_progress")), effective_date=effective_date,
        reviewer_id=user.id, supersedes_event_id=supersedes,
        source_key=f"proposal:{proposal.id}:{proposal.revision}",
    )
    db.add(event)
    proposal.review_state = "approved"
    state.revision += 1
    state.completed_quantity = result.completed_quantity
    state.physical_percent = result.physical_percent
    db.flush()
    response = {
        "proposal_id": str(proposal.id), "event_id": str(event.id),
        "activity_id": str(activity.id), "state_revision": state.revision,
    }
    db.add(AuditEvent(
        actor_id=user.id, action="approve", target_type="proposal", target_id=proposal.id,
        after=response, reason=body.resolution_notes, request_id=body.idempotency_key,
    ))
    db.add(IdempotencyKey(
        actor_id=user.id, endpoint="approve", key=body.idempotency_key,
        request_hash=request_hash, result_reference=response,
    ))
    return response
