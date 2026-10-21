"""Real SQLite durable boundaries and local HTTP contracts; no provider calls."""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.conversation import runtime
from app.conversation.service import _exact_selection, add_turn, payload
from app.db.models import (Base, Activity, Conversation, ConversationTask, ConversationTaskCall,
                           Fragment, Project, Report, ScheduleVersion, User)
from app.agent.schedule_decision import candidate_for_activity
from app.llm.ollama import OllamaTransportError
from app.schemas.conversation import ConversationView
from backend.tests.unit.agent.test_agent_tools import Fixture


@pytest.fixture
def durable():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as db:
        user = User(username="offline", password_hash="unused", role="reviewer")
        project = Project(name="Runtime controlled")
        schedule = ScheduleVersion(project=project, version_number=1, content_sha256="a" * 64, state="active")
        db.add_all([user, project, schedule])
        db.flush()
        project.active_schedule_version_id = schedule.id
        conversation = Conversation(project_id=project.id, creator_id=user.id, schedule_version_id=schedule.id,
            revision=0, status="draft", draft={"orchestration_version": runtime.VERSION})
        db.add(conversation)
        db.flush()
        add_turn(db, conversation, "user", "Installed cable", user.id)
        task = runtime.enqueue(db, conversation)
        ids = SimpleNamespace(user=user.id, project=project.id, schedule=schedule.id,
                              conversation=conversation.id, task=task.id)
    yield sessions, ids
    engine.dispose()


def journal(sessions, task_id, token, factory=None, stop=None):
    with sessions() as db:
        config = deepcopy(db.get(ConversationTask, task_id).config)
    return runtime.CallJournal(sessions, task_id, token, config, model_factory=factory, should_stop=stop)


@pytest.mark.parametrize("mutation", ["foreign_schedule", "stale_active"])
def test_ret03_pinned_scope_filters_before_model_visible_retrieval(mutation):
    from app.agent.tools import AgentToolError
    fixture = Fixture()
    with fixture.context.session_factory() as db:
        foreign = ScheduleVersion(id=uuid4(), project_id=fixture.project_id, version_number=2,
                                  content_sha256="c" * 64, state="superseded")
        db.add(foreign)
        db.flush()
        db.add(Activity(id=uuid4(), schedule_version_id=foreign.id, external_id="FOREIGN", name="Cable",
                        wbs="1", discipline="electrical", work_type="cable_laying", is_leaf=True,
                        measurement_basis="unsupported"))
        if mutation == "stale_active":
            db.get(Project, fixture.project_id).active_schedule_version_id = foreign.id
        db.commit()
    seen = []
    def retrieve(*args):
        seen.extend(args[2])
        return [fixture.candidate]
    tools = fixture.tools(retrieval_service=retrieve)
    if mutation == "stale_active":
        with pytest.raises(AgentToolError, match="schedule changed"):
            fixture.load(tools)
        assert not seen and fixture.model_calls == 0
    else:
        scope = fixture.load(tools)
        tools.extract_observations(scope.fragment_ids, tools.report_metadata)
        tools.retrieve_candidates("obs-0001", fixture.observation, scope.schedule_version_id)
        assert len(seen) == 1
        assert str(seen[0].id) == str(fixture.activity_id)


@pytest.mark.parametrize("incompatible", [False, True])
def test_ret05_missing_schedule_units_do_not_invent_measurements_and_worktype_conflict_blocks_exact_match(incompatible):
    fixture = Fixture()
    candidate = candidate_for_activity(dict(id=str(fixture.activity_id), external_id="C-1", name="Cable",
        area="AREA-A", work_type="excavation" if incompatible else "cable_laying", is_leaf=True,
        unit=None, planned_quantity=None))
    observation = fixture.observation.model_copy(update={"area": "AREA-A"})
    observation.evidence[0].quote = "Installed cable in AREA-A"
    fragment_map = {observation.evidence[0].fragment_id: observation.evidence[0].quote}
    result = _exact_selection(observation, [candidate], fragment_map)
    assert candidate.unit is None and candidate.planned_quantity is None
    if incompatible:
        assert result is None
    else:
        assert result is not None and result.proposed_effects == {}
        assert result.review_state.value == "pending"


