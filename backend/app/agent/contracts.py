"""Strict, versioned contracts for hierarchical agent tasks.

These envelopes carry identity and references only. Source text, prompts, and
provider/session objects belong in the ephemeral runtime context.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from app.schemas.common import StrictModel

CONTRACT_VERSION = "agent-task-v1"
TASK_NAMESPACE = UUID("97bd0294-92af-4b2c-830c-d1ec3fa8134f")


class AgentRole(StrEnum):
    ROOT = "root"
    INTAKE = "intake"
    ANALYSIS = "analysis"
    REVIEW = "review"
    CLARIFICATION = "clarification"
    EXTRACTION = "extraction"
    MATCHING = "matching"
    EVIDENCE = "evidence"
    SELECTION = "selection"


class TaskOutcome(StrEnum):
    COMPLETED = "completed"
    NEEDS_CLARIFICATION = "needs_clarification"
    RETRYABLE_FAILURE = "retryable_failure"
    FAILED = "failed"
    STALE = "stale"
    UNRESOLVED = "unresolved"


class TaskError(StrictModel):
    code: str = Field(min_length=1, max_length=100, pattern=r"^[A-Z0-9_.:-]+$")
    # This is intentionally a short, caller-supplied operational message. The
    # durable store persists only the code and never the message.
    safe_message: str | None = Field(default=None, max_length=300)
    retryable: bool = False


class TaskEnvelope(StrictModel):
    """Identity and pinned scope for one delegated unit of work."""

    task_id: UUID
    parent_task_id: UUID | None = None
    run_id: UUID
    agent_role: AgentRole
    project_id: UUID
    source_id: UUID
    schedule_version_id: UUID
    input_references: list[str] = Field(default_factory=list, max_length=500)
    observation_key: str | None = Field(default=None, max_length=100)
    attempt: int = Field(ge=1, le=100)
    contract_version: str = Field(default=CONTRACT_VERSION, min_length=1, max_length=80)
    deadline: datetime | None = None
    budget_allocation: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_task_shape(self):
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError("unsupported task contract version")
        if self.agent_role == AgentRole.ROOT:
            if self.parent_task_id is not None or self.attempt != 1:
                raise ValueError("root task must have no parent and attempt 1")
        elif self.parent_task_id is None:
            raise ValueError("non-root task must have a parent")
        if self.agent_role == AgentRole.SELECTION and self.observation_key is None:
            raise ValueError("selection tasks require an observation key")
        expected_id = stable_task_id(
            run_id=self.run_id,
            parent_task_id=self.parent_task_id,
            agent_role=self.agent_role,
            observation_key=self.observation_key,
            attempt=self.attempt,
            contract_version=self.contract_version,
        )
        if self.task_id != expected_id:
            raise ValueError("task_id must be the stable UUID for its run, parent, role, observation, attempt, and contract")
        if any(not key or len(key) > 80 or value < 0 for key, value in self.budget_allocation.items()):
            raise ValueError("budget allocations require short names and non-negative values")
        return self


class TaskResult(StrictModel):
    task_id: UUID
    parent_task_id: UUID | None
    run_id: UUID
    agent_role: AgentRole
    project_id: UUID
    source_id: UUID
    schedule_version_id: UUID
    outcome: TaskOutcome
    output_references: list[str] = Field(default_factory=list, max_length=500)
    evidence_references: list[str] = Field(default_factory=list, max_length=500)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    actual_usage: dict[str, int] = Field(default_factory=dict)
    schema_version: str = Field(default=CONTRACT_VERSION, min_length=1, max_length=80)
    error: TaskError | None = None

    @model_validator(mode="after")
    def outcome_has_consistent_error(self):
        failure = self.outcome in {TaskOutcome.RETRYABLE_FAILURE, TaskOutcome.FAILED, TaskOutcome.STALE}
        if failure != (self.error is not None):
            raise ValueError("failure outcomes require an error; other outcomes forbid one")
        if any(not key or len(key) > 80 or value < 0 for key, value in self.actual_usage.items()):
            raise ValueError("usage counters require short names and non-negative values")
        return self

    def validate_for(self, task: TaskEnvelope) -> "TaskResult":
        expected = (task.task_id, task.parent_task_id, task.run_id, task.agent_role,
                    task.project_id, task.source_id, task.schedule_version_id)
        actual = (self.task_id, self.parent_task_id, self.run_id, self.agent_role,
                  self.project_id, self.source_id, self.schedule_version_id)
        if actual != expected:
            raise ValueError("task result identity or pinned scope does not match its envelope")
        if self.schema_version != task.contract_version:
            raise ValueError("task result schema version does not match its envelope")
        return self


def stable_task_id(
    *, run_id: UUID, parent_task_id: UUID | None, agent_role: AgentRole | str,
    attempt: int, observation_key: str | None = None, contract_version: str = CONTRACT_VERSION,
) -> UUID:
    """Return a deterministic UUID for a task identity and its retry attempt."""
    if attempt < 1:
        raise ValueError("attempt must be positive")
    role = AgentRole(agent_role).value
    identity = f"{run_id}:{parent_task_id or 'root'}:{role}:{observation_key or '-'}:{attempt}:{contract_version}"
    return uuid5(TASK_NAMESPACE, identity)
