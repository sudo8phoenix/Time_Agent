from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.agent.context import AgentRuntimeContext
from app.agent.policy import (
    AgentPolicyError,
    NODE_TRANSITIONS,
    public_stage,
    route_extraction_validation,
    route_next_action,
    route_persist,
    route_selection_validation,
    validate_node_execution_budget,
    validate_repair_attempt,
    validate_transition,
)
from app.agent.state import AgentStateError, create_initial_state

IDS = {
    "run_id": "11111111-1111-4111-8111-111111111111",
    "job_id": "22222222-2222-4222-8222-222222222222",
    "project_id": "33333333-3333-4333-8333-333333333333",
    "report_id": "44444444-4444-4444-8444-444444444444",
    "schedule_version_id": "55555555-5555-4555-8555-555555555555",
}


def state(**updates):
    payload = dict(IDS)
    payload.update(updates)
    return create_initial_state(**payload)


def test_every_frozen_node_transition_and_forbidden_edges():
    for source, destinations in NODE_TRANSITIONS.items():
        for destination in destinations:
            validate_transition(source, destination)
    with pytest.raises(AgentPolicyError):
        validate_transition("extract", "persist")
    with pytest.raises(AgentPolicyError):
        validate_transition("unknown", "select")


@pytest.mark.parametrize(("action", "expected"), [
    ("extract", "extract"),
    ("repair_extraction", "repair_extraction"),
    ("retrieve", "retrieve"),
    ("select", "select"),
    ("repair_selection", "repair_selection"),
    ("persist", "persist"),
    ("fail", "record_failure"),
])
def test_only_frozen_actions_route_to_named_nodes(action, expected):
    assert route_next_action(state(next_action=action)) == expected


def test_conditional_routes_and_terminal_policy():
    assert route_extraction_validation(state(next_action="retrieve")) == "retrieve"
    assert route_extraction_validation(state(next_action="fail")) == "record_failure"
    assert route_selection_validation(state(next_action="persist")) == "persist"
    assert route_selection_validation(state(next_action="fail")) == "record_failure"
    assert route_persist(state(next_action="fail")) == "record_failure"
    assert route_persist(state(next_action="persist")) == "finalize"
    with pytest.raises(AgentPolicyError):
        route_extraction_validation(state(next_action="persist"))
    repair_state = state(next_action="repair_extraction", validation_errors=[
        {"stage": "extraction", "code": "A", "message": "bad one", "retryable": True},
        {"stage": "extraction", "code": "B", "message": "bad two", "retryable": True},
    ])
    assert route_extraction_validation(repair_state, attempted_repairs=0) == "repair_extraction"
    with pytest.raises(AgentPolicyError) as exc:
        route_extraction_validation(repair_state, attempted_repairs=1)
    assert exc.value.code == "AGENT_REPAIR_LIMIT"
    with pytest.raises(AgentPolicyError) as exc:
        route_selection_validation(state(next_action="repair_selection"), attempted_repairs=1)
    assert exc.value.code == "AGENT_REPAIR_LIMIT"
    assert public_stage("validate_extraction") == "Validating evidence"
    assert public_stage("unused", "ready_for_review") == "Ready for review"
    assert public_stage("unused", "stale") == "Stale"


def test_repair_budget_and_step_limits_fail_closed():
    validate_repair_attempt(state(), "extraction", attempted=0)
    validate_repair_attempt(state(), "selection", attempted=0)
    with pytest.raises(AgentPolicyError) as exc:
        validate_repair_attempt(state(), "extraction", attempted=1)
    assert exc.value.code == "AGENT_REPAIR_LIMIT"
    with pytest.raises(AgentPolicyError) as exc:
        validate_repair_attempt(state(), "selection", attempted=1)
    assert exc.value.code == "AGENT_REPAIR_LIMIT"
    validate_node_execution_budget(executions=12, repairs=0)
    validate_node_execution_budget(executions=16, repairs=1)
    with pytest.raises(AgentPolicyError) as exc:
        validate_node_execution_budget(executions=13, repairs=0)
    assert exc.value.code == "AGENT_STEP_LIMIT"
    with pytest.raises(AgentPolicyError) as exc:
        validate_node_execution_budget(executions=17, repairs=1)
    assert exc.value.code == "AGENT_STEP_LIMIT"
    with pytest.raises(AgentPolicyError) as exc:
        validate_node_execution_budget(executions=12, repairs=3)
    assert exc.value.code == "AGENT_REPAIR_LIMIT"


def test_runtime_context_is_frozen_ephemeral_and_has_exact_fields():
    def noop(*args):
        return None
    context = AgentRuntimeContext(noop, "lease-sentinel", noop, None, noop, noop, noop)
    assert set(context.__dataclass_fields__) == {
        "session_factory", "lease_token", "model_callable", "embedder",
        "heartbeat_callback", "shutdown_callback", "clock",
    }
    with pytest.raises(FrozenInstanceError):
        context.lease_token = "changed"
    with pytest.raises(AgentStateError):
        state(lease_token=context.lease_token)
