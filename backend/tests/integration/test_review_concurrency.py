"""Transaction-isolated approval safety checks for W-13."""
from datetime import date
from decimal import Decimal
from threading import Event, Thread
from queue import Queue
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.api.endpoints.review import ApprovalRequest, ReviewChange, approve, revise
from app.db.models import (
    Activity, ActivityState, AuditEvent, IdempotencyKey, Job, Observation,
    ProgressEvent, Project, ProjectMembership, Proposal, Report,
    ScheduleVersion, User,
)
from app.db.passwords import hash_password
from app.db.session import engine


@pytest.fixture
def db_pair():
    connection = engine.connect()
    outer = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        yield factory
    finally:
        outer.rollback()
        connection.close()


def _pending(factory, *, other_project=False, warnings=None):
    db = factory()
    user = User(username=f"w13-{uuid4().hex}", password_hash=hash_password("x"), role="reviewer")
    project = Project(name=f"p-{uuid4().hex}", timezone="UTC")
    version = ScheduleVersion(project=project, version_number=1, content_sha256=uuid4().hex, state="active")
    activity = Activity(
        schedule_version=version, external_id="A-1", name="Install", wbs="1", discipline="mechanical",
        work_type="pipe_spool_erection", area="A", is_leaf=True, measurement_basis="quantity_ratio",
        planned_quantity=Decimal("10"), unit="spool", baseline_quantity=Decimal("0"), baseline_date=date(2026, 1, 1),
    )
    state = ActivityState(activity=activity, revision=0, completed_quantity=0)
    db.add_all([user, project, version, activity, state])
    db.flush()
    db.add(ProjectMembership(project_id=project.id, user_id=user.id))
    report = Report(project_id=project.id, content_hash=uuid4().hex, report_date=date(2026, 1, 2))
    db.add(report)
    db.flush()
    job = Job(project_id=project.id, report_id=report.id, schedule_version_id=version.id)
    db.add(job)
    db.flush()
    observation = Observation(job_id=job.id, ordinal=1, fields={"summary": "installed", "quantity": "2"}, field_evidence={})
    db.add(observation)
    db.flush()
    proposal = Proposal(
        observation_id=observation.id, revision=1, project_id=project.id, chosen_activity_id=activity.id,
        candidates=[], mapping_state="suggested", match_strength="review", review_state="pending", warnings=warnings or [],
        proposed_effects={"quantity": "2", "unit": "spool", "quantity_semantics": "delta", "event_type": "actual_progress", "effective_date": "2026-01-02"},
    )
    db.add(proposal)
    db.commit()
    ids = (user.id, proposal.id, activity.id, project.id)
    db.close()
    return ids


def _request(key: str):
    return ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0, idempotency_key=key)


def test_two_database_sessions_racing_same_idempotency_key_return_one_approval(monkeypatch):
    """Hold the first transaction after it locks the proposal while a second waits."""
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    user_id, proposal_id, activity_id, project_id = _pending(factory)
    entered_recompute = Event()
    release_first = Event()
    second_started = Event()
    outputs: Queue = Queue()
    errors: Queue = Queue()
    original_recompute = __import__("app.api.endpoints.review", fromlist=["recompute_progress"]).recompute_progress

    def pause_first(*args, **kwargs):
        if __import__("threading").current_thread().name == "approval-first":
            entered_recompute.set()
            assert release_first.wait(timeout=10), "first approval was not released"
        return original_recompute(*args, **kwargs)

    monkeypatch.setattr("app.api.endpoints.review.recompute_progress", pause_first)

    def run_approval(name: str, *, wait_for_lock: bool):
        db = factory()
        try:
            user = db.get(User, user_id)
            if wait_for_lock:
                second_started.set()
            value = approve(proposal_id, ApprovalRequest(
                expected_proposal_revision=1,
                expected_activity_revision=0,
                idempotency_key="concurrent-same-key",
            ), user, db)
            db.commit()
            outputs.put(value)
        except Exception as exc:  # deliver worker failures to the test thread
            db.rollback()
            errors.put(exc)
        finally:
            db.close()

    first = Thread(target=run_approval, args=("first",), kwargs={"wait_for_lock": False}, name="approval-first")
    second = Thread(target=run_approval, args=("second",), kwargs={"wait_for_lock": True}, name="approval-second")
    try:
        first.start()
        assert entered_recompute.wait(timeout=10), "first approval did not reach the post-lock point"
        second.start()
        assert second_started.wait(timeout=10)
        release_first.set()
        first.join(timeout=10)
        second.join(timeout=10)
        assert not first.is_alive() and not second.is_alive(), "approval race did not finish"
        assert errors.empty(), list(errors.queue)
        first_result, second_result = outputs.get_nowait(), outputs.get_nowait()
        assert first_result == second_result

        verify = factory()
        assert verify.scalar(select(Proposal.review_state).where(Proposal.id == proposal_id)) == "approved"
        assert verify.scalar(select(ActivityState.revision).where(ActivityState.activity_id == activity_id)) == 1
        assert len(verify.scalars(select(ProgressEvent).where(ProgressEvent.activity_id == activity_id)).all()) == 1
        verify.close()
    finally:
        release_first.set()
        first.join(timeout=10)
        second.join(timeout=10)
        cleanup = factory()
        cleanup.query(ProgressEvent).filter(ProgressEvent.activity_id == activity_id).delete(synchronize_session=False)
        cleanup.query(IdempotencyKey).filter(IdempotencyKey.actor_id == user_id).delete(synchronize_session=False)
        cleanup.query(AuditEvent).filter(AuditEvent.actor_id == user_id).delete(synchronize_session=False)
        cleanup.execute(delete(Project).where(Project.id == project_id))
        cleanup.execute(delete(User).where(User.id == user_id))
        cleanup.commit()
        cleanup.close()


