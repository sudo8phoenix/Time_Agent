"""Strict, public-safe schemas for bounded agent-run status."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import Field, model_validator

from .common import StrictModel


class AgentRunState(str, Enum):
    created = "created"
    running = "running"
    ready_for_review = "ready_for_review"
    failed = "failed"
    stale = "stale"
    cancelled = "cancelled"


class AgentTraceState(str, Enum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class AgentNode(str, Enum):
    load_context = "load_context"
    extract = "extract"
    validate_extraction = "validate_extraction"
    repair_extraction = "repair_extraction"
    retrieve = "retrieve"
    select = "select"
    validate_selection = "validate_selection"
    repair_selection = "repair_selection"
    persist = "persist"
    finalize = "finalize"
    record_failure = "record_failure"


class PublicAgentStage(str, Enum):
    loading_context = "Loading context"
    extracting_observations = "Extracting observations"
    validating_evidence = "Validating evidence"
    retrieving_schedule_candidates = "Retrieving schedule candidates"
    selecting_supported_matches = "Selecting supported matches"
    validating_proposals = "Validating proposals"
    saving_for_review = "Saving for review"
    ready_for_review = "Ready for review"
    failed = "Failed"
    stale = "Stale"


class AgentCounters(StrictModel):
    node_executions: int = Field(ge=0, le=16)
    extraction_calls: int = Field(ge=0, le=2)
    selection_calls: int = Field(ge=0, le=400)
    corrective_retries: int = Field(ge=0, le=2)


_NODE_LABELS: dict[AgentNode, frozenset[PublicAgentStage]] = {
    AgentNode.load_context: frozenset({PublicAgentStage.loading_context}),
    AgentNode.extract: frozenset({PublicAgentStage.extracting_observations}),
    AgentNode.validate_extraction: frozenset({PublicAgentStage.validating_evidence}),
    AgentNode.repair_extraction: frozenset({PublicAgentStage.extracting_observations}),
    AgentNode.retrieve: frozenset({PublicAgentStage.retrieving_schedule_candidates}),
    AgentNode.select: frozenset({PublicAgentStage.selecting_supported_matches}),
    AgentNode.validate_selection: frozenset({PublicAgentStage.validating_proposals}),
    AgentNode.repair_selection: frozenset({PublicAgentStage.selecting_supported_matches}),
    AgentNode.persist: frozenset({PublicAgentStage.saving_for_review}),
    AgentNode.finalize: frozenset({PublicAgentStage.ready_for_review}),
    AgentNode.record_failure: frozenset({PublicAgentStage.failed, PublicAgentStage.stale}),
}


class AgentStepStatus(StrictModel):
    ordinal: int = Field(ge=1)
    node: AgentNode
    label: PublicAgentStage
    state: AgentTraceState
    attempt: int = Field(ge=1)
    duration_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_public_trace(self):
        if self.label not in _NODE_LABELS[self.node]:
            raise ValueError("label is not the public label for node")
        if self.state is AgentTraceState.running and self.duration_ms is not None:
            raise ValueError("running step duration must be null")
        if self.state is not AgentTraceState.failed and self.error_code is not None:
            raise ValueError("step error_code is only allowed for failed state")
        return self


class AgentRunStatus(StrictModel):
    """Canonical read-only response; internal trace/checkpoint fields are absent by design."""

    id: UUID
    job_id: UUID
    graph_version: str = Field(min_length=1, max_length=100)
    framework_version: str = Field(min_length=1, max_length=100)
    state: AgentRunState
    current_stage: PublicAgentStage | None
    counters: AgentCounters
    steps: list[AgentStepStatus] = Field(max_length=16)
    error_code: str | None = Field(default=None, min_length=1, max_length=100)
    error_message: str | None = Field(default=None, min_length=1, max_length=1000)
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    @model_validator(mode="after")
    def validate_status(self):
        ordinals = [step.ordinal for step in self.steps]
        if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
            raise ValueError("steps must have unique ascending ordinals")
        error_state = self.state in {
            AgentRunState.failed,
            AgentRunState.stale,
            AgentRunState.cancelled,
        }
        if not error_state and (self.error_code is not None or self.error_message is not None):
            raise ValueError("run errors are only allowed for failed, stale, or cancelled state")
        if self.updated_at < self.started_at:
            raise ValueError("updated_at must not precede started_at")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        return self


# The endpoint card refers to its canonical body as a response; keep the explicit alias
# without widening or duplicating the contract.
AgentRunResponse = AgentRunStatus
AgentStepResponse = AgentStepStatus
