"""Transactional snapshots; workers only observe committed rows."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import select, or_, exists
from sqlalchemy.orm import aliased
from app.db.models import IntegrationOutbox, ScheduleVersion, ProgressEvent
from .base import LABEL, PermanentDeliveryError


def enqueue(db, activity, state):
    schedule = db.get(ScheduleVersion, activity.schedule_version_id)
    key = uuid4()
    def endpoint(kind):
        value = getattr(state, kind)
        if value is None:
            return None
        event = db.get(ProgressEvent, getattr(state, "lifecycle_" + kind.removeprefix("actual_") + "_event_id")) if getattr(state, "lifecycle_" + kind.removeprefix("actual_") + "_event_id") else None
        if event and isinstance((event.approved_values or {}).get("endpoint"), dict):
            return event.approved_values["endpoint"]
        clock = getattr(state, kind + "_time")
        return {"local_date": value.isoformat(), "local_time": clock.isoformat() if clock else None,
                "precision": getattr(state, kind + "_precision") or "date", "basis": "imported_baseline"}
    payload = {"label": LABEL, "idempotency_key": str(key),
               "project_id": str(schedule.project_id), "external_project_id": str(schedule.project_id),
               "activity_id": str(activity.id), "external_activity_id": activity.external_id,
               "source_schedule_version_id": str(schedule.id), "source_schedule_version": schedule.version_number,
               "state_revision": state.revision,
               "state": {"actual_start": endpoint("actual_start"), "actual_finish": endpoint("actual_finish"),
                         "lifecycle_status": state.lifecycle_status,
                         "completed_quantity": str(state.completed_quantity),
                         "physical_percent": str(state.physical_percent) if state.physical_percent is not None else None}}
    db.add(IntegrationOutbox(id=key, project_id=schedule.project_id, activity_id=activity.id,
                             state_revision=state.revision, payload=payload))


def run_once(factory, connector):
    # Lock held through bounded HTTP IO. A crash rolls back the claim; receiver idempotency
    # makes a retry safe even when it applied the request before the worker crashed.
    with factory() as db, db.begin():
        now = datetime.now(timezone.utc)
        older = aliased(IntegrationOutbox)
        row = db.scalar(select(IntegrationOutbox).where(
            IntegrationOutbox.status.in_(["pending", "retry"]),
            or_(IntegrationOutbox.next_attempt_at.is_(None), IntegrationOutbox.next_attempt_at <= now),
            ~exists(select(older.id).where(older.activity_id == IntegrationOutbox.activity_id,
                older.state_revision < IntegrationOutbox.state_revision,
                older.status.in_(["pending", "retry", "failed"])))
        ).order_by(IntegrationOutbox.created_at, IntegrationOutbox.state_revision)
          .with_for_update(skip_locked=True).limit(1))
        if row is None:
            return False
        row.attempts += 1
        row.attempted_at = now
        try:
            row.receipt = connector.deliver(row.payload)
            row.status = "delivered"
            row.delivered_at = datetime.now(timezone.utc)
            row.last_error = None
            row.next_attempt_at = None
        except PermanentDeliveryError as exc:
            row.status = "failed"
            row.last_error = str(exc)
        except Exception as exc:
            row.status = "retry"
            row.last_error = str(exc)
            row.next_attempt_at = now + timedelta(seconds=min(300, 2 ** min(row.attempts, 8)))
        return True
