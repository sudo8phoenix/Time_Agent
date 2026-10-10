"""Immutable accepted-event history, distinct from current activity projections."""

from __future__ import annotations

from uuid import UUID
from sqlalchemy import select
from app.db.models import (
    Activity,
    ActivityState,
    AuditEvent,
    Fragment,
    Job,
    Observation,
    ProgressEvent,
    Proposal,
    Report,
    User,
)
from app.confidence.provenance import context

BLOCKER_CATEGORIES = (
    "access",
    "design",
    "equipment",
    "inspection",
    "labour",
    "material",
    "safety",
    "weather",
    "other",
)


def event_statuses(events):
    """A retraction withdraws the correction chain; originals never resurrect."""
    parents = {event.id: event.supersedes_event_id for event in events}
    superseded = {parent for parent in parents.values() if parent}
    retracted = set()
    for event in events:
        if event.effect_kind == "lifecycle_retraction":
            parent = event.supersedes_event_id
            while parent and parent not in retracted:
                retracted.add(parent)
                parent = parents.get(parent)
    return {
        event.id: (
            "retraction"
            if event.effect_kind == "lifecycle_retraction"
            else "retracted"
            if event.id in retracted
            else "superseded"
            if event.id in superseded
            else "active"
        )
        for event in events
    }


def history_query(schedule_id):
    return (
        select(
            ProgressEvent,
            Activity,
            ActivityState,
            Observation,
            Job,
            Report,
            Fragment,
            Proposal,
            User,
        )
        .join(Activity, Activity.id == ProgressEvent.activity_id)
        .outerjoin(ActivityState, ActivityState.activity_id == Activity.id)
        .join(Observation, Observation.id == ProgressEvent.observation_id)
        .join(Job, Job.id == Observation.job_id)
        .join(Report, Report.id == Job.report_id)
        .outerjoin(Fragment, Fragment.id == Observation.fragment_id)
        .join(Proposal, Proposal.id == ProgressEvent.proposal_id)
        .join(User, User.id == ProgressEvent.reviewer_id)
        .where(Activity.schedule_version_id == schedule_id)
    )


def serialize(db, row, status):
    event, activity, state, observation, job, report, fragment, proposal, reviewer = row
    values = event.approved_values or {}
    provenance = context(db, observation)
    evidence = []
    for item in values.get("evidence") or provenance.get("evidence") or []:
        try:
            source_fragment = db.get(Fragment, UUID(str(item.get("fragment_id"))))
        except (ValueError, TypeError):
            source_fragment = None
        evidence.append(
            {**item, "locator": source_fragment.locator if source_fragment else item.get("locator")}
        )
    audits = db.scalars(
        select(AuditEvent)
        .where(
            ((AuditEvent.target_type == "proposal") & (AuditEvent.target_id == proposal.id))
            | ((AuditEvent.target_type == "event") & (AuditEvent.target_id == event.id))
        )
        .order_by(AuditEvent.timestamp, AuditEvent.id)
    ).all()
    return {
        "event_id": str(event.id),
        "activity_id": str(activity.id),
        "activity_external_id": activity.external_id,
        "activity_name": activity.name,
        "discipline": activity.discipline,
        "work_type": activity.work_type,
        "wbs": activity.wbs,
        "event_type": event.effect_kind,
        "work_date": event.effective_date,
        "status": status,
        "active": status == "active",
        "correction_status": "retraction"
        if event.effect_kind == "lifecycle_retraction"
        else "correction"
        if event.supersedes_event_id
        else "original",
        "supersedes_event_id": str(event.supersedes_event_id)
        if event.supersedes_event_id
        else None,
        "scope": event.lifecycle_scope or values.get("scope"),
        "subactivity_key": values.get("subactivity_key"),
        "scheduled_parent_id": values.get("scheduled_parent_id"),
        "accepted_values": values,
        "endpoint": values.get("endpoint"),
        "quantity": values.get("quantity"),
        "unit": values.get("unit"),
        "blocker": values.get("blocker"),
        "blocker_category": values.get("blocker_category"),
        "evidence": evidence,
        "source_locator": fragment.locator if fragment else None,
        "confidence": provenance.get("confidence"),
        "provenance": provenance,
        "report_id": str(report.id),
        "source_file_id": str(report.file_id) if report.file_id else None,
        "schedule_version_id": str(activity.schedule_version_id),
        "source_schedule_version_id": str(
            event.source_schedule_version_id or job.schedule_version_id
        ),
        "model_version": job.model_version,
        "prompt_version": job.prompt_version,
        "config_version": job.config_version,
        "reviewer_id": str(reviewer.id),
        "reviewer": reviewer.username,
        "approved_at": event.approved_at,
        "warnings": proposal.warnings,
        "decisions": [
            {
                "action": audit.action,
                "actor_id": str(audit.actor_id),
                "timestamp": audit.timestamp,
                "reason": audit.reason,
                "before": audit.before,
                "after": audit.after,
            }
            for audit in audits
        ],
        "latest_activity_state": {
            "revision": state.revision,
            "completed_quantity": str(state.completed_quantity),
            "physical_percent": str(state.physical_percent)
            if state.physical_percent is not None
            else None,
            "actual_start": state.actual_start,
            "actual_start_time": state.actual_start_time,
            "actual_start_precision": state.actual_start_precision,
            "actual_finish": state.actual_finish,
            "actual_finish_time": state.actual_finish_time,
            "actual_finish_precision": state.actual_finish_precision,
        }
        if state
        else None,
    }