def test_correction_supersedes_event_and_recomputes_without_rewriting_history(db_pair):
    user_id, proposal_id, activity_id, _ = _pending(db_pair)
    db = db_pair()
    user = db.get(User, user_id)
    first = approve(proposal_id, _request("original-event"), user, db)
    db.commit()
    original_event_id = first["event_id"]

    original_proposal = db.get(Proposal, proposal_id)
    original_observation = db.get(Observation, original_proposal.observation_id)
    correction_observation = Observation(
        job_id=original_observation.job_id,
        ordinal=2,
        fields={"summary": "Correction: 1 spool installed."},
        field_evidence={},
    )
    db.add(correction_observation)
    db.flush()
    correction_proposal = Proposal(
        observation_id=correction_observation.id,
        revision=1,
        project_id=original_proposal.project_id,
        chosen_activity_id=activity_id,
        candidates=original_proposal.candidates,
        mapping_state="suggested",
        match_strength="review",
        review_state="pending",
        warnings=[],
        proposed_effects={
            "quantity": "1", "unit": "spool", "quantity_semantics": "delta",
            "event_type": "correction", "effective_date": "2026-01-02",
            "supersedes_event_id": original_event_id,
        },
    )
    db.add(correction_proposal)
    db.flush()
    correction_proposal_id = correction_proposal.id
    db.commit()
    assert db.scalar(select(Proposal.review_state).where(Proposal.id == proposal_id)) == "approved"

    correction = approve(
        correction_proposal_id,
        ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=1, idempotency_key="corrected-event"),
        user,
        db,
    )
    db.commit()
    events = db.scalars(select(ProgressEvent).where(ProgressEvent.activity_id == activity_id).order_by(ProgressEvent.approved_at)).all()
    by_id = {str(event.id): event for event in events}
    assert len(events) == 2
    assert by_id[original_event_id].approved_values["quantity"] == "2"
    assert by_id[correction["event_id"]].supersedes_event_id == by_id[original_event_id].id
    state = db.get(ActivityState, activity_id)
    assert state.revision == 2
    assert state.completed_quantity == Decimal("1.0000")
    assert db.scalar(select(Proposal.review_state).where(Proposal.id == correction_proposal_id)) == "approved"
    db.close()


def test_stale_second_approval_and_idempotent_retry(db_pair):
    user_id, proposal_id, _, _ = _pending(db_pair)
    first_db = db_pair()
    user = first_db.get(User, user_id)
    result = approve(proposal_id, _request("same-key"), user, first_db)
    first_db.commit()
    retry = approve(proposal_id, _request("same-key"), user, first_db)
    assert retry == result
    first_db.close()

    loser_db = db_pair()
    loser = loser_db.get(User, user_id)
    with pytest.raises(HTTPException) as exc:
        approve(proposal_id, _request("loser-key"), loser, loser_db)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "STALE_PROPOSAL"
    loser_db.rollback()
    assert loser_db.scalar(select(Proposal.review_state).where(Proposal.id == proposal_id)) == "approved"
    assert loser_db.scalar(select(ActivityState.revision).join(Activity, Activity.id == ActivityState.activity_id).join(Proposal, Proposal.chosen_activity_id == Activity.id).where(Proposal.id == proposal_id)) == 1
    loser_db.close()