@pytest.mark.parametrize("kind", ["transport", "rate"])
def test_acct09_retry_keeps_pinned_adapter_identity_and_debits_prior_attempt(durable, monkeypatch, kind):
    sessions, ids = durable
    _, token = runtime.claim(sessions)
    from app.llm.hosted import HostedRateLimitError
    failure_type = OllamaTransportError if kind == "transport" else HostedRateLimitError
    constructed = []
    def adapter(settings, *, role, timeout):
        constructed.append((getattr(settings, f"{role}_provider"), getattr(settings, f"{role}_model"),
                            getattr(settings, f"{role}_key_slot"), timeout))
        return SimpleNamespace(chat=lambda **kw: (_ for _ in ()).throw(failure_type("offline")))
    monkeypatch.setattr(runtime, "create_adapter", adapter)
    with sessions.begin() as db:
        task = db.get(ConversationTask, ids.task)
        pinned = deepcopy(task.config)
        deadline = task.deadline_at
    call = journal(sessions, ids.task, token).model("extraction")
    with pytest.raises(failure_type):
        call(user="same request")
    with sessions.begin() as db:
        task = db.get(ConversationTask, ids.task)
        task.lease_expires_at = runtime.now() - timedelta(seconds=1)
    _, next_token = runtime.claim(sessions)
    with pytest.raises(failure_type):
        journal(sessions, ids.task, next_token).model("extraction")(user="same request")
    with sessions() as db:
        task = db.get(ConversationTask, ids.task)
        assert task.config == pinned and task.deadline_at == deadline
        assert task.model_calls == 2 and task.attempts == 2
    identity = pinned["roles"]["extraction"]
    assert [entry[:3] for entry in constructed] == [(identity["provider"], identity["model"], identity["key_slot"])] * 2


@pytest.mark.parametrize("saved", [False, True])
def test_rel05_restart_before_or_after_durable_response_preserves_call_reservations(durable, saved):
    sessions, ids = durable
    _, token = runtime.claim(sessions)
    calls = []
    def model(**kwargs):
        calls.append(kwargs)
        if not saved and len(calls) == 1:
            raise KeyboardInterrupt("controlled process death before response")
        return {"observations": []}
    first = journal(sessions, ids.task, token, lambda role: model)
    if saved:
        assert first.model("extraction")(user="request") == {"observations": []}
    else:
        with pytest.raises(KeyboardInterrupt):
            first.model("extraction")(user="request")
    with sessions.begin() as db:
        db.get(ConversationTask, ids.task).lease_expires_at = runtime.now() - timedelta(seconds=1)
    _, replacement = runtime.claim(sessions)
    second = journal(sessions, ids.task, replacement, lambda role: model)
    assert second.model("extraction")(user="request") == {"observations": []}
    with sessions() as db:
        task = db.get(ConversationTask, ids.task)
        assert task.model_calls == (1 if saved else 2)
        assert task.attempts == 2
        assert db.scalar(select(func.count()).select_from(ConversationTaskCall)) == 1
    assert len(calls) == (1 if saved else 2)


@pytest.mark.parametrize("clock_delta,code", [(121, "CONVERSATION_LEASE_LOST"),
                                               (1801, "CONVERSATION_LEASE_LOST")])
def test_rel07_clock_forward_expired_ownership_cannot_call_or_extend_deadline(durable, monkeypatch, clock_delta, code):
    sessions, ids = durable
    fixed = runtime.now()
    monkeypatch.setattr(runtime, "now", lambda: fixed)
    _, token = runtime.claim(sessions)
    with sessions() as db:
        deadline = db.get(ConversationTask, ids.task).deadline_at
    monkeypatch.setattr(runtime, "now", lambda: fixed + timedelta(seconds=clock_delta))
    def forbidden(role):
        raise AssertionError("expired ownership must fail before constructing provider")
    with pytest.raises(runtime.TaskStopped) as error:
        journal(sessions, ids.task, token, forbidden).model("extraction")(user="request")
    assert error.value.code == code
    with sessions() as db:
        task = db.get(ConversationTask, ids.task)
        assert task.deadline_at == deadline and task.model_calls == 0


def test_cap08_task_admission_limit_and_expired_deadline_stop_queue(durable, monkeypatch):
    sessions, ids = durable
    monkeypatch.setattr(runtime, "MAX_TASKS", 1)
    with sessions.begin() as db:
        conversation = db.get(Conversation, ids.conversation)
        revision = conversation.revision
        with pytest.raises(HTTPException) as error:
            runtime.enqueue(db, conversation)
        assert error.value.detail["code"] == "CONVERSATION_TASK_LIMIT"
        assert conversation.revision == revision
        db.get(ConversationTask, ids.task).deadline_at = runtime.now() - timedelta(seconds=1)
    assert runtime.claim(sessions) is None
    with sessions() as db:
        task = db.get(ConversationTask, ids.task)
        assert task.state == "failed" and task.error_code == "CONVERSATION_BUDGET_EXHAUSTED"
        assert task.model_calls == task.attempts == 0


