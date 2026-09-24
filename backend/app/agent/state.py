"""Strict, bounded JSON state for one report-analysis graph run."""
from __future__ import annotations

import json
import math
from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, StrictStr, ValidationError, field_validator, model_validator

from app.schemas.common import StrictModel
from app.schemas.matching import Candidate, Proposal
from app.schemas.observation import Observation

STATE_SCHEMA_VERSION = "agent-state-v1"
GRAPH_VERSION = "report-analysis-v1"
MAX_STATE_BYTES = 1_048_576
MAX_OBSERVATIONS = 200
MAX_CANDIDATES = 8


class AgentStateError(ValueError):
    """Stable state validation failure suitable for policy conversion."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _canonical_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("must be a canonical UUID string") from exc
    if str(parsed) != value:
        raise ValueError("must be a canonical lowercase UUID string")
    return value


class AgentCounters(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    node_executions: int = Field(ge=0, le=16)
    extraction_calls: int = Field(ge=0, le=2)
    selection_calls: int = Field(ge=0, le=400)
    corrective_retries: int = Field(ge=0, le=2)


class ValidationErrorRecord(StrictModel):
    stage: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    retryable: bool


class AgentWarning(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)


class ModelMetadata(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model_tag: StrictStr | None = Field(default=None, max_length=200)
    model_digest: StrictStr | None = Field(default=None, max_length=256)
    extraction_prompt_version: StrictStr | None = Field(default=None, max_length=100)
    extraction_prompt_hash: StrictStr | None = Field(default=None, max_length=128)
    selection_prompt_version: StrictStr | None = Field(default=None, max_length=100)
    selection_prompt_hash: StrictStr | None = Field(default=None, max_length=128)
    settings_hash: StrictStr | None = Field(default=None, max_length=128)


class AgentState(StrictModel):
    """Exactly the frozen graph-state fields; all values are JSON-safe."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["agent-state-v1"]
    run_id: str
    job_id: str
    project_id: str
    report_id: str
    schedule_version_id: str
    graph_version: Literal["report-analysis-v1"]
    fragment_ids: list[str]
    activity_ids: list[str]
    observation_drafts: list[Observation] = Field(max_length=MAX_OBSERVATIONS)
    candidate_sets: dict[str, list[Candidate]]
    selection_drafts: dict[str, Proposal]
    validation_errors: list[ValidationErrorRecord]
    warnings: list[AgentWarning]
    counters: AgentCounters
    model_metadata: ModelMetadata
    next_action: Literal[
        "extract", "repair_extraction", "retrieve", "select", "repair_selection", "persist", "fail"
    ]
    terminal_state: Literal["ready_for_review", "failed", "stale", "cancelled"] | None

    @field_validator("run_id", "job_id", "project_id", "report_id", "schedule_version_id")
    @classmethod
    def identity_is_canonical_uuid(cls, value: str) -> str:
        return _canonical_uuid(value)

    @field_validator("fragment_ids", "activity_ids")
    @classmethod
    def ids_are_unique_canonical(cls, values: list[str]) -> list[str]:
        for value in values:
            _canonical_uuid(value)
        if len(values) != len(set(values)):
            raise ValueError("IDs must be ordered and unique")
        return values

    @field_validator("candidate_sets")
    @classmethod
    def candidate_limit(cls, values: dict[str, list[Candidate]]) -> dict[str, list[Candidate]]:
        if any(len(candidates) > MAX_CANDIDATES for candidates in values.values()):
            raise ValueError("each candidate set is limited to eight")
        return values

    @field_validator("observation_drafts", mode="before")
    @classmethod
    def parse_observations_with_frozen_schema(cls, values):
        return [value if isinstance(value, Observation) else Observation.model_validate(value) for value in values]

    @field_validator("candidate_sets", mode="before")
    @classmethod
    def parse_candidates_with_frozen_schema(cls, values):
        return {
            key: [candidate if isinstance(candidate, Candidate) else Candidate.model_validate(candidate) for candidate in candidates]
            for key, candidates in values.items()
        }

    @field_validator("selection_drafts", mode="before")
    @classmethod
    def parse_proposals_with_frozen_schema(cls, values):
        return {
            key: proposal if isinstance(proposal, Proposal) else Proposal.model_validate(proposal)
            for key, proposal in values.items()
        }

    @model_validator(mode="after")
    def observation_keys_are_consistent(self):
        if len(self.observation_drafts) > MAX_OBSERVATIONS:
            raise ValueError("observation limit exceeded")
        expected = set(observation_keys(len(self.observation_drafts)))
        candidate_keys = set(self.candidate_sets)
        selection_keys = set(self.selection_drafts)
        if candidate_keys and candidate_keys != expected:
            raise ValueError("candidate keys must exactly match observation keys")
        if selection_keys and selection_keys != expected:
            raise ValueError("selection keys must exactly match observation keys")
        # Empty maps are legitimate before their corresponding node runs. Once
        # both stages have produced data their correlation keysets must match.
        if candidate_keys and selection_keys and candidate_keys != selection_keys:
            raise ValueError("candidate and selection dictionaries must have equal keys")
        return self


