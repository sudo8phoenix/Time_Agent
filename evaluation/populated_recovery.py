"""Deterministic crash/restore rehearsal with populated operational journals.

Uses an injected synthetic model, never a live provider or approval operation.
Run seed against a fresh local rehearsal DB, use ops/backup and restore_verify,
then verify against the newly restored copy. Source databases are never reset.
"""
import argparse
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.conversation import runtime
from app.conversation.service import add_turn
from app.db.models import (Activity, ActivityState, Conversation, ConversationTask,
    ConversationTaskCall, HostedProviderAdmission, ProgressEvent, Project, ProjectMembership, ScheduleVersion, User)
from app.db.passwords import hash_password
from app.db.session import session_factory as sessions
from app.llm.capacity import DatabaseAdmission
from app.llm.hosted import HostedCapacityError
from app.settings import get_settings


def seed():
    # Reuse the exact deterministic fault-test response, explicitly not live AI.
    from backend.tests.integration.test_durable_conversations import extraction
    with sessions.begin() as db:
        if db.scalar(select(func.count()).select_from(Project)):
            raise ValueError("Seed requires an empty rehearsal database")
        user = User(username="recovery-"+uuid4().hex, password_hash=hash_password(uuid4().hex), role="viewer")
        project = Project(name="Synthetic populated recovery", timezone="Asia/Kolkata")
        db.add_all([user, project])
        db.flush()
        schedule = ScheduleVersion(project_id=project.id, version_number=1, content_sha256="0"*64, state="active")
        db.add(schedule)
        db.flush()
        project.active_schedule_version_id = schedule.id
        db.add(ProjectMembership(project_id=project.id, user_id=user.id))
        activity = Activity(schedule_version_id=schedule.id, external_id="EX-F01", name="Excavation F-01",
            wbs="1", discipline="civil", work_type="excavation", area="F-01", asset_tags="F-01",
            is_leaf=True, measurement_basis="unsupported", planned_quantity=None, unit=None)
        db.add(activity)
        db.flush()
        db.add(ActivityState(activity_id=activity.id, revision=0, completed_quantity=Decimal(0)))
        conversation = Conversation(project_id=project.id, creator_id=user.id, schedule_version_id=schedule.id,
            revision=0, status="draft", draft={"orchestration_version": runtime.VERSION, "report_date": "2026-10-09"})
        db.add(conversation)
        db.flush()
        add_turn(db, conversation, "user", "Started excavation at F-01 at 08:30", user.id)
        task = runtime.enqueue(db, conversation)
        task_id = task.id
    claimed, token = runtime.claim(sessions)
    assert claimed == task_id
    original = runtime.analyze
    class SimulatedProcessDeath(BaseException):
        pass
    def stop_after_saved_response(*args, **kwargs):
        original(*args, **kwargs)
        raise SimulatedProcessDeath()
    runtime.analyze = stop_after_saved_response
    try:
        runtime.process(sessions, task_id, token, model_factory=lambda role: extraction)
    except SimulatedProcessDeath:
        pass
    finally:
        runtime.analyze = original
    coordinator = DatabaseAdmission(sessions, intervals={})
    coordinator.acquire("groq", {"max_completion_tokens": 32}, 1)
    router, _ = coordinator.acquire("openrouter", {}, 1)
    coordinator.release("openrouter", router, status=429, headers={"Retry-After": "120"})
    with sessions() as db:
        task = db.get(ConversationTask, task_id)
        calls = list(db.scalars(select(ConversationTaskCall).where(ConversationTaskCall.task_id == task_id)))
        assert task.state == "running" and task.model_calls == 1
        assert len(calls) == 1 and calls[0].result is not None
        return {"scope": "deterministic synthetic process-death rehearsal; no live provider calls",
            "task_id": str(task_id), "state": task.state, "saved_model_calls": task.model_calls,
            "provider_rows": 2, "rollout_flags": False, "approved_events": 0}


def verify():
    settings = get_settings()
    assert not settings.agent_hierarchy_enabled and not settings.orchestrator_model_assisted
    with sessions.begin() as db:
        task = db.scalar(select(ConversationTask))
        assert task and task.state == "running" and task.model_calls == 1
        task_id, conversation_id = task.id, task.conversation_id
        # Advance only dead-process ownership on the restored copy. Original
        # backup/source state remains untouched and is independently hashed.
        task.lease_expires_at = runtime.now() - timedelta(seconds=1)
        admission = db.get(HostedProviderAdmission, "groq")
        assert admission.owner
        stale_owner = admission.owner
        admission.lease_expires_at = runtime.now() - timedelta(seconds=1)
        router = db.get(HostedProviderAdmission, "openrouter")
        assert router.state.get("cooldown", 0) > 0
    coordinator = DatabaseAdmission(sessions, intervals={})
    owner, _ = coordinator.acquire("groq", {}, 1)
    assert not coordinator.release("groq", stale_owner)
    assert coordinator.release("groq", owner)
    cooldown_preserved = False
    try:
        coordinator.acquire("openrouter", {}, .1)
    except HostedCapacityError:
        cooldown_preserved = True
    assert cooldown_preserved
    def no_model(role):
        raise AssertionError("Restored saved response must replay without a new model call")
    assert runtime.run_once(sessions, model_factory=no_model)
    with sessions() as db:
        task = db.get(ConversationTask, task_id)
        conversation = db.get(Conversation, conversation_id)
        assert task.state == "succeeded" and task.attempts == 2 and task.model_calls == 1
        assert len(conversation.draft["events"]) == 1 and conversation.job_id is None
        assert db.scalar(select(func.count()).select_from(ProgressEvent)) == 0
        return {"scope": "restored deterministic populated-state recovery", "task_state": task.state,
            "attempts": task.attempts, "model_calls": task.model_calls,
            "saved_response_replayed_without_inference": True, "stale_provider_release_fenced": True,
            "provider_cooldown_preserved": True, "rollout_flags": False, "approved_events": 0,
            "clock_fault_injection": "expired dead-process leases on restored copy only"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("seed", "verify"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = make_url(get_settings().database_url)
    prefix = "progress_rehearsal_recovery_" if args.mode == "seed" else "progress_restore_"
    if url.host not in {"127.0.0.1", "localhost"} or not (url.database or "").startswith(prefix):
        parser.error("Use a separate local rehearsal/restore database")
    if args.output.exists():
        parser.error("Output path must be new")
    result = seed() if args.mode == "seed" else verify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
