"""Baseline preservation and activation/approval serialization regressions."""
from datetime import date
from decimal import Decimal
from queue import Queue
from threading import Event, Thread
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.orm import sessionmaker

from app.api.endpoints.progress import progress_view
from app.api.endpoints.review import ApprovalRequest, approve
from app.api.endpoints.schedules import ActivationRequest, activate_schedule
from app.db.models import (
    Activity, ActivityState, AuditEvent, IdempotencyKey, IntegrationOutbox,
    ProgressEvent, Project, ScheduleVersion, User,
)
from app.db.session import engine
from backend.tests.integration.test_lifecycle_acceptance import _lifecycle
from backend.tests.integration.test_review_concurrency import _pending


@pytest.fixture
def db_pair():
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield sessionmaker(bind=connection, expire_on_commit=False,
                               join_transaction_mode="create_savepoint")
        finally:
            transaction.rollback()


@pytest.mark.parametrize("kind", ["numeric", "lifecycle"])
def test_baseline_survives_progress_read_and_first_approval(db_pair, kind):
    ids = (_pending(db_pair) if kind == "numeric" else
           _lifecycle(db_pair, "actual_finish", "2026-01-02"))
    user_id, proposal_id, activity_id, project_id = ids
    with db_pair() as db:
        db.execute(delete(ActivityState).where(ActivityState.activity_id == activity_id))
        activity = db.get(Activity, activity_id)
        activity.measurement_basis = "quantity_ratio"
        activity.baseline_quantity = Decimal("2")
        activity.actual_start = date(2026, 1, 1)
        db.flush()
        project, user = db.get(Project, project_id), db.get(User, user_id)
        item = progress_view(None, project, user, db)["items"][0]
        assert Decimal(item["completed_quantity"]) == 2
        assert Decimal(item["physical_percent"]) == 20
        assert item["actual_start"] == "2026-01-01"
        assert item["actual_start_precision"] == "date"
        # A GET projects the baseline without writing durable state.
        assert db.get(ActivityState, activity_id) is None
        approve(proposal_id, ApprovalRequest(expected_proposal_revision=1,
                expected_activity_revision=0, idempotency_key=f"baseline-{kind}"), user, db)
        db.flush()
        state = db.get(ActivityState, activity_id)
        assert state.completed_quantity == (4 if kind == "numeric" else 2)
        assert state.physical_percent == (40 if kind == "numeric" else 20)
        assert state.actual_start == date(2026, 1, 1)
        if kind == "lifecycle":
            assert state.actual_finish == date(2026, 1, 2)
        delivery = db.scalar(select(IntegrationOutbox).where(
            IntegrationOutbox.activity_id == activity_id))
        assert Decimal(delivery.payload["state"]["completed_quantity"]) == state.completed_quantity


@pytest.mark.parametrize("winner", ["activation", "approval"])
def test_activation_and_first_approval_serialize(winner):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    user_id, proposal_id, activity_id, project_id = _pending(factory)
    with factory.begin() as db:
        target = ScheduleVersion(project_id=project_id, version_number=2,
                                 content_sha256=uuid4().hex, state="staged")
        db.add(target)
    locked, release, loser_started, loser_finished = Event(), Event(), Event(), Event()
    results = Queue()

    def run(action, first):
        try:
            with factory.begin() as db:
                db.execute(text("SET LOCAL lock_timeout = '5s'"))
                db.execute(text("SET LOCAL statement_timeout = '8s'"))
                user = db.get(User, user_id)
                project = db.get(Project, project_id)
                if first:
                    db.scalar(select(Project).where(Project.id == project_id).with_for_update())
                    locked.set()
                    assert release.wait(5), "winner was not released"
                else:
                    loser_started.set()
                if action == "activation":
                    activate_schedule(2, ActivationRequest(expected_active_version=1),
                                      project, db, user)
                else:
                    approve(proposal_id, ApprovalRequest(expected_proposal_revision=1,
                            expected_activity_revision=0, idempotency_key="activation-race"), user, db)
            results.put((action, "ok"))
        except HTTPException as exc:
            results.put((action, exc.detail["code"]))
        except Exception as exc:
            results.put((action, exc))
        finally:
            if not first:
                loser_finished.set()

    loser = "approval" if winner == "activation" else "activation"
    first = Thread(target=run, args=(winner, True))
    second = Thread(target=run, args=(loser, False))
    try:
        first.start()
        assert locked.wait(5)
        second.start()
        assert loser_started.wait(5)
        # Both operations must honor the project lock before changing progress.
        assert not loser_finished.wait(.2)
        release.set()
        first.join(10)
        second.join(10)
        assert not first.is_alive() and not second.is_alive()
        outcomes = dict(results.queue)
        assert outcomes[winner] == "ok", outcomes
        assert outcomes[loser] == ("STALE_SCHEDULE" if winner == "activation"
                                   else "SCHEDULE_REBASE_REQUIRED"), outcomes
        with factory() as db:
            project = db.get(Project, project_id)
            active = db.get(ScheduleVersion, project.active_schedule_version_id)
            assert active.version_number == (2 if winner == "activation" else 1)
            assert db.get(ActivityState, activity_id).revision == (0 if winner == "activation" else 1)
    finally:
        release.set()
        if first.ident:
            first.join(10)
        if second.ident:
            second.join(10)
        with factory.begin() as db:
            db.execute(delete(IntegrationOutbox).where(IntegrationOutbox.activity_id == activity_id))
            db.execute(delete(ProgressEvent).where(ProgressEvent.activity_id == activity_id))
            db.execute(delete(IdempotencyKey).where(IdempotencyKey.actor_id == user_id))
            db.execute(delete(AuditEvent).where(AuditEvent.actor_id == user_id))
            db.execute(delete(Project).where(Project.id == project_id))
            db.execute(delete(User).where(User.id == user_id))