@pytest.mark.parametrize("failure", [False, True])
def test_flow01_local_http_submission_persists_source_and_exposes_parse_queue_or_storage_error(durable, monkeypatch, failure):
    from app.api.endpoints import reports
    from app.api.dependencies import project_access, require_reviewer
    from app.db.session import get_session
    sessions, ids = durable
    app = FastAPI()
    app.include_router(reports.router, prefix="/api/v1")
    def database():
        with sessions.begin() as db:
            yield db
    def project():
        with sessions() as db:
            return db.get(Project, ids.project)
    def reviewer():
        with sessions() as db:
            return db.get(User, ids.user)
    app.dependency_overrides.update({get_session: database, project_access: project, require_reviewer: reviewer})
    def store(*args):
        if failure:
            raise OSError("offline storage failure")
    monkeypatch.setattr("app.ingest.reports._store_original", store)
    # Use local parsing in this test: no process launch or provider involved.
    monkeypatch.setattr("app.ingest.reports.parse_bytes", lambda *args: ([("p1", "Installed cable.")], [], "txt"))
    with TestClient(app) as client:
        response = client.post(f"/api/v1/projects/{ids.project}/reports", json={"text": "Installed cable."})
    if failure:
        assert response.status_code == 503 and response.json()["detail"]["code"] == "REPORT_STORAGE_FAILED"
        with sessions() as db:
            assert db.scalar(select(func.count()).select_from(Report)) == 0
    else:
        assert response.status_code == 202
        body = response.json()
        assert body["state"] == "queued" and body["stage"] == "parse"
        assert body["extracted_count"] == body["proposal_count"] == 0
        with sessions() as db:
            report = db.get(Report, UUID(body["report_id"]))
            assert report is not None
            assert db.scalar(select(Fragment.original_text).where(Fragment.report_id == report.id)) == "Installed cable."


@pytest.mark.parametrize("state,error", [("failed", "MODEL_REQUEST_FAILED"), ("queued", "MODEL_RATE_LIMITED")])
def test_flow03_failed_and_waiting_analysis_never_publish_success_events(durable, state, error):
    sessions, ids = durable
    with sessions.begin() as db:
        task = db.get(ConversationTask, ids.task)
        if state == "failed":
            runtime._finish(db, task, state=state, error=error)
        else:
            task.error_code = error
        conversation = db.get(Conversation, ids.conversation)
        result = payload(db, conversation)
        assert result["events"] == [] and result["proposal_ids"] == []
        assert result["status"] == ("draft" if state == "failed" else "analyzing")
        assert result["pending_question"] == ("retry" if state == "failed" else None)
        assert task.state == state and task.error_code == error


def test_flow15_persisted_worker_payload_roundtrips_strict_api_schema_and_rejects_drift(durable):
    from pydantic import ValidationError
    sessions, ids = durable
    with sessions() as db:
        raw = payload(db, db.get(Conversation, ids.conversation))
        wire = ConversationView.model_validate(raw).model_dump(mode="json")
    assert ConversationView.model_validate(wire).model_dump(mode="json") == wire
    app = FastAPI()
    @app.get("/saved-conversation", response_model=ConversationView)
    def saved_conversation():
        with sessions() as db:
            return payload(db, db.get(Conversation, ids.conversation))
    with TestClient(app) as client:
        response = client.get("/saved-conversation")
    assert response.status_code == 200 and response.json() == wire
    assert wire["turns"][0]["text"] == "Installed cable"
    with pytest.raises(ValidationError):
        ConversationView.model_validate({**wire, "approval_override": True})
    with pytest.raises(ValidationError):
        ConversationView.model_validate({**wire, "revision": "not-an-integer"})


def test_ret03_revoked_project_membership_denies_scope_before_any_retrieval(durable):
    from app.api.dependencies import project_access
    from app.db.models import ProjectMembership
    sessions, ids = durable
    with sessions.begin() as db:
        user = db.get(User, ids.user)
        with pytest.raises(HTTPException) as failure:
            project_access(ids.project, user, db)
        assert failure.value.status_code == 403
        membership = ProjectMembership(project_id=ids.project, user_id=ids.user)
        db.add(membership)
        db.flush()
        assert project_access(ids.project, user, db).id == ids.project
        db.delete(membership)
        db.flush()
        with pytest.raises(HTTPException) as revoked:
            project_access(ids.project, user, db)
        assert revoked.value.status_code == 403
        assert db.scalar(select(func.count()).select_from(ConversationTaskCall)) == 0


def test_rel07_backward_clock_does_not_reset_original_deadline_or_replaced_token(durable, monkeypatch):
    sessions, ids = durable
    fixed = runtime.now()
    monkeypatch.setattr(runtime, "now", lambda: fixed)
    _, token = runtime.claim(sessions)
    with sessions.begin() as db:
        task = db.get(ConversationTask, ids.task)
        original_deadline = task.deadline_at
        task.lease_token = "replacement-owner"
    monkeypatch.setattr(runtime, "now", lambda: fixed - timedelta(hours=2))
    with pytest.raises(runtime.TaskStopped) as failure:
        journal(sessions, ids.task, token).model("extraction")(user="request")
    assert failure.value.code == "CONVERSATION_LEASE_LOST"
    with sessions() as db:
        task = db.get(ConversationTask, ids.task)
        assert task.deadline_at == original_deadline and task.model_calls == 0