def test_cross_project_selection_and_failed_transaction_leave_no_progress(db_pair, monkeypatch):
    user_id, proposal_id, activity_id, project_id = _pending(db_pair)
    db = db_pair()
    user = db.get(User, user_id)
    other = Project(name="other", timezone="UTC")
    version = ScheduleVersion(project=other, version_number=1, content_sha256=uuid4().hex, state="active")
    foreign = Activity(schedule_version=version, external_id="B-1", name="Foreign", wbs="1", discipline="mechanical", work_type="pipe_spool_erection", area="B", is_leaf=True, measurement_basis="quantity_ratio", planned_quantity=10, unit="spool", baseline_quantity=0)
    db.add_all([other, version, foreign])
    db.flush()
    proposal = db.get(Proposal, proposal_id)
    proposal.chosen_activity_id = foreign.id
    with pytest.raises(HTTPException) as exc:
        approve(proposal_id, _request("cross-project"), user, db)
    assert exc.value.status_code == 422
    db.rollback()

    db = db_pair()
    user = db.get(User, user_id)
    def fail(*_args, **_kwargs):
        raise RuntimeError("forced transaction failure")
    monkeypatch.setattr("app.api.endpoints.review.recompute_progress", fail)
    with pytest.raises(RuntimeError):
        approve(proposal_id, _request("failed"), user, db)
    db.rollback()
    assert db.scalar(select(ActivityState.revision).where(ActivityState.activity_id == activity_id)) == 0
    assert db.scalar(select(Proposal.review_state).where(Proposal.id == proposal_id)) == "pending"
    db.close()


def test_warning_requires_explicit_review_resolution_before_approval(db_pair):
    user_id, proposal_id, activity_id, _ = _pending(db_pair, warnings=["date is uncertain"])
    db = db_pair()
    user = db.get(User, user_id)
    with pytest.raises(HTTPException) as exc:
        approve(proposal_id, _request("warning-blocked"), user, db)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "UNRESOLVED_WARNINGS"
    db.rollback()

    original = db.get(Proposal, proposal_id)
    revised = revise(
        proposal_id,
        ReviewChange(
            expected_proposal_revision=1,
            chosen_activity_id=activity_id,
            field_changes={"resolve_warnings": ["date is uncertain"]},
            reason="Checked the dated report evidence with the source record.",
        ),
        user,
        db,
    )
    db.commit()
    assert original.review_state == "superseded"
    assert revised["warnings"] == []
    result = approve(
        revised["id"],
        ApprovalRequest(expected_proposal_revision=2, expected_activity_revision=0, idempotency_key="warning-resolved"),
        user,
        db,
    )
    assert result["state_revision"] == 1
    db.rollback()
    db.close()


def test_approval_rejects_activity_outside_the_job_pinned_schedule(db_pair):
    user_id, proposal_id, _, project_id = _pending(db_pair)
    db = db_pair()
    user = db.get(User, user_id)
    project = db.get(Project, project_id)
    newer = ScheduleVersion(project=project, version_number=2, content_sha256=uuid4().hex, state="active")
    newer_activity = Activity(
        schedule_version=newer,
        external_id="A-2",
        name="Different schedule activity",
        wbs="2",
        discipline="mechanical",
        work_type="pipe_spool_erection",
        area="A",
        is_leaf=True,
        measurement_basis="quantity_ratio",
        planned_quantity=10,
        unit="spool",
        baseline_quantity=0,
    )
    db.add(newer_activity)
    db.flush()
    db.get(Proposal, proposal_id).chosen_activity_id = newer_activity.id
    with pytest.raises(HTTPException) as exc:
        approve(proposal_id, _request("wrong-pinned-schedule"), user, db)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "ACTIVITY_OUTSIDE_PINNED_SCHEDULE"
    db.rollback()
    db.close()