def observation_keys(count: int) -> list[str]:
    if count < 0 or count > MAX_OBSERVATIONS:
        raise AgentStateError("AGENT_OBSERVATION_LIMIT", "observation count is outside 0..200")
    return [f"obs-{index:04d}" for index in range(1, count + 1)]


def create_initial_state(*, counters: dict[str, int] | None = None, **values: Any) -> AgentState:
    """Create only an initial state; this is the sole place counters default."""
    payload = dict(values)
    payload.setdefault("schema_version", STATE_SCHEMA_VERSION)
    payload.setdefault("graph_version", GRAPH_VERSION)
    payload.setdefault("fragment_ids", [])
    payload.setdefault("activity_ids", [])
    payload.setdefault("observation_drafts", [])
    payload.setdefault("candidate_sets", {})
    payload.setdefault("selection_drafts", {})
    payload.setdefault("validation_errors", [])
    payload.setdefault("warnings", [])
    payload.setdefault("counters", counters if counters is not None else {
        "node_executions": 0,
        "extraction_calls": 0,
        "selection_calls": 0,
        "corrective_retries": 0,
    })
    payload.setdefault("model_metadata", {})
    payload.setdefault("next_action", "extract")
    payload.setdefault("terminal_state", None)
    try:
        return AgentState.model_validate(payload)
    except ValidationError as exc:
        raise AgentStateError("AGENT_STATE_INVALID", str(exc)) from exc


def _reject_nonfinite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise AgentStateError("AGENT_STATE_INVALID", "nonfinite numbers are not allowed")
    if isinstance(value, dict):
        for nested in value.values():
            _reject_nonfinite(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_nonfinite(nested)


def encode_agent_state(state: AgentState) -> bytes:
    """Return canonical UTF-8 JSON, rejecting invalid values and oversize data."""
    try:
        python_payload = state.model_dump(mode="python", warnings=False)
        _reject_nonfinite(python_payload)
        AgentState.model_validate(python_payload)
        payload = state.model_dump(mode="json", warnings=False)
        _reject_nonfinite(payload)
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        if isinstance(exc, AgentStateError):
            raise
        raise AgentStateError("AGENT_STATE_INVALID", "state cannot be encoded as finite JSON") from exc
    if len(encoded) > MAX_STATE_BYTES:
        raise AgentStateError("AGENT_STATE_TOO_LARGE", "serialized state exceeds 1 MiB")
    return encoded


def decode_agent_state(payload: bytes | str) -> AgentState:
    """Decode resumed state; all fields, including counters, are mandatory."""
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if len(raw) > MAX_STATE_BYTES:
        raise AgentStateError("AGENT_STATE_TOO_LARGE", "serialized state exceeds 1 MiB")

    def reject_constant(value: str):
        raise AgentStateError("AGENT_STATE_INVALID", f"nonfinite JSON constant {value} is not allowed")

    try:
        decoded = json.loads(raw, parse_constant=reject_constant)
        _reject_nonfinite(decoded)
        return AgentState.model_validate(decoded)
    except AgentStateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise AgentStateError("AGENT_STATE_INVALID", "invalid resumed agent state") from exc


def validate_identity_transition(previous: AgentState, current: AgentState) -> None:
    fields = ("run_id", "job_id", "project_id", "report_id", "schedule_version_id", "graph_version", "schema_version")
    changed = [field for field in fields if getattr(previous, field) != getattr(current, field)]
    if changed:
        raise AgentStateError("AGENT_STATE_INVALID", f"immutable identity changed: {', '.join(changed)}")
