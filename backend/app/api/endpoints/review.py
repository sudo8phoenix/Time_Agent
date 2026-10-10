"""Evidence-first proposal review and atomic approval."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from ...db.models import (
    Activity, ActivityState, AuditEvent, Fragment, IdempotencyKey, Observation,
    Job, ProgressEvent, Project, ProjectMembership, Proposal, Report, ScheduleVersion, User,
)
from ...db.session import get_session
from ...progress.ledger import ActivityBaseline, ProgressEvent as LedgerEvent, recompute_progress
from ...integrations.outbox import enqueue
from ...confidence.provenance import capture
from ...progress.acceptance import lifecycle_effect, project_lifecycle, apply_lifecycle_state
from ...progress.lifecycle import LifecycleEvent
from ..dependencies import current_reviewer, require_reviewer

router = APIRouter(prefix="/proposals", tags=["review"])


class ReviewChange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
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


def _proposal(db: DBSession, proposal_id: UUID, user: User, *, lock: bool = False, allow_stale: bool = False) -> Proposal:
    statement = select(Proposal).where(Proposal.id == proposal_id)
    proposal = db.scalar(statement.with_for_update() if lock else statement)
    if proposal is None:
        raise HTTPException(404, "Proposal not found")
    membership = db.scalar(select(ProjectMembership).where(
        ProjectMembership.project_id == proposal.project_id,
        ProjectMembership.user_id == user.id,
    ))
    if membership is None:
        raise HTTPException(403, "Project access denied")
    if proposal.chosen_activity_id is not None:
        _validate_pinned_activity(db, proposal, proposal.chosen_activity_id, require_active=not allow_stale)
    return proposal


def _validate_pinned_activity(db: DBSession, proposal: Proposal, activity_id: UUID, *, require_active: bool = True) -> Activity:
    activity = db.get(Activity, activity_id)
    observation = db.get(Observation, proposal.observation_id)
    job = db.get(Job, observation.job_id) if observation else None
    schedule = db.get(ScheduleVersion, activity.schedule_version_id) if activity else None
    if activity is None or schedule is None or schedule.project_id != proposal.project_id:
        raise HTTPException(422, detail={"code": "CROSS_PROJECT_ACTIVITY"})
    if job is None or job.project_id != proposal.project_id or job.schedule_version_id != schedule.id:
        raise HTTPException(422, detail={"code": "ACTIVITY_OUTSIDE_PINNED_SCHEDULE"})
    project = db.get(Project, proposal.project_id)
    if require_active and (project is None or project.active_schedule_version_id != schedule.id or schedule.state != "active"):
        raise HTTPException(409, detail={"code": "STALE_SCHEDULE"})
    if not activity.is_leaf:
        raise HTTPException(422, detail={"code": "SUMMARY_ACTIVITY_INELIGIBLE"})
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
    selection = (observation.field_evidence or {}).get("selection", {}) if observation else {}
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
    chosen_activity = db.get(Activity, proposal.chosen_activity_id) if proposal.chosen_activity_id else None
    candidates = list(proposal.candidates or [])
    if chosen_activity and not any(str(c.get("candidate_id", c.get("id"))) == str(chosen_activity.id) for c in candidates):
        from ...agent.schedule_decision import candidate_for_activity
        candidates.append(candidate_for_activity(chosen_activity).model_dump(mode="json"))
    from ...confidence.provenance import context
    from ...confidence.history import decision_history
    return {
        "provenance": context(db, observation),
        "decision_history": decision_history(db, observation),
        "id": str(proposal.id),
        "observation_id": str(proposal.observation_id),
        "revision": proposal.revision,
        "current_activity_revision": state.revision if state else 0,
        "current_lifecycle_state": {
            "actual_start": state.actual_start.isoformat() if state and state.actual_start else chosen_activity.actual_start.isoformat() if chosen_activity and chosen_activity.actual_start else None,
            "actual_start_time": state.actual_start_time.isoformat() if state and state.actual_start_time else None,
            "actual_start_precision": state.actual_start_precision if state else "date" if chosen_activity and chosen_activity.actual_start else None,
            "actual_finish": state.actual_finish.isoformat() if state and state.actual_finish else chosen_activity.actual_finish.isoformat() if chosen_activity and chosen_activity.actual_finish else None,
            "actual_finish_time": state.actual_finish_time.isoformat() if state and state.actual_finish_time else None,
            "actual_finish_precision": state.actual_finish_precision if state else "date" if chosen_activity and chosen_activity.actual_finish else None,
            "status": state.lifecycle_status if state else None,
        },
        "candidates": [_candidate_payload(candidate, index) for index, candidate in enumerate(candidates, 1)],
        "chosen_activity_id": str(proposal.chosen_activity_id) if proposal.chosen_activity_id else None,
        "chosen_activity_measurement_basis": chosen_activity.measurement_basis if chosen_activity else None,
        "mapping_state": proposal.mapping_state,
        "match_strength": proposal.match_strength,
        "review_state": proposal.review_state,
        "warnings": proposal.warnings or [],
        "proposed_effects": proposal.proposed_effects or {},
        "missing_information": selection.get("missing_information") or fields.get("missing_information", []),
        "selection_explanation": selection.get("explanation"),
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
def get_proposal(proposal_id: UUID, user: User = Depends(current_reviewer), db: DBSession = Depends(get_session)):
    return _proposal_payload(db, _proposal(db, proposal_id, user, allow_stale=True))


@router.get("/{proposal_id}/activities")
def search_activities(proposal_id: UUID, q: str = Query(default="", max_length=200),
                      offset: int = Query(default=0, ge=0),
                      user: User = Depends(current_reviewer), db: DBSession = Depends(get_session)):
    proposal = _proposal(db, proposal_id, user)
    observation = db.get(Observation, proposal.observation_id)
    job = db.get(Job, observation.job_id)
    from ...agent.project_aliases import with_project_aliases
    rows = with_project_aliases(db, proposal.project_id, db.scalars(select(Activity).where(
        Activity.schedule_version_id == job.schedule_version_id, Activity.is_leaf.is_(True)
    ).order_by(Activity.external_id)).all())
    terms = q.casefold().split()
    rows = [row for row in rows if all(term in " ".join(str(getattr(row, key) or "") for key in
            ("external_id", "name", "area", "asset_tags", "discipline", "wbs", "aliases")).casefold()
            for term in terms)]
    from ...agent.schedule_decision import candidate_for_activity
    return {"total": len(rows), "offset": offset, "items": [
        {**_candidate_payload(candidate_for_activity(row).model_dump(mode="json"), 0),
         "external_id": row.external_id, "wbs": row.wbs, "discipline": row.discipline}
        for row in rows[offset:offset + 50]]}


class ResolutionRequest(ReviewChange):
    outcome: str = Field(pattern="^(request_clarification|missing_schedule_scope)$")


@router.post("/{proposal_id}/resolve")
def resolve_unmatched(proposal_id: UUID, body: ResolutionRequest,
                      user: User = Depends(require_reviewer), db: DBSession = Depends(get_session)):
    proposal = _proposal(db, proposal_id, user, lock=True)
    if body.expected_proposal_revision != proposal.revision or proposal.review_state != "pending":
        raise HTTPException(409, detail={"code": "STALE_PROPOSAL"})
    proposal.review_state = body.outcome
    db.add(AuditEvent(timestamp=datetime.now(timezone.utc), actor_id=user.id, action=body.outcome, target_type="proposal",
                     target_id=proposal.id, before={"state": "pending"},
                     after={"state": body.outcome}, reason=body.reason))
    return _proposal_payload(db, proposal)


class AliasApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=0)
    aliases: list[str] = Field(max_length=30)
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/{proposal_id}/aliases")
def get_aliases(proposal_id: UUID, user: User = Depends(current_reviewer), db: DBSession = Depends(get_session)):
    from ...agent.project_aliases import alias_snapshot
    proposal = _proposal(db, proposal_id, user)
    return alias_snapshot(db, proposal.project_id)


@router.post("/{proposal_id}/activities/{activity_id}/aliases")
def approve_aliases(proposal_id: UUID, activity_id: UUID, body: AliasApproval,
                    user: User = Depends(require_reviewer), db: DBSession = Depends(get_session)):
    proposal = _proposal(db, proposal_id, user)
    _validate_pinned_activity(db, proposal, activity_id)
    db.scalar(select(Project).where(Project.id == proposal.project_id).with_for_update())
    from ...agent.project_aliases import alias_snapshot
    before = alias_snapshot(db, proposal.project_id)
    if body.expected_revision != before["revision"]:
        raise HTTPException(409, detail={"code": "STALE_ALIAS_REVISION"})
    if any(not alias.strip() or len(alias) > 200 for alias in body.aliases):
        raise HTTPException(422, detail={"code": "INVALID_ALIAS"})
    after = {"revision": before["revision"] + 1, "aliases": {
        **before["aliases"], str(activity_id): list(dict.fromkeys(a.strip() for a in body.aliases))}}
    db.add(AuditEvent(timestamp=datetime.now(timezone.utc), actor_id=user.id, action="approve_aliases", target_type="project_aliases",
                     target_id=proposal.project_id, before=before, after=after, reason=body.reason))
    return after


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
    if "endpoint" in effects_change and not isinstance(effects_change["endpoint"], dict):
        raise HTTPException(422, detail={"code": "INVALID_ENDPOINT"})
    if "quantity" in effects_change:
        try:
            quantity = Decimal(str(effects_change["quantity"]))
            if not quantity.is_finite() or quantity < 0:
                raise ValueError()
        except (InvalidOperation, ValueError):
            raise HTTPException(422, detail={"code": "INVALID_QUANTITY", "message": "Quantity must be a finite, non-negative number."}) from None
    if "reported_percent" in effects_change:
        try:
            percent = Decimal(str(effects_change["reported_percent"]))
            if not percent.is_finite() or not 0 <= percent <= 100:
                raise ValueError()
        except (InvalidOperation, ValueError):
            raise HTTPException(422, detail={"code": "INVALID_PERCENT", "message": "Percent must be between 0 and 100."}) from None
    if "effective_date" in effects_change:
        try:
            date.fromisoformat(str(effects_change["effective_date"]))
        except ValueError:
            raise HTTPException(422, detail={"code": "INVALID_DATE", "message": "Work date must be a valid calendar date."}) from None
    existing_warnings = list(proposal.warnings or [])
    resolutions = body.field_changes.get("resolve_warnings", [])
    if not isinstance(resolutions, list) or any(not isinstance(item, str) for item in resolutions):
        raise HTTPException(422, detail={"code": "INVALID_WARNING_RESOLUTION"})
    if len(set(resolutions)) != len(resolutions) or not set(resolutions).issubset(existing_warnings):
        raise HTTPException(422, detail={"code": "INVALID_WARNING_RESOLUTION"})
    remaining_warnings = [warning for warning in existing_warnings if warning not in set(resolutions)]
    proposal.review_state = "superseded"
    effects = dict(proposal.proposed_effects or {})
    if "endpoint" in effects_change:
        effects_change = {**effects_change, "endpoint": {**effects.get("endpoint", {}), **effects_change["endpoint"]}}
    effects.update(effects_change)
    if effects.get("scope") == "subactivity" and body.chosen_activity_id:
        effects["scheduled_parent_id"] = str(body.chosen_activity_id)
    if body.chosen_activity_id and body.chosen_activity_id != proposal.chosen_activity_id:
        observation = db.get(Observation, proposal.observation_id)
        if not (observation.fields or {}).get("evidence") and not observation.fragment_id:
            raise HTTPException(422, detail={"code": "EVIDENCE_REQUIRED"})
    if effects.get("event_type") in {"actual_start", "actual_finish"} and "endpoint" in effects_change:
        effects["effective_date"] = effects["endpoint"].get("local_date")
    revision = Proposal(
        observation_id=proposal.observation_id, revision=proposal.revision + 1, project_id=proposal.project_id,
        chosen_activity_id=body.chosen_activity_id, candidates=proposal.candidates,
        mapping_state="suggested" if body.chosen_activity_id else "unmatched",
        match_strength="review" if body.chosen_activity_id else "unresolved", review_state="pending",
        warnings=remaining_warnings, proposed_effects=effects, base_activity_revision=proposal.base_activity_revision,
    )
    db.add(revision)
    db.flush()
    db.add(AuditEvent(timestamp=datetime.now(timezone.utc),
        actor_id=user.id, action="revise", target_type="proposal", target_id=proposal.id,
        before={"proposal_id": str(proposal.id), "revision": proposal.revision,
                "chosen_activity_id": str(proposal.chosen_activity_id) if proposal.chosen_activity_id else None,
                "effects": proposal.proposed_effects, "warnings": existing_warnings},
        after={"proposal_id": str(revision.id), "revision": revision.revision,
               "chosen_activity_id": str(revision.chosen_activity_id) if revision.chosen_activity_id else None,
               "effects": effects, "warnings": remaining_warnings}, reason=body.reason,
    ))
    return revision


@router.post("/{proposal_id}/revise")
def revise(proposal_id: UUID, body: ReviewChange, user: User = Depends(require_reviewer), db: DBSession = Depends(get_session)):
    return _proposal_payload(db, _revise(db, _proposal(db, proposal_id, user, lock=True), body, user))


@router.post("/{proposal_id}/reject")
def reject(proposal_id: UUID, body: ReviewChange, user: User = Depends(require_reviewer), db: DBSession = Depends(get_session)):
    proposal = _proposal(db, proposal_id, user, lock=True)
    if body.expected_proposal_revision != proposal.revision or proposal.review_state != "pending":
        raise HTTPException(409, detail={"code": "STALE_PROPOSAL", "current_revision": proposal.revision})
    before = {"state": proposal.review_state, "effects": proposal.proposed_effects,
              "warnings": proposal.warnings, "chosen_activity_id": str(proposal.chosen_activity_id) if proposal.chosen_activity_id else None}
    proposal.review_state = "rejected"
    db.add(AuditEvent(timestamp=datetime.now(timezone.utc),
        actor_id=user.id, action="reject", target_type="proposal", target_id=proposal.id,
        before=before, after={**before, "state": "rejected"}, reason=body.reason,
    ))
    return {"id": str(proposal.id), "revision": proposal.revision, "review_state": proposal.review_state}


def _lifecycle_snapshot(state: ActivityState) -> dict:
    return {key: value.isoformat() if hasattr(value, "isoformat") else value
            for key in ("actual_start", "actual_start_time", "actual_start_precision",
                        "actual_finish", "actual_finish_time", "actual_finish_precision",
                        "lifecycle_status") for value in [getattr(state, key)]}


def _effects(proposal: Proposal) -> tuple[dict[str, object], date | None]:
    effects = dict(proposal.proposed_effects or {})
    allowed = {"quantity", "unit", "quantity_semantics", "reported_percent", "event_type", "effective_date", "source_id", "correction_of", "supersedes_event_id"}
    if effects.get("event_type") in {"actual_start", "actual_finish"}:
        return effects, None
    if effects.get("event_type") == "blocker":
        allowed |= {"blocker", "blocker_category", "evidence"}
    if set(effects) - allowed or (effects.get("event_type") != "blocker" and "quantity" not in effects and "reported_percent" not in effects):
        raise HTTPException(422, detail={"code": "INVALID_EFFECT"})
    if "reported_percent" in effects:
        try:
            percent = Decimal(str(effects["reported_percent"]))
            if not percent.is_finite() or not 0 <= percent <= 100:
                raise ValueError()
        except (InvalidOperation, ValueError):
            raise HTTPException(422, detail={"code": "INVALID_EFFECT"}) from None
    if "quantity" in effects and "quantity_semantics" not in effects:
        raise HTTPException(422, detail={"code": "INVALID_EFFECT"})
    try:
        effective_date = date.fromisoformat(str(effects["effective_date"])) if effects.get("effective_date") else None
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_EFFECT"}) from exc
    return effects, effective_date


@router.post("/{proposal_id}/approve")
def approve(proposal_id: UUID, body: ApprovalRequest, user: User = Depends(require_reviewer), db: DBSession = Depends(get_session)):
    proposal = _proposal(db, proposal_id, user, lock=True)
    request_hash = hashlib.sha256((str(proposal_id) + ":" + body.model_dump_json()).encode()).hexdigest()
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
    observation = db.get(Observation, proposal.observation_id)
    job = db.get(Job, observation.job_id) if observation else None
    if job:
        db.scalar(select(Report).where(Report.id == job.report_id).with_for_update())
    activity = _validate_pinned_activity(db, proposal, proposal.chosen_activity_id)
    db.scalar(select(Activity).where(Activity.id == activity.id).with_for_update())
    state = db.scalar(select(ActivityState).where(ActivityState.activity_id == activity.id).with_for_update())
    if state is None:
        state = ActivityState(activity_id=activity.id, revision=0)
        db.add(state)
        db.flush()
    if state.revision != body.expected_activity_revision:
        raise HTTPException(409, detail={"code": "STALE_ACTIVITY", "current_revision": state.revision})
    effects, effective_date = _effects(proposal)
    if job:
        effect_kind = effects.get("event_type") or "actual_progress"
        if effect_kind in {"actual_start", "actual_finish"}:
            prior_kind = effect_kind
        elif effect_kind == "blocker":
            prior_kind = "blocker"
        else:
            prior_kind = "actual_progress"
        prior_query = (select(ProgressEvent.id)
            .join(Observation, ProgressEvent.observation_id == Observation.id)
            .join(Job, Observation.job_id == Job.id)
            .where(Job.report_id == job.report_id, Job.id != job.id,
                   ProgressEvent.effect_kind == prior_kind))
        if observation and observation.fragment_id:
            prior_query = prior_query.where(Observation.fragment_id == observation.fragment_id)
        else:
            prior_query = prior_query.where(Observation.fragment_id.is_(None))
        prior_application = db.scalar(
            prior_query.limit(1)
        )
        if prior_application:
            raise HTTPException(409, detail={"code": "SOURCE_WORK_ALREADY_ACCEPTED",
                                             "message": "This source work was already applied to this activity; review its existing decision."})
    is_blocker = effects.get("event_type") == "blocker"
    is_lifecycle = effects.get("event_type") in {"actual_start", "actual_finish"}
    parsed = lifecycle_effect(db, proposal, activity, effects) if is_lifecycle else None
    if not is_lifecycle and not is_blocker and activity.measurement_basis in {"manual_physical", "milestone"}:
        if "reported_percent" not in effects:
            raise HTTPException(422, detail={"code": "PERCENT_REQUIRED"})
    elif not is_lifecycle and not is_blocker and activity.measurement_basis == "quantity_ratio":
        if "quantity" not in effects:
            raise HTTPException(422, detail={"code": "QUANTITY_REQUIRED"})
    try:
        supersedes = UUID(str(effects["supersedes_event_id"])) if effects.get("supersedes_event_id") else None
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_CORRECTION_REFERENCE"}) from exc
    prior = db.scalars(select(ProgressEvent).where(ProgressEvent.activity_id == activity.id).with_for_update()).all()
    if is_lifecycle and effects.get("correction_of") and str(effects["correction_of"]) != str(supersedes):
        raise HTTPException(422, detail={"code": "INVALID_CORRECTION_REFERENCE"})
    if supersedes:
        replaced = next((event for event in prior if event.id == supersedes), None)
        if replaced is None or replaced.effect_kind != effects.get("event_type", "actual_progress"):
            raise HTTPException(422, detail={"code": "INVALID_CORRECTION_REFERENCE"})
    if is_blocker:
        from ...progress.history import BLOCKER_CATEGORIES, event_statuses
        observation = db.get(Observation, proposal.observation_id)
        job = db.get(Job, observation.job_id)
        if (not effective_date or not isinstance(effects.get("blocker"), str)
                or not effects["blocker"].strip() or len(effects["blocker"]) > 2000
                or effects.get("blocker_category") not in BLOCKER_CATEGORIES
                or set(effects) & {"quantity", "reported_percent", "unit", "quantity_semantics"}):
            raise HTTPException(422, detail={"code": "INVALID_BLOCKER"})
        evidence = effects.get("evidence")
        if not isinstance(evidence, list) or not evidence or len(evidence) > 30:
            raise HTTPException(422, detail={"code": "INVALID_EVIDENCE"})
        for item in evidence:
            try:
                fragment = db.get(Fragment, UUID(str(item["fragment_id"])))
                quote = item["quote"]
                if not fragment or fragment.report_id != job.report_id or not isinstance(quote, str) or not quote.strip() or quote not in fragment.original_text:
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise HTTPException(422, detail={"code": "INVALID_EVIDENCE"}) from None
        if supersedes and event_statuses(prior).get(supersedes) != "active":
            raise HTTPException(409, detail={"code": "INACTIVE_CORRECTION_TARGET"})
        event = ProgressEvent(activity_id=activity.id, observation_id=proposal.observation_id,
            proposal_id=proposal.id, proposal_revision=proposal.revision, approved_values=effects,
            effect_kind="blocker", effective_date=effective_date, reviewer_id=user.id,
            supersedes_event_id=supersedes, source_key=f"proposal:{proposal.id}:{proposal.revision}",
            source_schedule_version_id=activity.schedule_version_id)
        before = {"revision": state.revision}
        db.add(event)
        db.flush()
        state.revision += 1
        proposal.review_state = "approved"
        response = {"proposal_id": str(proposal.id), "event_id": str(event.id),
                    "activity_id": str(activity.id), "state_revision": state.revision}
        db.add(AuditEvent(timestamp=datetime.now(timezone.utc), actor_id=user.id, action="approve",
            target_type="proposal", target_id=proposal.id, before=before,
            after={**response, "effect": effects}, reason=body.resolution_notes, request_id=body.idempotency_key))
        db.add(IdempotencyKey(actor_id=user.id, endpoint="approve", key=body.idempotency_key,
            request_hash=request_hash, result_reference=response))
        return response
    if is_lifecycle:
        result = project_lifecycle(db, activity, prior, LifecycleEvent(
            "candidate", parsed.kind, parsed.endpoint, parsed.scope,
            f"observation:{proposal.observation_id}", True,
            str(supersedes) if supersedes else None, parsed.subactivity_key))
        if any("suspected duplicate" in warning for warning in result.warnings):
            raise HTTPException(422, detail={"code": "DUPLICATE_LIFECYCLE_EVENT", "warnings": result.warnings})
        event = ProgressEvent(
            activity_id=activity.id, observation_id=proposal.observation_id, proposal_id=proposal.id,
            proposal_revision=proposal.revision, approved_values=effects,
            effect_kind=parsed.kind.value, effective_date=parsed.endpoint.local_date,
            reviewer_id=user.id, supersedes_event_id=supersedes,
            source_key=f"proposal:{proposal.id}:{proposal.revision}", lifecycle_scope=parsed.scope.value,
            endpoint_time=parsed.endpoint.local_time, endpoint_precision=parsed.endpoint.precision.value,
            endpoint_timezone=parsed.endpoint.timezone, endpoint_basis=parsed.endpoint.basis,
            endpoint_raw_expression=parsed.endpoint.raw_expression,
            endpoint_instant=parsed.endpoint.normalized_instant,
            endpoint_evidence=[item.model_dump(mode="json") for item in parsed.evidence],
            source_schedule_version_id=activity.schedule_version_id)
        before = {**_lifecycle_snapshot(state), "revision": state.revision, "actual_start": str(state.actual_start) if state.actual_start else None,
                  "actual_finish": str(state.actual_finish) if state.actual_finish else None,
                  "status": state.lifecycle_status, "physical_percent": str(state.physical_percent) if state.physical_percent is not None else None}
        db.add(event)
        db.flush()
        apply_lifecycle_state(state, result, activity.schedule_version_id, event.id, parsed.kind.value)
        state.revision += 1
        enqueue(db, activity, state)
        proposal.review_state = "approved"
        response = {"proposal_id": str(proposal.id), "event_id": str(event.id),
                    "activity_id": str(activity.id), "state_revision": state.revision}
        after = {**_lifecycle_snapshot(state), "revision": state.revision, "actual_start": str(state.actual_start) if state.actual_start else None,
                 "actual_finish": str(state.actual_finish) if state.actual_finish else None,
                 "status": state.lifecycle_status, "physical_percent": str(state.physical_percent) if state.physical_percent is not None else None,
                 "effect": effects, **response}
        db.add(AuditEvent(timestamp=datetime.now(timezone.utc), actor_id=user.id, action="approve", target_type="proposal", target_id=proposal.id,
                          before=before, after=after, reason=body.resolution_notes, request_id=body.idempotency_key))
        db.add(IdempotencyKey(actor_id=user.id, endpoint="approve", key=body.idempotency_key,
                              request_hash=request_hash, result_reference=response))
        return response
    ledger = [
        LedgerEvent(
            str(event.id), event.effective_date, (event.approved_values or {}).get("quantity"),
            (event.approved_values or {}).get("unit"), (event.approved_values or {}).get("quantity_semantics", "unknown"),
            (event.approved_values or {}).get("event_type", event.effect_kind), str(event.observation_id), True,
            str(event.supersedes_event_id) if event.supersedes_event_id else None,
            (event.approved_values or {}).get("correction_of"),
            (event.approved_values or {}).get("reported_percent"),
        ) for event in prior
    ]
    candidate = LedgerEvent(
        "candidate", effective_date, effects.get("quantity"), effects.get("unit"),
        str(effects.get("quantity_semantics", "unknown")), str(effects.get("event_type", "actual_progress")),
        str(proposal.observation_id), True, str(supersedes) if supersedes else None,
        str(effects["correction_of"]) if effects.get("correction_of") else None,
        effects.get("reported_percent"),
    )
    result = recompute_progress(
        ActivityBaseline(activity.planned_quantity, activity.unit, activity.baseline_quantity, activity.baseline_date, activity.measurement_basis),
        ledger + [candidate],
    )
    if not result.valid:
        raise HTTPException(422, detail={"code": "CONFLICTING_EFFECT", "conflicts": result.conflicts})
    numeric_before = {"revision": state.revision, "completed_quantity": str(state.completed_quantity),
                      "physical_percent": str(state.physical_percent) if state.physical_percent is not None else None}
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
    enqueue(db, activity, state)
    response = {
        "proposal_id": str(proposal.id), "event_id": str(event.id),
        "activity_id": str(activity.id), "state_revision": state.revision,
    }
    db.add(AuditEvent(timestamp=datetime.now(timezone.utc),
        actor_id=user.id, action="approve", target_type="proposal", target_id=proposal.id,
        before=numeric_before, after={**response, "completed_quantity": str(state.completed_quantity),
                                      "physical_percent": str(state.physical_percent) if state.physical_percent is not None else None,
                                      "effect": effects}, reason=body.resolution_notes, request_id=body.idempotency_key,
    ))
    db.add(IdempotencyKey(
        actor_id=user.id, endpoint="approve", key=body.idempotency_key,
        request_hash=request_hash, result_reference=response,
    ))
    return response


class LifecycleCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_activity_revision: int = Field(ge=0)
    endpoint: dict[str, object]
    evidence: list[dict[str, object]] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/events/{event_id}/correct")
def propose_lifecycle_correction(event_id: UUID, body: LifecycleCorrectionRequest,
                                 user: User = Depends(require_reviewer), db: DBSession = Depends(get_session)):
    previous = db.scalar(select(ProgressEvent).where(ProgressEvent.id == event_id).with_for_update())
    if previous is None or previous.effect_kind not in {"actual_start", "actual_finish"}:
        raise HTTPException(404, "Lifecycle event not found")
    original = _proposal(db, previous.proposal_id, user)
    activity = _validate_pinned_activity(db, original, previous.activity_id)
    state = db.scalar(select(ActivityState).where(ActivityState.activity_id == activity.id).with_for_update())
    if state is None or state.revision != body.expected_activity_revision:
        raise HTTPException(409, detail={"code": "STALE_ACTIVITY", "current_revision": state.revision if state else 0})
    if db.scalar(select(ProgressEvent.id).where(ProgressEvent.supersedes_event_id == event_id)):
        raise HTTPException(409, detail={"code": "EVENT_ALREADY_SUPERSEDED"})
    observation = db.get(Observation, original.observation_id)
    job = db.scalar(select(Job).where(Job.id == observation.job_id).with_for_update())
    db.flush()
    next_ordinal = max(db.scalars(select(Observation.ordinal).where(Observation.job_id == job.id)).all(), default=0) + 1
    effects = dict(previous.approved_values or {})
    effects.update(endpoint=body.endpoint, evidence=body.evidence,
                   effective_date=body.endpoint.get("local_date"), supersedes_event_id=str(event_id))
    draft_observation = Observation(job_id=job.id, ordinal=next_ordinal, fragment_id=observation.fragment_id,
                                    fields={"summary": f"Correction of accepted {previous.effect_kind}",
                                            "evidence": body.evidence},
                                    field_evidence={"provenance": {
                                        **capture(
                                            {"summary": f"Correction of accepted {previous.effect_kind}", "evidence": body.evidence},
                                            {"candidate_id": str(activity.id), "explanation": body.reason},
                                            metadata={"capture_mode": "reviewer_correction"}),
                                        "parent_observation_id": str(observation.id),
                                        "parent_event_id": str(event_id),
                                    }})
    db.add(draft_observation)
    db.flush()
    effects["observation_id"] = str(draft_observation.id)
    effects["proposal_id"] = None
    draft = Proposal(observation_id=draft_observation.id, revision=1, project_id=original.project_id,
                     chosen_activity_id=activity.id, candidates=original.candidates,
                     mapping_state="suggested", match_strength="review", review_state="pending",
                     warnings=[], proposed_effects=effects, base_activity_revision=state.revision)
    db.add(draft)
    db.flush()
    effects["proposal_id"] = str(draft.id)
    draft.proposed_effects = effects
    lifecycle_effect(db, draft, activity, effects)
    db.add(AuditEvent(timestamp=datetime.now(timezone.utc), actor_id=user.id, action="propose_correction", target_type="event", target_id=event_id,
                      before={"event_id": str(event_id), "effect": previous.approved_values},
                      after={"proposal_id": str(draft.id), "effect": effects}, reason=body.reason))
    return _proposal_payload(db, draft)


class LifecycleRetractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_activity_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/events/{event_id}/retract")
def retract_lifecycle(event_id: UUID, body: LifecycleRetractionRequest,
                      user: User = Depends(require_reviewer), db: DBSession = Depends(get_session)):
    previous = db.scalar(select(ProgressEvent).where(ProgressEvent.id == event_id).with_for_update())
    if previous is None or previous.effect_kind not in {"actual_start", "actual_finish"}:
        raise HTTPException(404, "Lifecycle event not found")
    original = _proposal(db, previous.proposal_id, user)
    activity = _validate_pinned_activity(db, original, previous.activity_id)
    old = db.scalar(select(IdempotencyKey).where(IdempotencyKey.actor_id == user.id,
                    IdempotencyKey.endpoint == "retract_lifecycle", IdempotencyKey.key == body.idempotency_key))
    request_hash = hashlib.sha256((str(event_id) + ":" + body.model_dump_json()).encode()).hexdigest()
    if old:
        if old.request_hash != request_hash:
            raise HTTPException(409, "Idempotency key reused with different request")
        return old.result_reference
    state = db.scalar(select(ActivityState).where(ActivityState.activity_id == activity.id).with_for_update())
    if state is None or state.revision != body.expected_activity_revision:
        raise HTTPException(409, detail={"code": "STALE_ACTIVITY", "current_revision": state.revision if state else 0})
    prior = db.scalars(select(ProgressEvent).where(ProgressEvent.activity_id == activity.id).with_for_update()).all()
    if any(event.supersedes_event_id == event_id for event in prior):
        raise HTTPException(409, detail={"code": "EVENT_ALREADY_SUPERSEDED"})
    before = {**_lifecycle_snapshot(state), "revision": state.revision, "actual_start": str(state.actual_start) if state.actual_start else None,
              "actual_finish": str(state.actual_finish) if state.actual_finish else None, "status": state.lifecycle_status,
              "effect": previous.approved_values}
    result = project_lifecycle(db, activity, prior + [ProgressEvent(
        activity_id=activity.id, observation_id=previous.observation_id, proposal_id=previous.proposal_id,
        proposal_revision=previous.proposal_revision, approved_values={}, effect_kind="lifecycle_retraction",
        reviewer_id=user.id, supersedes_event_id=event_id)], None)
    tombstone = ProgressEvent(activity_id=activity.id, observation_id=previous.observation_id,
                              proposal_id=previous.proposal_id, proposal_revision=previous.proposal_revision,
                              approved_values={"event_type": "lifecycle_retraction", "retracted_event_id": str(event_id),
                                               "reason": body.reason}, effect_kind="lifecycle_retraction",
                              effective_date=previous.effective_date, reviewer_id=user.id,
                              supersedes_event_id=event_id,
                              source_key=f"retraction:{event_id}", source_schedule_version_id=activity.schedule_version_id)
    db.add(tombstone)
    db.flush()
    state.actual_start = result.actual_start.local_date if result.actual_start else None
    state.actual_finish = result.actual_finish.local_date if result.actual_finish else None
    state.actual_start_time = result.actual_start.local_time if result.actual_start else None
    state.actual_finish_time = result.actual_finish.local_time if result.actual_finish else None
    state.actual_start_precision = result.actual_start.precision.value if result.actual_start else None
    state.actual_finish_precision = result.actual_finish.precision.value if result.actual_finish else None
    state.lifecycle_status = result.status
    state.lifecycle_start_event_id = None if previous.effect_kind == "actual_start" else state.lifecycle_start_event_id
    state.lifecycle_finish_event_id = None if previous.effect_kind == "actual_finish" else state.lifecycle_finish_event_id
    state.revision += 1
    enqueue(db, activity, state)
    response = {"event_id": str(tombstone.id), "retracted_event_id": str(event_id),
                "activity_id": str(activity.id), "state_revision": state.revision}
    db.add(AuditEvent(timestamp=datetime.now(timezone.utc), actor_id=user.id, action="retract", target_type="event", target_id=event_id,
                      before=before, after={**_lifecycle_snapshot(state), **response, "effect": tombstone.approved_values, "actual_start": str(state.actual_start) if state.actual_start else None,
                                            "actual_finish": str(state.actual_finish) if state.actual_finish else None,
                                            "status": state.lifecycle_status}, reason=body.reason,
                      request_id=body.idempotency_key))
    db.add(IdempotencyKey(actor_id=user.id, endpoint="retract_lifecycle", key=body.idempotency_key,
                          request_hash=request_hash, result_reference=response))
    return response


class BlockerCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_activity_revision: int = Field(ge=0)
    blocker: str = Field(min_length=1, max_length=2000)
    blocker_category: str
    effective_date: date
    evidence: list[dict[str, object]] = Field(min_length=1, max_length=30)
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/events/{event_id}/correct-blocker")
def propose_blocker_correction(event_id: UUID, body: BlockerCorrectionRequest,
    user: User = Depends(require_reviewer), db: DBSession = Depends(get_session)):
    from ...progress.history import BLOCKER_CATEGORIES
    previous = db.scalar(select(ProgressEvent).where(ProgressEvent.id == event_id).with_for_update())
    if not previous or previous.effect_kind != "blocker":
        raise HTTPException(404, "Blocker event not found")
    original = _proposal(db, previous.proposal_id, user)
    activity = _validate_pinned_activity(db, original, previous.activity_id)
    state = db.scalar(select(ActivityState).where(ActivityState.activity_id == activity.id).with_for_update())
    if not state or state.revision != body.expected_activity_revision:
        raise HTTPException(409, detail={"code": "STALE_ACTIVITY"})
    if db.scalar(select(ProgressEvent.id).where(ProgressEvent.supersedes_event_id == event_id)):
        raise HTTPException(409, detail={"code": "EVENT_ALREADY_SUPERSEDED"})
    if body.blocker_category not in BLOCKER_CATEGORIES or not body.blocker.strip():
        raise HTTPException(422, detail={"code": "INVALID_BLOCKER"})
    observation = db.get(Observation, original.observation_id)
    job = db.scalar(select(Job).where(Job.id == observation.job_id).with_for_update())
    for item in body.evidence:
        try:
            fragment = db.get(Fragment, UUID(str(item["fragment_id"])))
            if not fragment or fragment.report_id != job.report_id or not item["quote"].strip() or item["quote"] not in fragment.original_text:
                raise ValueError()
        except (KeyError, ValueError, TypeError, AttributeError):
            raise HTTPException(422, detail={"code": "INVALID_EVIDENCE"}) from None
    ordinal = max(db.scalars(select(Observation.ordinal).where(Observation.job_id == job.id)).all(), default=0) + 1
    fields = {"summary": body.blocker, "evidence": body.evidence}
    child = Observation(job_id=job.id, fragment_id=observation.fragment_id, ordinal=ordinal,
        fields=fields, field_evidence={"provenance": {**capture(fields, {"candidate_id": str(activity.id)},
            metadata={"capture_mode": "reviewer_correction"}), "parent_event_id": str(event_id),
            "parent_observation_id": str(observation.id)}})
    db.add(child)
    db.flush()
    effects = {"event_type": "blocker", "blocker": body.blocker, "blocker_category": body.blocker_category,
        "effective_date": body.effective_date.isoformat(), "evidence": body.evidence, "supersedes_event_id": str(event_id)}
    draft = Proposal(observation_id=child.id, revision=1, project_id=original.project_id,
        chosen_activity_id=activity.id, candidates=original.candidates, mapping_state="suggested",
        match_strength="review", review_state="pending", warnings=[], proposed_effects=effects,
        base_activity_revision=state.revision)
    db.add(draft)
    db.flush()
    db.add(AuditEvent(timestamp=datetime.now(timezone.utc), actor_id=user.id, action="propose_correction",
        target_type="event", target_id=event_id, before={"effect": previous.approved_values},
        after={"proposal_id": str(draft.id), "effect": effects}, reason=body.reason))
    return _proposal_payload(db, draft)
