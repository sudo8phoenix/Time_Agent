"""Durable task lifecycle with strict identity and privacy checks."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentRun, AgentTask, Job
from .contracts import AgentRole, TaskEnvelope, TaskOutcome, TaskResult
from .budgets import BudgetExceeded, BudgetLimits
from .registry import DelegationError, get_role, validate_child

_REFERENCE = re.compile(r"^[A-Za-z0-9_.:/-]{1,200}$")
_CODE = re.compile(r"^[A-Z0-9_.:-]{1,100}$")
_SUMMARY_KEYS = {
    "status", "outcome", "count", "observation_count", "candidate_count",
    "proposal_count", "reference_count", "warning_count",
}


class TaskStoreError(ValueError):
    pass


@dataclass(frozen=True)
class TaskRecord:
    task_id: UUID
    parent_task_id: UUID | None
    run_id: UUID
    agent_role: str
    project_id: UUID
    source_id: UUID
    schedule_version_id: UUID
    observation_key: str | None
    attempt: int
    contract_version: str
    input_fingerprint: str
    status: str
    outcome: str | None
    output_references: tuple[str, ...]
    evidence_references: tuple[str, ...]
    actual_usage: Mapping[str, int]
    safe_summary: Mapping[str, Any]
    error_code: str | None
    reused: bool = False


def input_fingerprint(value: bytes | str | Mapping[str, Any]) -> str:
    """Hash canonical input data without retaining it in the task record."""
    if isinstance(value, bytes):
        encoded = value
    elif isinstance(value, str):
        encoded = value.encode("utf-8")
    else:
        import json
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _references(values: list[str], field: str) -> list[str]:
    if any(not isinstance(value, str) or not _REFERENCE.fullmatch(value) for value in values):
        raise TaskStoreError(f"{field} must contain reference identifiers, not source text")
    return list(values)


def _safe_summary(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Persist only small operational counters and registered status labels."""
    if value is None:
        return {}
    if set(value) - _SUMMARY_KEYS:
        raise TaskStoreError("summary contains unsupported or potentially sensitive fields")
    clean: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"status", "outcome"}:
            if not isinstance(item, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", item):
                raise TaskStoreError("summary status must be a short operational label")
            clean[key] = item
        else:
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise TaskStoreError("summary counters must be non-negative integers")
            clean[key] = item
    return clean


def close_cancelled_run(session: Session, run: AgentRun, *, now=None) -> None:
    """Close the journal within the caller's Job → Run → Task transaction."""
    now = now or datetime.now(timezone.utc)
    for task in session.scalars(select(AgentTask).where(
        AgentTask.run_id == run.id, AgentTask.status == "running"
    ).with_for_update()):
        task.status, task.outcome = "failed", "failed"
        task.error_code, task.finished_at = "JOB_CANCELLED", now
    if run.state != "cancelled":
        run.state, run.error_code = "cancelled", "JOB_CANCELLED"
        run.error_message = "The job was cancelled."
        run.updated_at = run.completed_at = now


class TaskStore:
    """Persist task envelopes and results beneath an existing agent run.

    ``session_factory`` is a SQLAlchemy sessionmaker or a compatible callable.
    A successful task with the same stable identity can be reused only when its
    input fingerprint still matches.
    """

    def __init__(self, session_factory: Callable[[], Session], run_id: UUID | str):
        self.session_factory = session_factory
        self.run_id = UUID(str(run_id))

    def begin(
        self,
        envelope: TaskEnvelope,
        *,
        input_fingerprint: str,
        safe_summary: Mapping[str, Any] | None = None,
    ) -> TaskRecord:
        self._check_run(envelope)
        if not re.fullmatch(r"[0-9a-f]{64}", input_fingerprint):
            raise TaskStoreError("input_fingerprint must be a lowercase SHA-256 hex digest")
        references = _references(envelope.input_references, "input_references")
        summary = _safe_summary(safe_summary)
        with self.session_factory() as session:
            self.lock_active_job(session)
            self._validate_parent(session, envelope)
            row = session.scalar(select(AgentTask).where(
                AgentTask.id == envelope.task_id
            ).with_for_update())
            if row is not None:
                self._assert_same_envelope(row, envelope, input_fingerprint)
                session.commit()
                return self._record(row, reused=row.status == "succeeded")
            if envelope.parent_task_id is not None:
                parent_row = session.get(AgentTask, envelope.parent_task_id)
                child_count = session.query(AgentTask).filter(
                    AgentTask.parent_task_id == envelope.parent_task_id
                ).count()
                if parent_row is not None and child_count >= get_role(parent_row.agent_role).max_children:
                    raise TaskStoreError("parent reached its registered child-task limit")
            row = AgentTask(
                id=envelope.task_id,
                run_id=envelope.run_id,
                parent_task_id=envelope.parent_task_id,
                agent_role=envelope.agent_role.value,
                project_id=envelope.project_id,
                source_id=envelope.source_id,
                schedule_version_id=envelope.schedule_version_id,
                observation_key=envelope.observation_key,
                attempt=envelope.attempt,
                contract_version=envelope.contract_version,
                input_fingerprint=input_fingerprint,
                input_references=references,
                output_references=[], evidence_references=[], warnings=[], actual_usage={},
                safe_summary=summary, status="running",
            )
            session.add(row)
            session.commit()
            return self._record(row)

    def finish(
        self,
        envelope: TaskEnvelope,
        result: TaskResult,
        *,
        safe_summary: Mapping[str, Any] | None = None,
    ) -> TaskRecord:
        self._check_run(envelope)
        result.validate_for(envelope)
        output_refs = _references(result.output_references, "output_references")
        evidence_refs = _references(result.evidence_references, "evidence_references")
        warning_codes = list(result.warnings)
        if any(not isinstance(code, str) or not _CODE.fullmatch(code) for code in warning_codes):
            raise TaskStoreError("warnings must be machine-readable codes")
        summary = _safe_summary(safe_summary)
        status = "failed" if result.outcome in {
            TaskOutcome.RETRYABLE_FAILURE, TaskOutcome.FAILED, TaskOutcome.STALE
        } else "succeeded"
        with self.session_factory() as session:
            self.lock_active_job(session)
            row = session.scalar(select(AgentTask).where(
                AgentTask.id == envelope.task_id
            ).with_for_update())
            if row is None:
                raise TaskStoreError("task must be begun before it can finish")
            self._assert_same_envelope(row, envelope, row.input_fingerprint)
            if row.status != "running":
                # An identical terminal result is an idempotent replay.
                if (
                    row.status == status
                    and row.outcome == result.outcome.value
                    and row.error_code == (result.error.code if result.error else None)
                    and list(row.output_references or ()) == output_refs
                    and list(row.evidence_references or ()) == evidence_refs
                    and list(row.warnings or ()) == warning_codes
                    and dict(row.actual_usage or {}) == dict(result.actual_usage)
                    and dict(row.safe_summary or {}) == summary
                ):
                    session.commit()
                    return self._record(row, reused=True)
                raise TaskStoreError("terminal task cannot be finished with a different result")
            self._validate_parent(session, envelope)
            if session.scalar(select(AgentTask.id).where(
                AgentTask.parent_task_id == row.id, AgentTask.status == "running"
            ).limit(1)) is not None:
                raise TaskStoreError("task has unfinished children")
            row.output_references = output_refs
            row.evidence_references = evidence_refs
            row.warnings = warning_codes
            row.actual_usage = dict(result.actual_usage)
            row.safe_summary = summary
            row.status = status
            row.outcome = result.outcome.value
            # Never persist provider/model error text, which can contain prompt
            # excerpts or source fragments. The stable code is sufficient.
            row.error_code = result.error.code if result.error else None
            row.finished_at = datetime.now(timezone.utc)
            session.commit()
            return self._record(row)

    def lock_active_job(self, session: Session) -> Job:
        """Fence task writes against cancellation under the owning job row lock.

        All task writers lock job, run, then task rows. Cancellation discovered
        here closes every active descendant in the same transaction; successful
        historical attempts and charged budgets remain unchanged. Call before
        any other writes: the cancellation branch deliberately commits its
        reconciliation before raising, so caller rollback cannot reopen work.
        """
        job_id = session.scalar(select(AgentRun.job_id).where(AgentRun.id == self.run_id))
        job = session.scalar(select(Job).where(Job.id == job_id).with_for_update().execution_options(populate_existing=True))
        run = session.scalar(select(AgentRun).where(AgentRun.id == self.run_id).with_for_update().execution_options(populate_existing=True))
        if job is None or run is None:
            raise TaskStoreError("agent run does not exist")
        if job.state == "cancelled":
            close_cancelled_run(session, run)
            session.commit()
            raise TaskStoreError("job is cancelled")
        return job

    begin_task = begin
    finish_task = finish

    def reserve_budget(
        self, counter: str, amount: int = 1, *, limits: BudgetLimits | None = None
    ) -> int:
        """Atomically charge run-wide usage before a model/tool/transition.

        Counts are stored in ``agent_runs.counters`` using hierarchy-prefixed
        keys, preserving the legacy runtime's existing counter fields.
        """
        limits = limits or BudgetLimits()
        limit_map = limits.as_dict()
        if counter not in limit_map or amount <= 0:
            raise ValueError("unknown counter or non-positive reservation")
        key = f"hierarchy_{counter}"
        with self.session_factory() as session:
            run = session.query(AgentRun).filter(AgentRun.id == self.run_id).with_for_update().one_or_none()
            if run is None:
                raise TaskStoreError("agent run does not exist")
            counters = dict(run.counters or {})
            current = int(counters.get(key, 0))
            if current + amount > limit_map[counter]:
                raise BudgetExceeded(counter, limit_map[counter])
            current += amount
            counters[key] = current
            run.counters = counters
            session.commit()
            return current

    def budget_snapshot(self, *, limits: BudgetLimits | None = None) -> dict[str, dict[str, int]]:
        limits = limits or BudgetLimits()
        with self.session_factory() as session:
            run = session.get(AgentRun, self.run_id)
            if run is None:
                raise TaskStoreError("agent run does not exist")
            counters = run.counters or {}
            used = {key: int(counters.get(f"hierarchy_{key}", 0)) for key in limits.as_dict()}
            if any(used[key] > limit for key, limit in limits.as_dict().items()):
                raise TaskStoreError("persisted run usage already exceeds configured budget")
            return {"used": used, "limits": limits.as_dict()}

    def _check_run(self, envelope: TaskEnvelope) -> None:
        if envelope.run_id != self.run_id:
            raise TaskStoreError("task run_id differs from this store's pinned run")
        get_role(envelope.agent_role)

    @staticmethod
    def _validate_parent(session: Session, envelope: TaskEnvelope) -> None:
        run = session.get(AgentRun, envelope.run_id)
        if run is None:
            raise TaskStoreError("agent run does not exist")
        if envelope.agent_role == AgentRole.ROOT:
            if envelope.parent_task_id is not None:
                raise TaskStoreError("root task cannot have a parent")
            job = session.get(Job, run.job_id)
            if job is None or (
                job.project_id != envelope.project_id
                or job.report_id != envelope.source_id
                or job.schedule_version_id != envelope.schedule_version_id
            ):
                raise TaskStoreError("root task scope does not match its pinned job")
            return
        # Serialize child creation with parent completion. `finish` locks the
        # same row, so either the child commits while the parent is active or
        # it observes the terminal parent and is rejected.
        parent_row = session.scalar(select(AgentTask).where(
            AgentTask.id == envelope.parent_task_id
        ).with_for_update())
        if parent_row is None:
            raise TaskStoreError("parent task does not exist")
        # A completed/failed parent has relinquished its delegation authority.
        # In particular, a late child result must not be attached after the
        # parent has already been merged or failed.
        if parent_row.status != "running":
            raise TaskStoreError("parent task is not active")
        parent = TaskEnvelope(
            task_id=parent_row.id,
            parent_task_id=parent_row.parent_task_id,
            run_id=parent_row.run_id,
            agent_role=parent_row.agent_role,
            project_id=parent_row.project_id,
            source_id=parent_row.source_id,
            schedule_version_id=parent_row.schedule_version_id,
            observation_key=parent_row.observation_key,
            attempt=parent_row.attempt,
            contract_version=parent_row.contract_version,
        )
        try:
            validate_child(parent, envelope)
        except (DelegationError, ValueError) as exc:
            raise TaskStoreError(str(exc)) from exc

    @staticmethod
    def _assert_same_envelope(row: AgentTask, envelope: TaskEnvelope, fingerprint: str) -> None:
        expected = (
            row.run_id, row.parent_task_id, row.agent_role, row.project_id, row.source_id,
            row.schedule_version_id, row.observation_key, row.attempt, row.contract_version,
        )
        actual = (
            envelope.run_id, envelope.parent_task_id, envelope.agent_role.value, envelope.project_id,
            envelope.source_id, envelope.schedule_version_id, envelope.observation_key,
            envelope.attempt, envelope.contract_version,
        )
        if expected != actual:
            raise TaskStoreError("stored task identity or pinned scope differs from envelope")
        if row.input_fingerprint != fingerprint:
            raise TaskStoreError("stable task identity was reused with a different input fingerprint")

    @staticmethod
    def _record(row: AgentTask, reused: bool = False) -> TaskRecord:
        return TaskRecord(
            task_id=row.id, parent_task_id=row.parent_task_id, run_id=row.run_id,
            agent_role=row.agent_role, project_id=row.project_id, source_id=row.source_id,
            schedule_version_id=row.schedule_version_id, observation_key=row.observation_key,
            attempt=row.attempt, contract_version=row.contract_version,
            input_fingerprint=row.input_fingerprint, status=row.status, outcome=row.outcome,
            output_references=tuple(row.output_references or ()),
            evidence_references=tuple(row.evidence_references or ()),
            actual_usage=dict(row.actual_usage or {}), safe_summary=dict(row.safe_summary or {}),
            error_code=row.error_code, reused=reused,
        )
