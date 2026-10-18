"""Durable conversation queue, journal replay, fences and approval boundaries."""
from datetime import timedelta
from decimal import Decimal
import re
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.conversation import runtime
from app.conversation.service import add_turn, confirm
from app.db.models import (Activity, ActivityState, Conversation, ConversationTask,
    ConversationTaskCall, ProgressEvent, Project, ProjectMembership,
    Proposal, ScheduleVersion, User)
from app.db.passwords import hash_password
from app.db.session import session_factory as sessions
from app.llm.ollama import OllamaTransportError
from app.main import app
from app.settings import get_settings


@pytest.fixture
def fixture(monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_hierarchy_enabled", True)
    password = "Durable-conversation-passphrase!"
    with sessions.begin() as db:
        user = User(username=f"durable-{uuid4().hex}", password_hash=hash_password(password), role="viewer")
        project = Project(name="Durable conversations", timezone="Asia/Kolkata")
        schedule = ScheduleVersion(project=project, version_number=1, content_sha256=uuid4().hex, state="active")
        db.add_all([user, project, schedule])
        db.flush()
        project.active_schedule_version_id = schedule.id
        db.add(ProjectMembership(project_id=project.id, user_id=user.id))
        activity = Activity(schedule_version=schedule, external_id="EX-F01", name="Excavation F-01",
            wbs="1", discipline="civil", work_type="excavation", area="F-01", asset_tags="F-01",
            is_leaf=True, measurement_basis="unsupported", planned_quantity=None, unit=None)
        db.add(activity)
        db.flush()
        db.add(ActivityState(activity=activity, revision=0, completed_quantity=Decimal(0)))
        conversation = Conversation(project_id=project.id, creator_id=user.id,
            schedule_version_id=schedule.id, revision=0, status="draft",
            draft={"orchestration_version": runtime.VERSION, "report_date": "2026-10-09"})
        db.add(conversation)
        db.flush()
        ids = {"project": project.id, "conversation": conversation.id,
               "user": user.id, "activity": activity.id, "schedule": schedule.id,
               "username": user.username, "password": password}
    yield ids
    with sessions.begin() as db:
        project = db.get(Project, ids["project"])
        if project:
            project.active_schedule_version_id = None
            db.flush()
            db.execute(delete(Conversation).where(Conversation.project_id == project.id))
            db.execute(delete(Project).where(Project.id == project.id))
        db.execute(delete(User).where(User.id == ids["user"]))


def enqueue(fixture, text="Started excavation at F-01 at 08:30"):
    with sessions.begin() as db:
        conversation = db.get(Conversation, fixture["conversation"])
        add_turn(db, conversation, "user", text, fixture["user"])
        task = runtime.enqueue(db, conversation)
        return task.id


def extraction(**kwargs):
    fragment = re.search(r"\[([a-f0-9-]{36}) \|", kwargs["user"]).group(1)
    quote = "Started excavation at F-01 at 08:30"
    return {"observations": [{
        "discipline": "civil", "work_type": "excavation", "event_type": "actual_start",
        "observed_status": "in_progress", "area": "F-01", "asset_tags": ["F-01"],
        "explicit_activity_id": None, "work_date": "2026-10-09", "date_basis": "report_context",
        "quantity": None, "quantity_kind": "none", "unit": None, "raw_unit": None,
        "reported_percent": None, "actual_start": None, "actual_finish": None, "blocker": None,
        "summary": quote, "evidence": [{"fields": ["event_type"], "fragment_id": fragment, "quote": quote}],
        "warnings": [], "lifecycle_effects": [{"kind": "actual_start", "scope": "whole_activity",
            "endpoint": {"local_date": "2026-10-09", "local_time": "08:30:00", "precision": "minute",
                         "basis": "report_context", "raw_expression": "at 08:30"},
            "evidence": [{"fields": ["endpoint"], "fragment_id": fragment, "quote": quote}]}]}]}


def no_model(_role):
    raise AssertionError("completed extraction must come from its checkpoint")


def test_http_turn_is_committed_before_model_then_confirmation_stays_pending(fixture, monkeypatch):
    def forbidden():
        raise AssertionError("HTTP must not construct a model")
    monkeypatch.setattr("app.conversation.service._model_call", forbidden)
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": fixture["username"], "password": fixture["password"]})
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        base = f"/api/v1/projects/{fixture['project']}/conversations"
        created = client.post(base, headers=headers).json()
        url = f"{base}/{created['id']}"
        response = client.post(url + "/messages", headers=headers, json={
            "text": "Started excavation at F-01 at 08:30", "report_date": "2026-10-09", "expected_revision": 0})
        assert response.status_code == 200, response.text
        queued = response.json()
        assert queued["status"] == "analyzing" and queued["turns"][0]["role"] == "user"
        with sessions() as db:
            assert db.scalar(select(ConversationTask).where(ConversationTask.conversation_id == created["id"])).state == "queued"
        blocked = client.post(url + "/confirm", headers=headers, json={"expected_revision": queued["revision"]})
        assert blocked.status_code == 409
        # Version pinning: a flag rollback must still process existing durable input.
        monkeypatch.setattr(get_settings(), "agent_hierarchy_enabled", False)
        assert runtime.run_once(sessions, model_factory=lambda role: extraction)
        ready = client.get(url).json()
        assert ready["status"] == "draft" and ready["pending_question"] is None
        assert len(ready["events"]) == 1
        edited = client.post(url + "/edit", headers=headers, json={
            "expected_revision": ready["revision"], "event_index": 0, "local_time": "08:35:00"})
        assert edited.status_code == 200, edited.text
        revision = edited.json()["revision"]
        confirmed = client.post(url + "/confirm", headers=headers, json={"expected_revision": revision})
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "pending_review"
        repeated = client.post(url + "/confirm", headers=headers, json={"expected_revision": revision})
        assert repeated.status_code == 409
        with sessions() as db:
            assert db.scalar(select(func.count()).select_from(Proposal).where(Proposal.project_id == fixture["project"])) == 1
            assert db.get(ActivityState, fixture["activity"]).actual_start is None
            assert db.scalar(select(func.count()).select_from(ProgressEvent).where(ProgressEvent.activity_id == fixture["activity"])) == 0


def test_clarification_releases_lease_and_next_turn_resumes(fixture):
    with sessions.begin() as db:
        c = db.get(Conversation, fixture["conversation"])
        c.draft = {"orchestration_version": runtime.VERSION}
    first = enqueue(fixture)
    assert runtime.run_once(sessions, model_factory=no_model)
    with sessions.begin() as db:
        c = db.get(Conversation, fixture["conversation"])
        assert c.status == "draft" and c.pending_question == "date"
        task = db.get(ConversationTask, first)
        assert task.state == "succeeded" and task.lease_token is None and task.model_calls == 0
        add_turn(db, c, "user", "9 October 2026", fixture["user"])
        runtime.enqueue(db, c)
    runtime.run_once(sessions, model_factory=lambda role: extraction)
    with sessions() as db:
        c = db.get(Conversation, fixture["conversation"])
        assert c.pending_question is None and len(c.draft["events"]) == 1


def test_restart_after_saved_response_reuses_call_and_conserves_budget(fixture, monkeypatch):
    task_id = enqueue(fixture)
    claimed_id, token = runtime.claim(sessions)
    assert claimed_id == task_id
    original = runtime.analyze
    class ProcessDeath(BaseException):
        pass
    def die_after_analysis(*args, **kwargs):
        original(*args, **kwargs)
        raise ProcessDeath()
    monkeypatch.setattr(runtime, "analyze", die_after_analysis)
    with pytest.raises(ProcessDeath):
        runtime.process(sessions, task_id, token, model_factory=lambda role: extraction)
    with sessions.begin() as db:
        task = db.get(ConversationTask, task_id)
        assert task.model_calls == 1
        assert db.scalar(select(ConversationTaskCall).where(ConversationTaskCall.task_id == task_id)).result is not None
        task.lease_expires_at = runtime.now() - timedelta(seconds=1)
    monkeypatch.setattr(runtime, "analyze", original)
    assert runtime.run_once(sessions, model_factory=no_model)
    # A stale owner cannot overwrite the completed task.
    runtime.process(sessions, task_id, token, model_factory=no_model)
    with sessions() as db:
        task = db.get(ConversationTask, task_id)
        assert task.state == "succeeded" and task.attempts == 2 and task.model_calls == 1
        c = db.get(Conversation, fixture["conversation"])
        assert len(c.draft["events"]) == 1 and c.job_id is None


def test_transport_retries_are_bounded_and_persist_reservations(fixture):
    task_id = enqueue(fixture)
    def unavailable(**kwargs):
        raise OllamaTransportError("outage")
    for attempt in range(1, runtime.MAX_ATTEMPTS + 1):
        assert runtime.run_once(sessions, model_factory=lambda role: unavailable)
        with sessions.begin() as db:
            task = db.get(ConversationTask, task_id)
            assert task.model_calls == attempt and task.attempts == attempt
            assert task.lease_token is None
            if attempt < runtime.MAX_ATTEMPTS:
                assert task.state == "queued"
                task.next_attempt_at = runtime.now() - timedelta(seconds=1)
            else:
                assert task.state == "failed"
                assert db.get(Conversation, fixture["conversation"]).pending_question == "retry"
    assert not runtime.run_once(sessions, model_factory=no_model)


@pytest.mark.parametrize("change", ["schedule", "cancel", "budget", "deadline"])
def test_fences_prevent_late_draft_or_proposal_publication(fixture, change):
    task_id = enqueue(fixture)
    _, token = runtime.claim(sessions)
    with sessions.begin() as db:
        c, task = db.get(Conversation, fixture["conversation"]), db.get(ConversationTask, task_id)
        if change == "schedule":
            db.get(Project, fixture["project"]).active_schedule_version_id = None
        elif change == "cancel":
            c.status = "cancelled"
            c.revision += 1
        elif change == "budget":
            task.model_calls = runtime.MAX_MODEL_CALLS
        else:
            task.deadline_at = runtime.now() - timedelta(seconds=1)
    runtime.process(sessions, task_id, token, model_factory=no_model)
    with sessions() as db:
        task, c = db.get(ConversationTask, task_id), db.get(Conversation, fixture["conversation"])
        assert task.state in {"stale", "cancelled", "failed"}
        assert not c.draft.get("events") and c.job_id is None
        assert c.status == ("cancelled" if change == "cancel" else "draft")


def test_confirmation_rechecks_schedule(fixture):
    enqueue(fixture)
    runtime.run_once(sessions, model_factory=lambda role: extraction)
    with sessions.begin() as db:
        db.get(Project, fixture["project"]).active_schedule_version_id = None
    with sessions.begin() as db:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as error:
            confirm(db, db.get(Conversation, fixture["conversation"]), db.get(User, fixture["user"]), None)
        assert error.value.detail["code"] == "STALE_SCHEDULE"
        assert db.get(Conversation, fixture["conversation"]).job_id is None


def test_sigkill_worker_recovers_completed_response_in_new_process(fixture):
    import os
    from pathlib import Path
    import signal
    import subprocess
    import sys
    task_id = enqueue(fixture)
    _, token = runtime.claim(sessions)
    root = Path(__file__).resolve().parents[3]
    source = '''
import os, signal, sys
sys.path.insert(0, "backend/tests/integration")
from uuid import UUID
from app.conversation import runtime
from app.db.session import session_factory
from test_durable_conversations import extraction
original = runtime.analyze
def crash(*args, **kwargs):
    original(*args, **kwargs)
    os.kill(os.getpid(), signal.SIGKILL)
runtime.analyze = crash
runtime.process(session_factory, UUID(sys.argv[1]), sys.argv[2], model_factory=lambda role: extraction)
'''
    child = subprocess.run([sys.executable, "-c", source, str(task_id), token], cwd=root,
        env={**os.environ, "PYTHONPATH": "backend"}, capture_output=True, timeout=30)
    assert child.returncode == -signal.SIGKILL, child.stderr.decode()
    with sessions.begin() as db:
        task = db.get(ConversationTask, task_id)
        assert task.state == "running" and task.model_calls == 1
        task.lease_expires_at = runtime.now() - timedelta(seconds=1)
    runtime.run_once(sessions, model_factory=no_model)
    with sessions() as db:
        assert db.get(ConversationTask, task_id).state == "succeeded"
        assert len(db.get(Conversation, fixture["conversation"]).draft["events"]) == 1


def test_changed_checkpoint_payload_fails_closed(fixture):
    task_id = enqueue(fixture)
    _, token = runtime.claim(sessions)
    with sessions() as db:
        config = db.get(ConversationTask, task_id).config
    first = runtime.CallJournal(sessions, task_id, token, config, model_factory=lambda role: lambda **kw: {"ok": True})
    assert first.model("extraction")(system="s", user="one", schema={}) == {"ok": True}
    second = runtime.CallJournal(sessions, task_id, token, config, model_factory=no_model)
    with pytest.raises(runtime.TaskStopped) as error:
        second.model("extraction")(system="s", user="two", schema={})
    assert error.value.code == "CONVERSATION_CHECKPOINT_CONFLICT"
    with sessions.begin() as db:
        task = db.get(ConversationTask, task_id)
        assert task.model_calls == 1
        # Leave no running work for other tests.
        runtime._finish(db, task, state="failed", error=error.value.code)


def test_retry_http_keeps_revision_monotonic_and_original_budget(fixture):
    from app.llm.ollama import OllamaResponseError
    task_id = enqueue(fixture)
    def unavailable(**kwargs):
        raise OllamaResponseError("invalid response")
    runtime.run_once(sessions, model_factory=lambda role: unavailable)
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": fixture["username"], "password": fixture["password"]})
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        url = f"/api/v1/projects/{fixture['project']}/conversations/{fixture['conversation']}"
        failed = client.get(url).json()
        response = client.post(url + "/retry", headers=headers, json={"expected_revision": failed["revision"]})
        assert response.status_code == 200, response.text
        assert response.json()["revision"] > failed["revision"]
        runtime.run_once(sessions, model_factory=lambda role: extraction)
        ready = client.get(url).json()
        assert ready["status"] == "draft" and ready["pending_question"] is None
        with sessions() as db:
            task = db.get(ConversationTask, task_id)
            assert task.attempts == 2 and task.model_calls == 2 and task.state == "succeeded"
            assert db.scalar(select(func.count()).select_from(ConversationTask).where(ConversationTask.conversation_id == fixture["conversation"])) == 1


def test_schedule_change_during_inference_discards_response(fixture):
    task_id = enqueue(fixture)
    def change_schedule(**kwargs):
        with sessions.begin() as db:
            db.get(Project, fixture["project"]).active_schedule_version_id = None
        return extraction(**kwargs)
    runtime.run_once(sessions, model_factory=lambda role: change_schedule)
    with sessions() as db:
        task = db.get(ConversationTask, task_id)
        assert task.state == "stale" and task.model_calls == 1
        saved = db.scalar(select(ConversationTaskCall).where(ConversationTaskCall.task_id == task_id))
        assert saved.result is None
        assert not db.get(Conversation, fixture["conversation"]).draft.get("events")


def test_heartbeat_renews_lease_while_inference_is_blocked(fixture, monkeypatch):
    from threading import Event, Thread
    monkeypatch.setattr(runtime, "LEASE_SECONDS", 0.6)
    enqueue(fixture)
    entered, release = Event(), Event()
    def slow(**kwargs):
        entered.set()
        assert release.wait(5)
        return extraction(**kwargs)
    worker = Thread(target=lambda: runtime.run_once(sessions, model_factory=lambda role: slow))
    worker.start()
    try:
        assert entered.wait(5)
        # Wait on the heartbeat's observable DB update, bounded to a few seconds.
        import time
        with sessions() as db:
            first = db.scalar(select(ConversationTask).where(ConversationTask.conversation_id == fixture["conversation"]))
            expiry = first.lease_expires_at
        end = time.monotonic() + 3
        renewed = False
        while time.monotonic() < end:
            with sessions() as db:
                task = db.scalar(select(ConversationTask).where(ConversationTask.conversation_id == fixture["conversation"]))
                if task.lease_expires_at > expiry:
                    renewed = True
                    break
            time.sleep(0.05)
        assert renewed
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    with sessions() as db:
        c = db.get(Conversation, fixture["conversation"])
        assert c.status == "draft" and len(c.draft["events"]) == 1


def test_selection_specialist_and_extraction_checkpoints_resume_together(fixture, monkeypatch):
    with sessions.begin() as db:
        db.get(Activity, fixture["activity"]).area = None
    task_id = enqueue(fixture)
    roles = []
    def factory(role):
        roles.append(role)
        if role == "extraction":
            return extraction
        def selection(**kwargs):
            if "Choose plausible schedule activities" in kwargs["system"]:
                return {"candidate_ids": [str(fixture["activity"])]}
            evidence = kwargs["user"]["observation"]["evidence"]
            return {"candidate_id": str(fixture["activity"]), "mapping_state": "suggested",
                "evidence_fragment_ids": [evidence[0]["fragment_id"]], "reason_codes": ["ASSET_MATCH"],
                "explanation": "Matches quoted work.", "missing_information": []}
        return selection
    original = runtime.analyze
    class Death(BaseException):
        pass
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise Death()
    monkeypatch.setattr(runtime, "analyze", crash)
    _, token = runtime.claim(sessions)
    with pytest.raises(Death):
        runtime.process(sessions, task_id, token, model_factory=factory)
    assert roles == ["extraction", "selection", "selection"]
    with sessions.begin() as db:
        task = db.get(ConversationTask, task_id)
        assert task.model_calls == 3
        task.lease_expires_at = runtime.now() - timedelta(seconds=1)
    monkeypatch.setattr(runtime, "analyze", original)
    runtime.run_once(sessions, model_factory=no_model)
    with sessions() as db:
        task = db.get(ConversationTask, task_id)
        assert task.state == "succeeded" and task.model_calls == 3
        c = db.get(Conversation, fixture["conversation"])
        assert c.draft["events"][0]["activity_id"] == str(fixture["activity"])


def test_checkpoint_storage_budget_fails_closed(fixture, monkeypatch):
    monkeypatch.setattr(runtime, "MAX_TASK_CHECKPOINT_BYTES", 1)
    task_id = enqueue(fixture)
    runtime.run_once(sessions, model_factory=lambda role: extraction)
    with sessions() as db:
        task = db.get(ConversationTask, task_id)
        assert task.state == "failed"
        assert task.error_code == "CONVERSATION_CHECKPOINT_TOO_LARGE"
        assert task.model_calls == 1
        assert not db.get(Conversation, fixture["conversation"]).draft.get("events")


def test_conversation_budget_is_shared_across_new_turns(fixture, monkeypatch):
    monkeypatch.setattr(runtime, "MAX_CONVERSATION_CALLS", 1)
    first = enqueue(fixture)
    runtime.run_once(sessions, model_factory=lambda role: extraction)
    second = enqueue(fixture, "Please check that event again")
    runtime.run_once(sessions, model_factory=no_model)
    with sessions() as db:
        assert db.get(ConversationTask, first).model_calls == 1
        task = db.get(ConversationTask, second)
        assert task.state == "failed" and task.error_code == "CONVERSATION_BUDGET_EXHAUSTED"
        assert task.model_calls == 0


@pytest.mark.parametrize("quota_exhausted", [False, True])
def test_hosted_provider_cooldown_is_durable_and_daily_quota_does_not_auto_retry(fixture, quota_exhausted):
    from app.llm.hosted import HostedQuotaError, HostedRateLimitError
    task_id = enqueue(fixture)
    before = runtime.now()
    def limited(**kwargs):
        if quota_exhausted:
            raise HostedQuotaError("quota exhausted")
        raise HostedRateLimitError("limited", retry_after_seconds=180)
    runtime.run_once(sessions, model_factory=lambda role: limited)
    with sessions() as db:
        task = db.get(ConversationTask, task_id)
        assert task.model_calls == 1 and task.attempts == 1
        assert task.lease_token is None
        if quota_exhausted:
            assert task.state == "failed" and task.error_code == "MODEL_QUOTA_EXHAUSTED"
        else:
            assert task.state == "queued" and task.error_code == "MODEL_RATE_LIMITED"
            assert runtime.utc(task.next_attempt_at) >= before + timedelta(seconds=180)
        assert not db.get(Conversation, fixture["conversation"]).draft.get("events")


def test_extreme_provider_cooldown_is_bounded_by_original_task_deadline(fixture):
    from app.llm.hosted import HostedRateLimitError
    task_id = enqueue(fixture)
    def limited(**kwargs):
        raise HostedRateLimitError("limited", retry_after_seconds=1e30)
    runtime.run_once(sessions, model_factory=lambda role: limited)
    with sessions() as db:
        task = db.get(ConversationTask, task_id)
        assert task.state == "queued" and task.lease_token is None
        assert task.next_attempt_at == task.deadline_at


@pytest.mark.parametrize("legacy", [False, True, "v10", "v11"])
def test_extraction_prompt_is_pinned_across_restart(fixture, monkeypatch, legacy):
    from app.prompts.extraction_v1 import PROMPT_VERSION, LEGACY_PROMPT_VERSION, V10_PROMPT_VERSION, V11_PROMPT_VERSION, get_extraction_prompt
    task_id = enqueue(fixture)
    with sessions.begin() as db:
        task = db.get(ConversationTask, task_id)
        assert task.config["extraction_prompt_version"] == PROMPT_VERSION
        if legacy in ("v10", "v11"):
            task.config = {**task.config, "extraction_prompt_version":
                V10_PROMPT_VERSION if legacy == "v10" else V11_PROMPT_VERSION}
        elif legacy:
            config = dict(task.config)
            config.pop("extraction_prompt_version")
            task.config = config
    _, token = runtime.claim(sessions)
    original = runtime.analyze
    expected = get_extraction_prompt(V11_PROMPT_VERSION if legacy == "v11" else V10_PROMPT_VERSION if legacy == "v10" else LEGACY_PROMPT_VERSION if legacy else PROMPT_VERSION)[1]
    calls = []
    def pinned_model(**kwargs):
        assert kwargs["system"] == expected
        calls.append(1)
        return extraction(**kwargs)
    class ProcessDeath(BaseException):
        pass
    def die(*args, **kwargs):
        original(*args, **kwargs)
        raise ProcessDeath()
    monkeypatch.setattr(runtime, "analyze", die)
    with pytest.raises(ProcessDeath):
        runtime.process(sessions, task_id, token, model_factory=lambda role: pinned_model)
    with sessions.begin() as db:
        task = db.get(ConversationTask, task_id)
        task.lease_expires_at = runtime.now() - timedelta(seconds=1)
    monkeypatch.setattr(runtime, "analyze", original)
    monkeypatch.setattr(runtime, "PROMPT_VERSION", "future-default-must-not-affect-replay")
    assert runtime.run_once(sessions, model_factory=no_model)
    with sessions() as db:
        task = db.get(ConversationTask, task_id)
        assert task.state == "succeeded" and task.model_calls == 1 and task.attempts == 2
    assert calls == [1]
