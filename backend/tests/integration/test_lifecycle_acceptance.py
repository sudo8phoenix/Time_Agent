"""Quantity-free lifecycle approval at the real transaction boundary."""
from datetime import date
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.api.endpoints.review import ApprovalRequest, approve
from app.api.endpoints.progress import progress_view, approved_export
from app.db.models import Activity, ActivityState, Fragment, Job, Observation, ProgressEvent, Project, Proposal, User
from backend.tests.integration.test_review_concurrency import _pending
from sqlalchemy.orm import sessionmaker
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


def _lifecycle(db_pair, kind, day, *, time=None, ordinal=1):
    user_id, proposal_id, activity_id, project_id = _pending(db_pair)
    with db_pair() as db:
        proposal = db.get(Proposal, proposal_id)
        db.get(Activity, activity_id).measurement_basis = "unsupported"
        observation = db.get(Observation, proposal.observation_id)
        job = db.get(Job, observation.job_id)
        fragment = Fragment(report_id=job.report_id, ordinal=1, locator="Developer fixture line 1",
                            original_text=f"{kind} on {day} at {time or 'date only'}.",
                            normalised_text=f"{kind} on {day} at {time or 'date only'}.")
        db.add(fragment)
        db.flush()
        observation.fragment_id = fragment.id
        proposal.proposed_effects = {
            "event_type": kind, "scope": "whole_activity", "effective_date": day,
            "endpoint": {"local_date": day, "local_time": time,
                         "precision": "minute" if time else "date", "basis": "explicit",
                         "raw_expression": f"{day} {time or ''}".strip()},
            "evidence": [{"fields": ["endpoint"], "fragment_id": str(fragment.id),
                          "quote": fragment.original_text}],
            "source_version_id": str(job.schedule_version_id),
            "observation_id": str(observation.id),
        }
        db.commit()
    return user_id, proposal_id, activity_id, project_id


def _child_proposal(db_pair, proposal_id, user_id, *, kind=None):
    from uuid import uuid4
    with db_pair() as db:
        base = db.get(Proposal, proposal_id)
        observation = db.get(Observation, base.observation_id)
        job = db.get(Job, observation.job_id)
        child = Job(project_id=job.project_id, report_id=job.report_id,
                    schedule_version_id=job.schedule_version_id, parent_job_id=job.id,
                    reanalysis_key=f"test-{uuid4()}", reanalysis_actor_id=user_id,
                    reanalysis_reason="review the accepted source again", config_snapshot={"execution_mode": "legacy"})
        db.add(child)
        db.flush()
        child_observation = Observation(job_id=child.id, fragment_id=observation.fragment_id,
                                        ordinal=1, fields=observation.fields,
                                        field_evidence=observation.field_evidence)
        db.add(child_observation)
        db.flush()
        effects = dict(base.proposed_effects)
        if kind:
            effects["event_type"] = kind
        effects["observation_id"] = str(child_observation.id)
        proposal = Proposal(observation_id=child_observation.id, project_id=base.project_id,
                            chosen_activity_id=base.chosen_activity_id, mapping_state="suggested",
                            match_strength="review", review_state="pending", warnings=[],
                            proposed_effects=effects, base_activity_revision=base.base_activity_revision)
        db.add(proposal)
        db.commit()
        return user_id, proposal.id


def test_quantity_free_start_is_accepted_once_and_exported(db_pair):
    user_id, proposal_id, activity_id, project_id = _lifecycle(db_pair, "actual_start", "2026-01-02", time="08:30:00")
    with db_pair() as db:
        user = db.get(User, user_id)
        request = ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0, idempotency_key="start")
        result = approve(proposal_id, request, user, db)
        db.commit()
        assert approve(proposal_id, request, user, db) == result
        state = db.get(ActivityState, activity_id)
        assert state.actual_start == date(2026, 1, 2)
        assert state.actual_start_time.hour == 8
        assert state.actual_start_precision == "minute"
        assert state.lifecycle_status == "in_progress"
        assert state.completed_quantity == 0
        assert state.physical_percent is None
        assert db.scalar(select(ProgressEvent).where(ProgressEvent.id == result["event_id"])).effect_kind == "actual_start"
        view = progress_view(project=db.get(Project, project_id), _user=user, db=db)
        assert view["items"][0]["actual_start"] == "2026-01-02"
        exported = approved_export(project=db.get(Project, project_id), _user=user, db=db).body.decode()
        assert "endpoint_precision" in exported and "minute" in exported and "actual_start" in exported


