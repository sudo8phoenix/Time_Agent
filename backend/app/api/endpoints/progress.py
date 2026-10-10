"""Authenticated approved-progress views and generic handoff export."""

from __future__ import annotations

import csv
import json
from datetime import date
from typing import Literal
from io import StringIO
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from ...db.models import (
    IntegrationOutbox,
    Activity,
    ActivityState,
    Fragment,
    Observation,
    ProgressEvent,
    Project,
    Proposal,
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
        "scope": values.get("scope"),
        "subactivity_key": values.get("subactivity_key"),
        "scheduled_parent_id": values.get("scheduled_parent_id"),
        "endpoint": values.get("endpoint"),
        "evidence": values.get("evidence"),
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
    from ...progress.history import event_statuses

    statuses = event_statuses([event for event, _ in events])
    history: dict[UUID, list[dict[str, object]]] = {}
    for event, locator in events:
        history.setdefault(event.activity_id, []).append(
            {
                **_event(event, locator),
                "status": statuses[event.id],
                "active": statuses[event.id] == "active",
            }
        )
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
    deliveries = {}
    blocked = {}
    for row in db.scalars(
        select(IntegrationOutbox)
        .where(IntegrationOutbox.project_id == project.id)
        .order_by(IntegrationOutbox.state_revision)
    ).all():
        if row.status == "failed":
            blocked[row.activity_id] = row.last_error
        deliveries[row.activity_id] = {
            "label": "MOCK PMIS — prototype",
            "status": row.status,
            "revision": row.state_revision,
            "attempts": row.attempts,
            "last_error": row.last_error,
            "attempted_at": row.attempted_at,
            "delivered_at": row.delivered_at,
            "receipt": row.receipt,
        }
    items = [
        {
            "delivery": (
                {
                    **deliveries[a.id],
                    "last_error": blocked.get(a.id) or deliveries[a.id]["last_error"],
                    "status": "blocked"
                    if a.id in blocked and deliveries[a.id]["status"] != "failed"
                    else deliveries[a.id]["status"],
                }
                if a.id in deliveries
                else None
            ),
            "activity_id": str(a.id),
            "state_revision": states[a.id].revision if a.id in states else 0,
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
            "lifecycle_status": states[a.id].lifecycle_status if a.id in states else None,
            "actual_start_time": states[a.id].actual_start_time.isoformat()
            if a.id in states and states[a.id].actual_start_time
            else None,
            "actual_finish_time": states[a.id].actual_finish_time.isoformat()
            if a.id in states and states[a.id].actual_finish_time
            else None,
            "actual_start_precision": states[a.id].actual_start_precision
            if a.id in states
            else None,
            "actual_finish_precision": states[a.id].actual_finish_precision
            if a.id in states
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


def _history_selection(
    db,
    schedule,
    *,
    activity_id=None,
    discipline=None,
    work_type=None,
    date_from=None,
    date_to=None,
    blocker=None,
    correction_status=None,
    active_only=False,
    status=None,
):
    from ...progress.history import history_query, event_statuses

    events = db.execute(
        select(ProgressEvent.id, ProgressEvent.supersedes_event_id, ProgressEvent.effect_kind)
        .join(Activity, Activity.id == ProgressEvent.activity_id)
        .where(Activity.schedule_version_id == schedule.id)
    ).all()
    statuses = event_statuses(events)
    query = history_query(schedule.id)
    if activity_id:
        query = query.where(Activity.id == activity_id)
    if discipline:
        query = query.where(Activity.discipline == discipline)
    if work_type:
        query = query.where(Activity.work_type == work_type)
    if date_from:
        query = query.where(ProgressEvent.effective_date >= date_from)
    if date_to:
        query = query.where(ProgressEvent.effective_date <= date_to)
    if blocker:
        query = query.where(ProgressEvent.effect_kind == "blocker")
        if blocker != "any":
            query = query.where(
                ProgressEvent.approved_values["blocker_category"].as_string() == blocker
            )
    if active_only or status:
        query = query.where(
            ProgressEvent.id.in_(
                [
                    key
                    for key, value in statuses.items()
                    if value == ("active" if active_only else status)
                ]
            )
        )
    if correction_status == "original":
        query = query.where(ProgressEvent.supersedes_event_id.is_(None))
    elif correction_status == "correction":
        query = query.where(
            ProgressEvent.supersedes_event_id.is_not(None),
            ProgressEvent.effect_kind != "lifecycle_retraction",
        )
    elif correction_status == "retraction":
        query = query.where(ProgressEvent.effect_kind == "lifecycle_retraction")
    return query.order_by(ProgressEvent.approved_at.desc(), ProgressEvent.id), statuses


@router.get("/history")
def execution_history(
    version: int | None = None,
    activity_id: UUID | None = None,
    discipline: str | None = None,
    work_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    blocker: str | None = None,
    correction_status: Literal["original", "correction", "retraction"] | None = None,
    status: Literal["active", "superseded", "retracted", "retraction"] | None = None,
    active_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    project: Project = Depends(project_access),
    _user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
):
    from ...progress.history import serialize

    schedule = _version(project, version, db)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "Date range is reversed")
    query, statuses = _history_selection(
        db,
        schedule,
        activity_id=activity_id,
        discipline=discipline,
        work_type=work_type,
        date_from=date_from,
        date_to=date_to,
        blocker=blocker,
        correction_status=correction_status,
        active_only=active_only,
        status=status,
    )
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = db.execute(query.offset(offset).limit(limit)).all()
    return {
        "project_id": str(project.id),
        "schedule_version": schedule.version_number,
        "total": total,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < total else None,
        "notice": "Accepted values describe each event. Latest activity state is a separate current projection.",
        "items": [serialize(db, row, statuses[row[0].id]) for row in rows],
    }


@router.get("/blockers")
def recurring_blockers(
    version: int | None = None,
    work_type: str | None = None,
    project: Project = Depends(project_access),
    _user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
):
    schedule = _version(project, version, db)
    query, statuses = _history_selection(
        db, schedule, work_type=work_type, blocker="any", active_only=True
    )
    groups = {}
    for row in db.execute(query).all():
        event = row[0]
        category = (event.approved_values or {}).get("blocker_category", "other")
        group = groups.setdefault(
            category, {"category": category, "count": 0, "evidence_links": []}
        )
        group["count"] += 1
        if len(group["evidence_links"]) < 20:
            group["evidence_links"].append(
                {
                    "event_id": str(event.id),
                    "activity_id": str(event.activity_id),
                    "history_url": f"/api/v1/projects/{project.id}/history?version={schedule.version_number}&activity_id={event.activity_id}&blocker={category}",
                    "source_locator": row[6].locator if row[6] else None,
                    "evidence": (event.approved_values or {}).get("evidence", []),
                }
            )
    return {
        "basis": "active reviewed blocker events; correction chains counted once",
        "items": list(groups.values()),
    }


@router.get("/exports/approved.json")
def approved_json(
    version: int | None = None,
    active_only: bool = False,
    project: Project = Depends(project_access),
    _user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
):
    from ...progress.history import serialize

    schedule = _version(project, version, db)
    query, statuses = _history_selection(db, schedule, active_only=active_only)
    return {
        "project_id": str(project.id),
        "schedule_version": schedule.version_number,
        "notice": "accepted_values are immutable event-time values; latest_activity_state is current state",
        "items": [serialize(db, row, statuses[row[0].id]) for row in db.execute(query).all()],
    }


@router.get("/exports/approved.csv")
def approved_export(
    version: int | None = None,
    active_only: bool = False,
    project: Project = Depends(project_access),
    _user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
):
    payload = approved_json(version, active_only, project, _user, db)
    output = StringIO(newline="")
    columns = [
        "project_name",
        "project_id",
        "schedule_version",
        "activity_id",
        "activity_external_id",
        "activity_name",
        "discipline",
        "work_type",
        "wbs",
        "event_id",
        "work_date",
        "event_type",
        "status",
        "active",
        "correction_status",
        "lifecycle_scope",
        "subactivity_key",
        "scheduled_parent_id",
        "endpoint_date",
        "endpoint_time",
        "endpoint_precision",
        "endpoint_timezone",
        "endpoint_basis",
        "supersedes_event_id",
        "quantity_kind",
        "quantity_value",
        "unit",
        "blocker",
        "blocker_category",
        "evidence",
        "source_locator",
        "confidence",
        "accepted_values",
        "latest_state_revision",
        "latest_completed_quantity",
        "latest_physical_percent",
        "latest_actual_start",
        "latest_actual_start_time",
        "latest_actual_start_precision",
        "latest_actual_finish",
        "latest_actual_finish_time",
        "latest_actual_finish_precision",
        "reviewer",
        "review_time",
        "report_id",
        "source_file_id",
        "source_schedule_version_id",
        "model_version",
        "prompt_version",
        "config_version",
        "provenance",
        "decisions",
        "warnings",
    ]
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for item in payload["items"]:
        endpoint = item["endpoint"] or {}
        values = item["accepted_values"]
        state = item["latest_activity_state"] or {}
        row = {
            **{key: item.get(key) for key in columns},
            "project_name": project.name,
            "project_id": project.id,
            "schedule_version": payload["schedule_version"],
            "lifecycle_scope": item["scope"],
            "review_time": item["approved_at"],
            "quantity_kind": values.get("quantity_semantics"),
            "quantity_value": values.get("quantity"),
            "latest_state_revision": state.get("revision"),
        }
        row.update(
            {
                "endpoint_" + key: endpoint.get(value)
                for key, value in [
                    ("date", "local_date"),
                    ("time", "local_time"),
                    ("precision", "precision"),
                    ("timezone", "timezone"),
                    ("basis", "basis"),
                ]
            }
        )
        row.update({"latest_" + key: value for key, value in state.items() if key != "revision"})
        writer.writerow(
            {
                key: _safe_csv(
                    json.dumps(value, default=str) if isinstance(value, (dict, list)) else value
                )
                for key, value in row.items()
                if key in columns
            }
        )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="approved-progress-v{payload["schedule_version"]}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/integration-deliveries")
def integration_deliveries(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    project: Project = Depends(project_access),
    _user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
):
    rows = db.scalars(
        select(IntegrationOutbox)
        .where(IntegrationOutbox.project_id == project.id)
        .order_by(IntegrationOutbox.created_at.desc(), IntegrationOutbox.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "label": "MOCK PMIS — prototype",
        "items": [
            {
                "id": str(row.id),
                "activity_id": str(row.activity_id),
                "revision": row.state_revision,
                "status": row.status,
                "attempts": row.attempts,
                "created_at": row.created_at,
                "attempted_at": row.attempted_at,
                "next_attempt_at": row.next_attempt_at,
                "delivered_at": row.delivered_at,
                "last_error": row.last_error,
                "receipt": row.receipt,
                "payload": row.payload,
            }
            for row in rows
        ],
    }


@router.get("/durations")
def actual_durations(
    version: int | None = None,
    work_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    project: Project = Depends(project_access),
    _user: User = Depends(current_user),
    db: DBSession = Depends(get_session),
):
    from dataclasses import asdict
    from ...progress.duration import calculate_duration, labour_productivity
    from ...schemas.events import Endpoint

    schedule = _version(project, version, db)
    query = (
        select(Activity, ActivityState)
        .outerjoin(ActivityState, ActivityState.activity_id == Activity.id)
        .where(Activity.schedule_version_id == schedule.id)
    )
    if work_type:
        query = query.where(Activity.work_type == work_type)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(Activity.external_id, Activity.id).offset(offset).limit(limit)
    ).all()
    items = []
    for activity, state in rows:
        endpoints = []
        for key in ("lifecycle_start_event_id", "lifecycle_finish_event_id"):
            event = (
                db.get(ProgressEvent, getattr(state, key))
                if state and getattr(state, key)
                else None
            )
            try:
                endpoints.append(
                    Endpoint.model_validate((event.approved_values or {}).get("endpoint"))
                    if event
                    else None
                )
            except ValueError:
                endpoints.append(None)
        items.append(
            {
                "activity_id": str(activity.id),
                "activity_external_id": activity.external_id,
                "name": activity.name,
                "work_type": activity.work_type,
                "scope": "whole_activity",
                "elapsed": asdict(calculate_duration(*endpoints)),
                "calendar_working": {
                    "status": "unavailable",
                    "basis": "reviewed_calendar_intersection",
                    "reason": "reviewed_versioned_calendar_definition_unavailable",
                },
                "labour_productivity": asdict(labour_productivity()),
            }
        )
    return {
        "items": items,
        "total": total,
        "next_offset": offset + limit if offset + limit < total else None,
        "notice": "Elapsed clock time and calendar working time do not measure crew labour or continuous productive work.",
    }
