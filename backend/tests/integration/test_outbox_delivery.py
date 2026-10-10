"""Developer fixtures: real HTTP receiver plus transactional acceptance/outbox."""
from datetime import datetime, timedelta, timezone
from threading import Thread
from uuid import uuid4
import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker
from app.db.models import IntegrationOutbox, User, ActivityState, Project
from app.db.session import engine
from app.api.endpoints.review import approve, ApprovalRequest, retract_lifecycle, LifecycleRetractionRequest
from app.api.endpoints.progress import progress_view
from app.integrations.outbox import run_once
from app.integrations.mock_pmis import MockPMISConnector
from app.integrations.base import PermanentDeliveryError
from ops.mock_pmis_server import create_server
from backend.tests.integration.test_lifecycle_acceptance import _lifecycle


@pytest.fixture
def db_pair():
    """Use a rollback-only DB transaction with an empty outbox view.

    The delivery worker scans all pending outbox rows, so project-scoped
    assertions alone are not enough when a shared developer DB has stale rows.
    Delete them only inside this fixture's outer transaction; teardown rolls the
    deletion back and preserves every persisted row in the shared database.
    """
    connection = engine.connect()
    outer = connection.begin()
    connection.execute(delete(IntegrationOutbox))
    factory = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        yield factory
    finally:
        outer.rollback()
        connection.close()


@pytest.fixture
def receiver(tmp_path):
    server = create_server(str(tmp_path / "pmis.sqlite"), 0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield MockPMISConnector(f"http://127.0.0.1:{server.server_port}")
    server.shutdown()
    server.server_close()
    thread.join()


def accept(factory):
    user, proposal, activity, project = _lifecycle(factory, "actual_start", "2026-01-02", time="08:30:00")
    request = ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0, idempotency_key="outbox")
    with factory() as db:
        result = approve(proposal, request, db.get(User, user), db)
        db.commit()
        assert approve(proposal, request, db.get(User, user), db) == result
        db.commit()
    return user, activity, project, result


def rows(factory, project_id):
    """Read only this test's project; shared integration databases may be populated."""
    with factory() as db:
        return db.scalars(
            select(IntegrationOutbox)
            .where(IntegrationOutbox.project_id == project_id)
            .order_by(IntegrationOutbox.state_revision)
        ).all()


def test_accept_timeout_retry_retraction_and_old_delivery(db_pair, receiver):
    user, activity, project, result = accept(db_pair)
    assert len(rows(db_pair, project)) == 1
    first = rows(db_pair, project)[0]
    assert first.payload["state"]["actual_start"]["local_time"] == "08:30:00"
    class LostResponse:
        def deliver(self, payload):
            receiver.deliver(payload)
            raise TimeoutError("timeout after receiver committed")
    assert run_once(db_pair, LostResponse())
    assert rows(db_pair, project)[0].status == "retry"
    with db_pair() as db:
        assert db.get(ActivityState, activity).actual_start_time.hour == 8
        db.get(IntegrationOutbox, first.id).next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert run_once(db_pair, receiver)
    assert rows(db_pair, project)[0].attempts == 2
    assert rows(db_pair, project)[0].receipt["verified"]
    with db_pair() as db:
        retract_lifecycle(result["event_id"], LifecycleRetractionRequest(expected_activity_revision=1,
            idempotency_key="retract-outbox", reason="Developer fixture correction"), db.get(User, user), db)
        db.commit()
    assert run_once(db_pair, receiver)
    second = rows(db_pair, project)[1]
    assert second.payload["state"]["actual_start"] is None
    # Delayed old payload under a new key also cannot overwrite the correction.
    old = {**first.payload, "idempotency_key": str(uuid4())}
    receipt = receiver.deliver(old)
    assert not receipt["applied"] and receipt["read_back_revision"] == 2
    with db_pair() as db:
        view = progress_view(project=db.get(Project, project), _user=db.get(User, user), db=db)
        assert view["items"][0]["delivery"]["status"] == "delivered"


def test_rollback_and_permanent_failure(db_pair, receiver):
    user, proposal, activity, project = _lifecycle(db_pair, "actual_finish", "2026-01-03")
    with db_pair() as db:
        approve(proposal, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0,
                idempotency_key="rollback"), db.get(User, user), db)
        db.rollback()
    assert rows(db_pair, project) == []
    with db_pair() as db:
        approve(proposal, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0,
                idempotency_key="finish"), db.get(User, user), db)
        db.commit()
    payload = rows(db_pair, project)[0].payload
    assert payload["state"]["actual_finish"]["local_time"] is None
    assert payload["state"]["actual_finish"]["precision"] == "date"
    assert run_once(db_pair, receiver)
    bad = {**payload, "idempotency_key": str(uuid4()), "activity_id": str(uuid4()), "state_revision": 2}
    with pytest.raises(PermanentDeliveryError):
        receiver.deliver(bad)


def test_failed_delivery_does_not_erase_acceptance(db_pair):
    _, activity, project, _ = accept(db_pair)
    class BadMapping:
        def deliver(self, payload):
            raise PermanentDeliveryError("mapping/version rejected")
    assert run_once(db_pair, BadMapping())
    assert rows(db_pair, project)[0].status == "failed"
    assert not run_once(db_pair, BadMapping())
    with db_pair() as db:
        assert db.get(ActivityState, activity).revision == 1


def test_accepted_correction_is_ordered_and_precision_preserved(db_pair, receiver):
    from app.api.endpoints.review import propose_lifecycle_correction, LifecycleCorrectionRequest
    from app.db.models import ProgressEvent
    user, activity, project, result = accept(db_pair)
    with db_pair() as db:
        event = db.get(ProgressEvent, result["event_id"])
        endpoint = {**event.approved_values["endpoint"], "local_time": None, "precision": "date"}
        draft = propose_lifecycle_correction(event.id, LifecycleCorrectionRequest(
            expected_activity_revision=1, endpoint=endpoint, evidence=event.approved_values["evidence"],
            reason="Retain only date precision in developer fixture"), db.get(User, user), db)
        approve(draft["id"], ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=1,
            idempotency_key="correction"), db.get(User, user), db)
        db.commit()
    assert len(rows(db_pair, project)) == 2
    assert run_once(db_pair, receiver)
    assert rows(db_pair, project)[0].status == "delivered"
    assert rows(db_pair, project)[1].status == "pending"
    assert run_once(db_pair, receiver)
    latest = rows(db_pair, project)[1]
    assert latest.receipt["read_back_revision"] == 2
    assert latest.payload["state"]["actual_start"]["local_time"] is None
    assert latest.payload["state"]["actual_start"]["precision"] == "date"