def test_reanalysis_cannot_apply_same_source_effect_in_either_order(db_pair):
    from app.api.endpoints.review import ApprovalRequest, approve
    user_id, proposal_id, activity_id, _ = _lifecycle(db_pair, "actual_start", "2026-01-02")
    child_user, child_id = _child_proposal(db_pair, proposal_id, user_id)
    with db_pair() as db:
        approve(proposal_id, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0,
                                             idempotency_key="base-first"), db.get(User, user_id), db)
        db.commit()
        with pytest.raises(HTTPException) as duplicate:
            approve(child_id, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=1,
                                              idempotency_key="child-second"), db.get(User, child_user), db)
        assert duplicate.value.status_code == 409
        assert duplicate.value.detail["code"] == "SOURCE_WORK_ALREADY_ACCEPTED"
        db.rollback()

    user_id, proposal_id, activity_id, _ = _lifecycle(db_pair, "actual_start", "2026-01-02")
    child_user, child_id = _child_proposal(db_pair, proposal_id, user_id)
    with db_pair() as db:
        approve(child_id, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0,
                                          idempotency_key="child-first"), db.get(User, child_user), db)
        db.commit()
        with pytest.raises(HTTPException) as duplicate:
            approve(proposal_id, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=1,
                                                  idempotency_key="base-second"), db.get(User, user_id), db)
        assert duplicate.value.status_code == 409
        assert duplicate.value.detail["code"] == "SOURCE_WORK_ALREADY_ACCEPTED"


def test_same_source_can_accept_distinct_start_and_finish_effects(db_pair):
    user_id, proposal_id, activity_id, _ = _lifecycle(db_pair, "actual_start", "2026-01-02")
    from app.db.models import Job, Observation, Proposal
    with db_pair() as db:
        proposal = db.get(Proposal, proposal_id)
        observation = db.get(Observation, proposal.observation_id)
        job = db.get(Job, observation.job_id)
        effects = dict(proposal.proposed_effects)
        effects["event_type"] = "actual_finish"
        effects["endpoint"] = {**effects["endpoint"], "local_date": "2026-01-03"}
        effects["effective_date"] = "2026-01-03"
        fragment = db.get(Fragment, observation.fragment_id)
        fragment.original_text = "actual_start on 2026-01-02 and actual_finish on 2026-01-03."
        fragment.normalised_text = fragment.original_text
        start_effects = dict(proposal.proposed_effects)
        start_evidence = dict(start_effects["evidence"][0])
        start_evidence["quote"] = "actual_start on 2026-01-02"
        start_effects["evidence"] = [start_evidence]
        proposal.proposed_effects = start_effects
        finish_observation = Observation(job_id=job.id, fragment_id=observation.fragment_id,
                                         ordinal=2, fields=observation.fields,
                                         field_evidence=observation.field_evidence)
        db.add(finish_observation)
        db.flush()
        effects["observation_id"] = str(finish_observation.id)
        finish_evidence = dict(effects["evidence"][0])
        finish_evidence["quote"] = "actual_finish on 2026-01-03"
        effects["evidence"] = [finish_evidence]
        finish = Proposal(observation_id=finish_observation.id, project_id=proposal.project_id,
                          chosen_activity_id=proposal.chosen_activity_id, mapping_state="suggested",
                          match_strength="review", review_state="pending", warnings=[],
                          proposed_effects=effects, base_activity_revision=0)
        db.add(finish)
        db.commit()
        finish_id = finish.id
    with db_pair() as db:
        approve(proposal_id, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0,
                                             idempotency_key="same-source-start"), db.get(User, user_id), db)
        db.commit()
        result = approve(finish_id, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=1,
                                                     idempotency_key="same-source-finish"), db.get(User, user_id), db)
        db.commit()
        assert db.get(ActivityState, activity_id).actual_finish == date(2026, 1, 3)
        assert db.get(ProgressEvent, result["event_id"]).effect_kind == "actual_finish"


