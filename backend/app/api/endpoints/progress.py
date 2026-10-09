"""Authenticated approved-progress views and generic handoff export."""

from __future__ import annotations

import csv
from io import StringIO
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from ...db.models import (
    Activity,
    ActivityState,
    AuditEvent,
    Fragment,
    Job,
    Observation,
    ProgressEvent,
    Project,
    Proposal,
    Report,
    ScheduleVersion,
    User,
)
from ...db.session import get_session
from ..dependencies import current_user, project_access

router = APIRouter(prefix="/projects/{project_id}", tags=["progress"])


def _version(project: Project, version: int | None, db: DBSession) -> ScheduleVersion:
    selected = (
        db.get(ScheduleVersion, project.active_schedule_version_id)
        if version is None and project.active_schedule_version_id
        else db.scalar(
            select(ScheduleVersion).where(
                ScheduleVersion.project_id == project.id, ScheduleVersion.version_number == version
            )
        )
    )
    if selected is None:
        raise HTTPException(
            409 if version is None else 404,
            detail={"code": "NO_ACTIVE_SCHEDULE"}
            if version is None
            else "Schedule version not found",
        )
    return selected


def _event(event: ProgressEvent, locator: str | None) -> dict[str, object]:
    values = event.approved_values or {}
    return {
        "event_id": str(event.id),
        "work_date": event.effective_date.isoformat() if event.effective_date else None,
        "quantity": values.get("quantity"),
        "unit": values.get("unit"),
        "quantity_kind": values.get("quantity_semantics", "unknown"),
        "event_type": values.get("event_type", event.effect_kind),
        "source_locator": locator,
        "supersedes_event_id": str(event.supersedes_event_id)
        if event.supersedes_event_id
        else None,
        "approved_at": event.approved_at.isoformat() if event.approved_at else None,
    }


@router.get("/progress")
def progress_view(
    version: int | None = None,
    project: Project = Depends(project_access),
    _user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
):
    schedule = _version(project, version, db)
    activities = db.scalars(
        select(Activity)
        .where(Activity.schedule_version_id == schedule.id)
        .order_by(Activity.external_id)
    ).all()
    events = db.execute(
        select(ProgressEvent, Fragment.locator)
        .join(Observation, Observation.id == ProgressEvent.observation_id)
        .outerjoin(Fragment, Fragment.id == Observation.fragment_id)
        .join(Activity, Activity.id == ProgressEvent.activity_id)
        .where(Activity.schedule_version_id == schedule.id)
        .order_by(ProgressEvent.effective_date, ProgressEvent.approved_at, ProgressEvent.id)
    ).all()
    history: dict[UUID, list[dict[str, object]]] = {}
    for event, locator in events:
        history.setdefault(event.activity_id, []).append(_event(event, locator))
    states = (
        {
            state.activity_id: state
            for state in db.scalars(
                select(ActivityState).where(
                    ActivityState.activity_id.in_([a.id for a in activities])
                )
            ).all()
        }
        if activities
        else {}
    )
    pending = (
        db.scalar(
            select(func.count(Proposal.id)).where(
                Proposal.project_id == project.id, Proposal.review_state == "pending"
            )
        )
        or 0
    )
    items = [
        {
            "activity_id": str(a.id),
            "external_id": a.external_id,
            "name": a.name,
            "wbs": a.wbs,
            "is_leaf": a.is_leaf,
            "measurement_basis": a.measurement_basis,
            "planned_quantity": str(a.planned_quantity) if a.planned_quantity is not None else None,
            "unit": a.unit,
            "completed_quantity": str(states[a.id].completed_quantity) if a.id in states else "0",
            "physical_percent": str(states[a.id].physical_percent)
            if a.id in states and states[a.id].physical_percent is not None
            else None,
            "actual_start": states[a.id].actual_start.isoformat()
            if a.id in states and states[a.id].actual_start
            else None,
            "actual_finish": states[a.id].actual_finish.isoformat()
            if a.id in states and states[a.id].actual_finish
            else None,
            "last_observed_date": states[a.id].last_observed_date.isoformat()
            if a.id in states and states[a.id].last_observed_date
            else None,
            "approved_event_count": len(history.get(a.id, [])),
            "history": history.get(a.id, []),
        }
        for a in activities
    ]
    return {
        "project_id": str(project.id),
        "project_name": project.name,
        "schedule_version": schedule.version_number,
        "counts": {
            "activities": len(items),
            "approved_events": len(events),
            "pending_review": pending,
        },
        "items": items,
        "notice": "Per-activity values only. No overall project percentage is calculated.",
    }


def _safe_csv(value: object | None) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


@router.get("/exports/approved.csv")
def approved_export(
    version: int | None = None,
    project: Project = Depends(project_access),
    _user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
):
    schedule = _version(project, version, db)
    rows = db.execute(
        select(
            ProgressEvent, Activity, ActivityState, Job, Fragment, Proposal, User, AuditEvent.reason, Report.file_id
        )
        .join(Activity, Activity.id == ProgressEvent.activity_id)
        .outerjoin(ActivityState, ActivityState.activity_id == Activity.id)
        .join(Observation, Observation.id == ProgressEvent.observation_id)
        .join(Job, Job.id == Observation.job_id)
        .join(Report, Report.id == Job.report_id)
        .outerjoin(Fragment, Fragment.id == Observation.fragment_id)
        .join(Proposal, Proposal.id == ProgressEvent.proposal_id)
        .join(User, User.id == ProgressEvent.reviewer_id)
        .outerjoin(
            AuditEvent,
            (AuditEvent.target_type == "proposal")
            & (AuditEvent.target_id == ProgressEvent.proposal_id)
            & (AuditEvent.action == "approve"),
        )
        .where(Activity.schedule_version_id == schedule.id)
        .order_by(ProgressEvent.effective_date, ProgressEvent.approved_at, ProgressEvent.id)
    ).all()
    output = StringIO(newline="")
    columns = [
        "project_name",
        "project_id",
        "schedule_version",
        "activity_external_id",
        "activity_name",
        "event_id",
        "work_date",
        "quantity_kind",
        "quantity_value",
        "unit",
        "approved_completed_quantity",
        "physical_percent",
        "actual_start",
        "actual_finish",
        "reviewer",
        "review_time",
        "report_id",
        "source_file_id",
        "source_locator",
        "explanation",
        "warnings",
    ]
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for event, activity, state, job, fragment, proposal, reviewer, explanation, file_id in rows:
        values = event.approved_values or {}
        values_by_column = {
            "project_name": project.name,
            "project_id": project.id,
            "schedule_version": schedule.version_number,
            "activity_external_id": activity.external_id,
            "activity_name": activity.name,
            "event_id": event.id,
            "work_date": event.effective_date,
            "quantity_kind": values.get("quantity_semantics", "unknown"),
            "quantity_value": values.get("quantity"),
            "unit": values.get("unit"),
            "approved_completed_quantity": state.completed_quantity if state else None,
            "physical_percent": state.physical_percent if state else None,
            "actual_start": state.actual_start if state else None,
            "actual_finish": state.actual_finish if state else None,
            "reviewer": reviewer.username,
            "review_time": event.approved_at,
            "report_id": job.report_id,
            "source_file_id": file_id,
            "source_locator": fragment.locator if fragment else None,
            "explanation": explanation,
            "warnings": "; ".join(map(str, proposal.warnings or [])),
        }
        writer.writerow({key: _safe_csv(value) for key, value in values_by_column.items()})
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="approved-progress-v{schedule.version_number}.csv"',
            "Cache-Control": "no-store",
        },
    )
