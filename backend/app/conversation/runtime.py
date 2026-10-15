"""Versioned, lease-owned conversation tasks with private model-call checkpoints.

No inference runs in an HTTP transaction. Reservations commit before each call;
completed responses are replayed only for the same ordinal, role and fingerprint.
A crash after inference but before saving its response may repeat that call, and
still consumes the original reservation. Domain analysis validates cached output
again. This module has no approval or ledger capability.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import threading
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from ..db.models import Conversation, ConversationTask, ConversationTaskCall, Project
from ..llm.ollama import LLMResult, OllamaResponseError, OllamaTransportError
from ..llm.provider import create_adapter, role_provider_config
from ..llm.hosted import HostedCapacityError, HostedRateLimitError, HostedQuotaError
from ..settings import get_settings
from ..prompts.extraction_v1 import PROMPT_VERSION, LEGACY_PROMPT_VERSION
from .service import QUESTIONS, add_turn, analyze, turns

VERSION = "conversation-analysis-v1"
LEASE_SECONDS = 120
MAX_ATTEMPTS = 3
MAX_MODEL_CALLS = 806
MAX_CONVERSATION_CALLS = 1600
MAX_TURNS = 100
MAX_TASKS = 200
MAX_SECONDS = 1800
MAX_CHECKPOINT_BYTES = 1024 * 1024
MAX_TASK_CHECKPOINT_BYTES = 16 * 1024 * 1024


def now():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def durable(conversation):
    return (conversation.draft or {}).get("orchestration_version") == VERSION


def input_fingerprint(db, conversation):
    return fingerprint({
        "conversation": str(conversation.id), "project": str(conversation.project_id),
        "schedule": str(conversation.schedule_version_id),
        "report_date": (conversation.draft or {}).get("report_date"),
        "pending_question": conversation.pending_question,
        "turns": [(str(t.id), t.ordinal, t.text) for t in turns(db, conversation) if t.role == "user"],
    })


def enqueue(db, conversation):
    """Called under the API's conversation row lock; committed with the user turn."""
    history = [t for t in turns(db, conversation) if t.role == "user"]
    if len(history) > MAX_TURNS:
        raise HTTPException(409, detail={"code": "CONVERSATION_TURN_LIMIT"})
    task_count = db.scalar(select(func.count()).select_from(ConversationTask).where(
        ConversationTask.conversation_id == conversation.id))
    if task_count >= MAX_TASKS:
        raise HTTPException(409, detail={"code": "CONVERSATION_TASK_LIMIT"})
    settings = get_settings()
    config = {"extraction_prompt_version": PROMPT_VERSION, "timeout": settings.conversation_model_timeout_seconds, "roles": {}, "pending_question": conversation.pending_question}
    for role, assignment in role_provider_config(settings).items():
        if role == "orchestrator":
            continue
        provider = assignment.provider or settings.llm_provider
        model = assignment.model or getattr(settings, f"{provider}_model")
        config["roles"][role] = {"provider": provider, "model": model,
                                  "key_slot": assignment.key_slot}
    conversation.revision += 1
    conversation.status = "analyzing"
    draft = dict(conversation.draft or {})
    draft.pop("events", None)
    draft.pop("hierarchy_waiting", None)
    conversation.draft = draft
    timestamp = now()
    config["resume_revision"] = conversation.revision
    task = ConversationTask(conversation_id=conversation.id,
        schedule_version_id=conversation.schedule_version_id,
        input_revision=conversation.revision, version=VERSION,
        input_fingerprint=input_fingerprint(db, conversation), config=config,
        state="queued", attempts=0, model_calls=0, next_attempt_at=timestamp,
        deadline_at=timestamp + timedelta(seconds=MAX_SECONDS))
    db.add(task)
    db.flush()
    return task