def test_lifecycle_rejects_invalid_evidence_without_mutation(db_pair):
    user_id, proposal_id, activity_id, _ = _lifecycle(db_pair, "actual_start", "2026-01-02")
    with db_pair() as db:
        proposal = db.get(Proposal, proposal_id)
        effects = dict(proposal.proposed_effects)
        effects["evidence"] = [{**effects["evidence"][0], "quote": "invented"}]
        proposal.proposed_effects = effects
        with pytest.raises(HTTPException) as exc:
            approve(proposal_id, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0,
                                                  idempotency_key="bad"), db.get(User, user_id), db)
        assert exc.value.detail["code"] == "INVALID_EVIDENCE"
        db.rollback()
        assert db.get(ActivityState, activity_id).revision == 0
        assert db.get(Proposal, proposal_id).review_state == "pending"


def test_evidenced_correction_and_retraction_preserve_history(db_pair):
    from app.api.endpoints.review import (LifecycleCorrectionRequest, LifecycleRetractionRequest,
                                          propose_lifecycle_correction, retract_lifecycle)
    user_id, proposal_id, activity_id, _ = _lifecycle(db_pair, "actual_start", "2026-01-02")
    with db_pair() as db:
        user = db.get(User, user_id)
        first = approve(proposal_id, ApprovalRequest(expected_proposal_revision=1,
                        expected_activity_revision=0, idempotency_key="first"), user, db)
        db.commit()
        original = db.get(ProgressEvent, first["event_id"])
        correction = propose_lifecycle_correction(original.id, LifecycleCorrectionRequest(
            expected_activity_revision=1,
            endpoint={"local_date": "2026-01-03", "local_time": None, "precision": "date",
                      "basis": "explicit", "raw_expression": "2026-01-03"},
            evidence=original.approved_values["evidence"], reason="Corrected transcribed date"), user, db)
        db.commit()
        assert correction["review_state"] == "pending"
        corrected = approve(correction["id"], ApprovalRequest(expected_proposal_revision=1,
                            expected_activity_revision=1, idempotency_key="correct"), user, db)
        db.commit()
        assert db.get(ActivityState, activity_id).actual_start == date(2026, 1, 3)
        assert db.get(ProgressEvent, first["event_id"]).approved_values["endpoint"]["local_date"] == "2026-01-02"
        retraction_request = LifecycleRetractionRequest(
            expected_activity_revision=2, idempotency_key="retract", reason="Source withdrawn")
        retracted = retract_lifecycle(corrected["event_id"], retraction_request, user, db)
        db.commit()
        assert retract_lifecycle(corrected["event_id"], retraction_request, user, db) == retracted
        assert db.get(ActivityState, activity_id).actual_start is None
        assert db.get(ActivityState, activity_id).lifecycle_status == "not_started"
        assert db.get(ProgressEvent, retracted["event_id"]).effect_kind == "lifecycle_retraction"


def test_known_finish_before_start_rejects_without_state_mutation(db_pair):
    from app.db.models import Activity
    user_id, proposal_id, activity_id, _ = _lifecycle(db_pair, "actual_start", "2026-01-02")
    with db_pair() as db:
        db.get(Activity, activity_id).actual_finish = date(2026, 1, 1)
        db.commit()
        with pytest.raises(HTTPException) as exc:
            approve(proposal_id, ApprovalRequest(expected_proposal_revision=1,
                    expected_activity_revision=0, idempotency_key="inverted"), db.get(User, user_id), db)
        assert exc.value.detail["code"] == "CONFLICTING_EFFECT"
        db.rollback()
        assert db.get(ActivityState, activity_id).revision == 0
        assert db.get(Proposal, proposal_id).review_state == "pending"


