"""Pure bounded routing, transition and retry policy."""
from __future__ import annotations

from typing import Mapping

from .state import AgentState, MAX_CANDIDATES, MAX_OBSERVATIONS, observation_keys

MAX_NODE_EXECUTIONS_NO_REPAIR = 12
MAX_NODE_EXECUTIONS_WITH_REPAIR = 16
MAX_EXTRACTION_REPAIRS = 1
MAX_SELECTION_REPAIRS = 1

NODE_TRANSITIONS: Mapping[str, tuple[str, ...]] = {
    "__start__": ("load_context",),
    "load_context": ("extract", "record_failure"),
    "extract": ("validate_extraction",),
    "validate_extraction": ("retrieve", "repair_extraction", "record_failure"),
    "repair_extraction": ("validate_extraction",),
    "retrieve": ("select",),
    "select": ("validate_selection",),
    "validate_selection": ("persist", "repair_selection", "record_failure"),
    "repair_selection": ("validate_selection",),
    "persist": ("finalize", "record_failure"),
    "finalize": ("__end__",),
    "record_failure": ("__end__",),
}

NEXT_ACTION_NODES = frozenset(("extract", "repair_extraction", "retrieve", "select", "repair_selection", "persist", "record_failure"))

PUBLIC_STAGES = {
    "load_context": "Loading context",
    "extract": "Extracting observations",
    "validate_extraction": "Validating evidence",
    "repair_extraction": "Extracting observations",
    "retrieve": "Retrieving schedule candidates",
    "select": "Selecting supported matches",
    "validate_selection": "Validating proposals",
    "repair_selection": "Selecting supported matches",
    "persist": "Saving for review",
    "finalize": "Ready for review",
    "record_failure": "Failed",
    "stale": "Stale",
}


class AgentPolicyError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def validate_transition(source: str, destination: str) -> None:
    if destination not in NODE_TRANSITIONS.get(source, ()):
        raise AgentPolicyError("AGENT_STATE_INVALID", f"transition {source!r} -> {destination!r} is not allowed")


def route_next_action(state: AgentState) -> str:
    """Map frozen state action to an exact graph node; unknown routes fail closed."""
    route = "record_failure" if state.next_action == "fail" else state.next_action
    if route not in NEXT_ACTION_NODES:
        raise AgentPolicyError("AGENT_STATE_INVALID", "state requested an unknown route")
    return route


def route_extraction_validation(state: AgentState, *, attempted_repairs: int = 0) -> str:
    if state.next_action == "retrieve":
        return "retrieve"
    if state.next_action == "repair_extraction":
        _check_repair_budget(state, "extraction", attempted_repairs)
        return "repair_extraction"
    if state.next_action == "fail":
        return "record_failure"
    raise AgentPolicyError("AGENT_STATE_INVALID", "invalid extraction validation route")


def route_selection_validation(state: AgentState, *, attempted_repairs: int = 0) -> str:
    if state.next_action == "persist":
        return "persist"
    if state.next_action == "repair_selection":
        _check_repair_budget(state, "selection", attempted_repairs)
        return "repair_selection"
    if state.next_action == "fail":
        return "record_failure"
    raise AgentPolicyError("AGENT_STATE_INVALID", "invalid selection validation route")


def route_persist(state: AgentState) -> str:
    return "record_failure" if state.next_action == "fail" else "finalize" if state.next_action == "persist" else _invalid_route()


def _invalid_route():
    raise AgentPolicyError("AGENT_STATE_INVALID", "invalid persistence route")


def _check_repair_budget(state: AgentState, stage: str, attempted_repairs: int) -> None:
    validate_repair_attempt(state, stage, attempted=attempted_repairs)
    if state.counters.corrective_retries >= MAX_EXTRACTION_REPAIRS + MAX_SELECTION_REPAIRS:
        raise AgentPolicyError("AGENT_REPAIR_LIMIT", "total corrective retry budget exhausted")


def validate_repair_attempt(state: AgentState, stage: str, *, attempted: int) -> None:
    limit = MAX_EXTRACTION_REPAIRS if stage == "extraction" else MAX_SELECTION_REPAIRS if stage == "selection" else 0
    if limit == 0:
        raise AgentPolicyError("AGENT_STATE_INVALID", "repair stage must be extraction or selection")
    if attempted >= limit:
        raise AgentPolicyError("AGENT_REPAIR_LIMIT", f"{stage} corrective retry budget exhausted")


def validate_observation_and_candidate_limits(state: AgentState) -> None:
    if len(state.observation_drafts) > MAX_OBSERVATIONS:
        raise AgentPolicyError("AGENT_OBSERVATION_LIMIT", "report exceeds 200 accepted observations")
    expected = set(observation_keys(len(state.observation_drafts)))
    if set(state.candidate_sets) - expected or set(state.selection_drafts) - expected:
        raise AgentPolicyError("AGENT_STATE_INVALID", "candidate/selection key is not an observation key")
    if any(len(candidates) > MAX_CANDIDATES for candidates in state.candidate_sets.values()):
        raise AgentPolicyError("AGENT_STATE_INVALID", "candidate set exceeds eight entries")


def validate_node_execution_budget(*, executions: int, repairs: int) -> None:
    if executions < 0 or repairs < 0:
        raise AgentPolicyError("AGENT_STATE_INVALID", "execution counters cannot be negative")
    if repairs > MAX_EXTRACTION_REPAIRS + MAX_SELECTION_REPAIRS:
        raise AgentPolicyError("AGENT_REPAIR_LIMIT", "total corrective retry budget exceeded")
    limit = MAX_NODE_EXECUTIONS_NO_REPAIR if repairs == 0 else MAX_NODE_EXECUTIONS_WITH_REPAIR
    if executions > limit:
        raise AgentPolicyError("AGENT_STEP_LIMIT", "graph node execution limit exceeded")


def public_stage(node: str, terminal_state: str | None = None) -> str:
    if terminal_state == "ready_for_review":
        return "Ready for review"
    if terminal_state == "failed":
        return "Failed"
    if terminal_state == "stale":
        return "Stale"
    try:
        return PUBLIC_STAGES[node]
    except KeyError as exc:
        raise AgentPolicyError("AGENT_STATE_INVALID", "node has no public stage label") from exc