def retry_analysis(db, conversation):
    """Retry the same failed task without resetting counters or regressing revisions."""
    task = db.scalar(select(ConversationTask).where(
        ConversationTask.conversation_id == conversation.id)
        .order_by(ConversationTask.input_revision.desc()).limit(1))
    if task and task.state == "failed":
        if (task.attempts >= MAX_ATTEMPTS or task.model_calls >= MAX_MODEL_CALLS or
                utc(task.deadline_at) <= now() or task.error_code in {
                    "CONVERSATION_BUDGET_EXHAUSTED", "CONVERSATION_CHECKPOINT_CONFLICT",
                    "CONVERSATION_CHECKPOINT_TOO_LARGE", "CONVERSATION_INPUT_CHANGED"}):
            raise HTTPException(409, detail={"code": "CONVERSATION_RETRY_EXHAUSTED"})
        conversation.revision += 1
        task.config = {**task.config, "resume_revision": conversation.revision}
        conversation.status = "analyzing"
        conversation.pending_question = task.config.get("pending_question")
        task.state, task.error_code, task.next_attempt_at = "queued", None, now()
        db.flush()
        return task
    return enqueue(db, conversation)


class TaskStopped(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _owned(db, task_id, token):
    task = db.scalar(select(ConversationTask).where(ConversationTask.id == task_id).with_for_update())
    if (not task or task.state != "running" or task.lease_token != token or
            not task.lease_expires_at or utc(task.lease_expires_at) <= now()):
        raise TaskStopped("CONVERSATION_LEASE_LOST")
    if utc(task.deadline_at) <= now():
        raise TaskStopped("CONVERSATION_BUDGET_EXHAUSTED")
    conversation = db.get(Conversation, task.conversation_id)
    if not conversation or conversation.status != "analyzing":
        raise TaskStopped("CONVERSATION_CANCELLED")
    if (task.version != VERSION or not durable(conversation) or
            conversation.revision != task.config.get("resume_revision", task.input_revision) or conversation.job_id or
            conversation.schedule_version_id != task.schedule_version_id or
            input_fingerprint(db, conversation) != task.input_fingerprint):
        raise TaskStopped("CONVERSATION_INPUT_CHANGED")
    project = db.get(Project, conversation.project_id)
    if not project or project.active_schedule_version_id != task.schedule_version_id:
        raise TaskStopped("STALE_SCHEDULE")
    return task


def _finish(db, task, *, state, error=None, draft=None, question=None):
    """Publish under task and conversation locks, fencing late/replaced workers."""
    conversation = db.scalar(select(Conversation).where(
        Conversation.id == task.conversation_id).with_for_update().execution_options(populate_existing=True))
    task.state, task.error_code = state, error
    task.lease_token = task.lease_expires_at = None
    if (not conversation or conversation.status != "analyzing" or
            conversation.revision != task.config.get("resume_revision", task.input_revision)):
        task.state, task.error_code = "cancelled", "CONVERSATION_INPUT_CHANGED"
        return
    conversation.status = "draft"
    conversation.revision += 1
    if state == "succeeded":
        conversation.draft, conversation.pending_question = draft, question
    else:
        clean = dict(conversation.draft or {})
        clean.pop("events", None)
        clean.pop("hierarchy_waiting", None)
        if state == "stale":
            clean["stale_schedule"] = True
        conversation.draft, conversation.pending_question = clean, "retry"
    if conversation.pending_question:
        add_turn(db, conversation, "assistant", QUESTIONS[conversation.pending_question])


def claim(sessions):
    """SKIP LOCKED permits multiple workers without duplicate task ownership."""
    with sessions.begin() as db:
        timestamp = now()
        tasks = db.scalars(select(ConversationTask).where(or_(
            (ConversationTask.state == "queued") & (ConversationTask.next_attempt_at <= timestamp),
            (ConversationTask.state == "running") & (ConversationTask.lease_expires_at <= timestamp)))
            .order_by(ConversationTask.created_at, ConversationTask.id)
            .limit(20).with_for_update(skip_locked=True)).all()
        for task in tasks:
            conversation = db.get(Conversation, task.conversation_id)
            if not conversation or conversation.status != "analyzing":
                task.state, task.error_code = "cancelled", "CONVERSATION_CANCELLED"
                task.lease_token = task.lease_expires_at = None
                continue
            if task.attempts >= MAX_ATTEMPTS or utc(task.deadline_at) <= timestamp:
                _finish(db, task, state="failed", error="CONVERSATION_BUDGET_EXHAUSTED")
                continue
            task.state, task.lease_token = "running", uuid4().hex
            task.attempts += 1
            task.lease_expires_at = timestamp + timedelta(seconds=LEASE_SECONDS)
            return task.id, task.lease_token
    return None


class CallJournal:
    def __init__(self, sessions, task_id, token, config, *, model_factory=None, should_stop=None):
        self.sessions, self.task_id, self.token = sessions, task_id, token
        self.config, self.model_factory = config, model_factory
        self.should_stop = should_stop or (lambda: False)
        self.ordinal = 0

    def check_stop(self):
        if self.should_stop():
            raise TaskStopped("CONVERSATION_SHUTDOWN")

    def model(self, role):
        def call(**kwargs):
            self.check_stop()
            ordinal = self.ordinal
            self.ordinal += 1
            digest = fingerprint({"role": role, "request": kwargs})
            with self.sessions.begin() as db:
                task = _owned(db, self.task_id, self.token)
                saved = db.scalar(select(ConversationTaskCall).where(
                    ConversationTaskCall.task_id == task.id, ConversationTaskCall.ordinal == ordinal))
                if saved and (saved.role != role or saved.input_fingerprint != digest):
                    raise TaskStopped("CONVERSATION_CHECKPOINT_CONFLICT")
                if saved and saved.result is not None:
                    return LLMResult(**saved.result) if "value" in saved.result else saved.result["plain"]
                # The conversation lock serializes its aggregate budget reservations.
                db.scalar(select(Conversation).where(Conversation.id == task.conversation_id).with_for_update())
                used = sum(db.scalars(select(ConversationTask.model_calls).where(
                    ConversationTask.conversation_id == task.conversation_id)))
                if task.model_calls >= MAX_MODEL_CALLS or used >= MAX_CONVERSATION_CALLS:
                    raise TaskStopped("CONVERSATION_BUDGET_EXHAUSTED")
                task.model_calls += 1
                if not saved:
                    db.add(ConversationTaskCall(task_id=task.id, ordinal=ordinal, role=role,
                        input_fingerprint=digest, result=None))
                remaining = (utc(task.deadline_at) - now()).total_seconds()
            settings = get_settings()
            assignment = self.config["roles"][role]
            # Only non-secret role assignments are pinned. Credentials stay ephemeral.
            settings = settings.model_copy(update={
                f"{role}_provider": assignment["provider"],
                f"{role}_model": assignment["model"],
                f"{role}_key_slot": assignment["key_slot"],
            })
            timeout = max(0.1, min(self.config["timeout"], remaining))
            model = (self.model_factory(role) if self.model_factory else
                     create_adapter(settings, role=role, timeout=timeout).chat)
            response = model(**kwargs)
            self.check_stop()
            record = asdict(response) if isinstance(response, LLMResult) else {"plain": response}
            record_bytes = len(json.dumps(record, allow_nan=False).encode())
            if record_bytes > MAX_CHECKPOINT_BYTES:
                raise TaskStopped("CONVERSATION_CHECKPOINT_TOO_LARGE")
            with self.sessions.begin() as db:
                task = _owned(db, self.task_id, self.token)
                checkpoint_bytes = task.config.get("checkpoint_bytes", 0) + record_bytes
                if checkpoint_bytes > MAX_TASK_CHECKPOINT_BYTES:
                    raise TaskStopped("CONVERSATION_CHECKPOINT_TOO_LARGE")
                task.config = {**task.config, "checkpoint_bytes": checkpoint_bytes}
                saved = db.scalar(select(ConversationTaskCall).where(
                    ConversationTaskCall.task_id == self.task_id, ConversationTaskCall.ordinal == ordinal))
                saved.result = record
            return response
        return call


def process(sessions, task_id, token, *, model_factory=None, should_stop=None):
    """Execute a claimed task. Completed calls survive rollback or process death."""
    try:
        with sessions.begin() as db:
            task = _owned(db, task_id, token)
            config, conversation_id = deepcopy(task.config), task.conversation_id
        journal = CallJournal(sessions, task_id, token, config,
                              model_factory=model_factory, should_stop=should_stop)
        journal.check_stop()
        # This read session never flushes speculative draft changes. Inference and
        # checkpoints use no conversation row lock held by the analysis session.
        with sessions() as db:
            conversation = db.get(Conversation, conversation_id)
            with db.no_autoflush:
                analyze(db, conversation, model_call=journal.model("extraction"),
                        selection_call_override=journal.model("selection"), hierarchy_enabled=True,
                        extraction_prompt_version=config.get("extraction_prompt_version", LEGACY_PROMPT_VERSION))
            draft, question = deepcopy(conversation.draft), conversation.pending_question
            project_id = conversation.project_id
            db.rollback()
        journal.check_stop()
        with sessions.begin() as db:
            task = _owned(db, task_id, token)
            # Fence schedule activation during publication.
            project = db.scalar(select(Project).where(Project.id == project_id).with_for_update().execution_options(populate_existing=True))
            if project.active_schedule_version_id != task.schedule_version_id:
                raise TaskStopped("STALE_SCHEDULE")
            _finish(db, task, state="succeeded", draft=draft, question=question)
    except Exception as error:
        code = (error.code if isinstance(error, TaskStopped) else
                error.code if isinstance(error, (HostedCapacityError, HostedRateLimitError, HostedQuotaError)) else
                "MODEL_REQUEST_FAILED" if isinstance(error, OllamaTransportError) else
                "MODEL_RESPONSE_INVALID" if isinstance(error, OllamaResponseError) else
                "CONVERSATION_ANALYSIS_FAILED")
        with sessions.begin() as db:
            task = db.scalar(select(ConversationTask).where(ConversationTask.id == task_id).with_for_update())
            if not task or task.state != "running" or task.lease_token != token:
                return
            # An expired worker cannot publish, even if nobody reclaimed it yet.
            if utc(task.lease_expires_at) <= now():
                return
            if code == "CONVERSATION_SHUTDOWN" or (
                    isinstance(error, OllamaTransportError) and task.attempts < MAX_ATTEMPTS and
                    utc(task.deadline_at) > now()):
                task.state = "queued"
                timestamp = now()
                delay = (0 if code == "CONVERSATION_SHUTDOWN" else
                         max(2 ** task.attempts, getattr(error, "retry_after_seconds", 0)))
                # Never overflow timestamps or reset the original deadline for
                # a provider cooldown extending beyond this task's lifetime.
                delay = min(delay, max(0, (utc(task.deadline_at) - timestamp).total_seconds()))
                task.next_attempt_at = timestamp + timedelta(seconds=delay)
                task.lease_token = task.lease_expires_at = None
                task.error_code = code
            else:
                state = "stale" if code == "STALE_SCHEDULE" else "cancelled" if code == "CONVERSATION_CANCELLED" else "failed"
                _finish(db, task, state=state, error=code)


def run_once(sessions, *, model_factory=None, should_stop=None):
    if should_stop and should_stop():
        return False
    claimed = claim(sessions)
    if not claimed:
        return False
    task_id, token = claimed
    stopped = threading.Event()
    lost = threading.Event()

    def renew():
        while not stopped.wait(LEASE_SECONDS / 3):
            try:
                with sessions.begin() as db:
                    task = _owned(db, task_id, token)
                    task.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
            except Exception:
                lost.set()
                return

    thread = threading.Thread(target=renew, name="conversation-heartbeat", daemon=True)
    thread.start()
    try:
        process(sessions, task_id, token, model_factory=model_factory,
                should_stop=lambda: lost.is_set() or bool(should_stop and should_stop()))
    finally:
        stopped.set()
        thread.join(timeout=2)
    return True