def test_stale_schedule_rejects_lifecycle_approval(db_pair):
    user_id, proposal_id, activity_id, project_id = _lifecycle(db_pair, "actual_start", "2026-01-02")
    with db_pair() as db:
        project = db.get(Project, project_id)
        project.active_schedule_version_id = None
        db.commit()
        with pytest.raises(HTTPException) as exc:
            approve(proposal_id, ApprovalRequest(expected_proposal_revision=1,
                    expected_activity_revision=0, idempotency_key="stale"), db.get(User, user_id), db)
        assert exc.value.detail["code"] == "STALE_SCHEDULE"
        db.rollback()
        assert db.get(ActivityState, activity_id).revision == 0


def test_concurrent_quantity_free_retry_commits_one_event(monkeypatch):
    from queue import Queue
    from threading import Event, Thread, current_thread
    from sqlalchemy import delete, update
    from app.db.models import AuditEvent, IdempotencyKey
    from app.api.endpoints import review as review_module
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    user_id, proposal_id, activity_id, project_id = _lifecycle(factory, "actual_start", "2026-01-02")
    entered, release = Event(), Event()
    outputs, errors = Queue(), Queue()
    original = review_module.project_lifecycle

    def pause_first(*args, **kwargs):
        if current_thread().name == "lifecycle-first":
            entered.set()
            assert release.wait(timeout=10)
        return original(*args, **kwargs)

    monkeypatch.setattr(review_module, "project_lifecycle", pause_first)

    def run():
        with factory() as db:
            try:
                result = approve(proposal_id, ApprovalRequest(expected_proposal_revision=1,
                                 expected_activity_revision=0, idempotency_key="same-lifecycle-key"),
                                 db.get(User, user_id), db)
                db.commit()
                outputs.put(result)
            except Exception as exc:
                db.rollback()
                errors.put(exc)

    first = Thread(target=run, name="lifecycle-first")
    second = Thread(target=run, name="lifecycle-second")
    try:
        first.start()
        assert entered.wait(timeout=10)
        second.start()
        release.set()
        first.join(timeout=10)
        second.join(timeout=10)
        assert errors.empty(), list(errors.queue)
        assert outputs.get_nowait() == outputs.get_nowait()
        with factory() as db:
            assert db.get(ActivityState, activity_id).revision == 1
            assert len(db.scalars(select(ProgressEvent).where(ProgressEvent.activity_id == activity_id)).all()) == 1
    finally:
        release.set()
        first.join(timeout=10)
        second.join(timeout=10)
        with factory() as db:
            db.execute(update(ActivityState).where(ActivityState.activity_id == activity_id).values(
                lifecycle_start_event_id=None, lifecycle_finish_event_id=None, lifecycle_source_version_id=None))
            db.query(ProgressEvent).filter(ProgressEvent.activity_id == activity_id).delete(synchronize_session=False)
            db.query(IdempotencyKey).filter(IdempotencyKey.actor_id == user_id).delete(synchronize_session=False)
            db.query(AuditEvent).filter(AuditEvent.actor_id == user_id).delete(synchronize_session=False)
            db.execute(delete(Project).where(Project.id == project_id))
            db.execute(delete(User).where(User.id == user_id))
            db.commit()


def test_date_only_finish_without_start_is_accepted_with_unknown_duration(db_pair):
    user_id, proposal_id, activity_id, _ = _lifecycle(db_pair, "actual_finish", "2026-01-03")
    with db_pair() as db:
        result = approve(proposal_id, ApprovalRequest(expected_proposal_revision=1,
                         expected_activity_revision=0, idempotency_key="finish-only"),
                         db.get(User, user_id), db)
        db.commit()
        state = db.get(ActivityState, activity_id)
        assert result["state_revision"] == 1
        assert state.actual_start is None
        assert state.actual_finish == date(2026, 1, 3)
        assert state.actual_finish_time is None
        assert state.actual_finish_precision == "date"
        assert state.lifecycle_status == "completed"
        assert state.physical_percent is None
