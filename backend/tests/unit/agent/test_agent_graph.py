from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from app.agent.context import AgentRuntimeContext
from app.agent.graph import NODE_NAMES, build_report_analysis_graph
from app.agent.nodes import _nodes, conditional_routers
from app.agent.state import AgentCounters, AgentState, create_initial_state, observation_keys
from app.agent.tools import AgentToolError
from app.agent import policy
from test_agent_tools import Fixture


IDS = {
    "run_id": "11111111-1111-4111-8111-111111111111",
}


class FaultingTools:
    """Small fault injector around the real W-34 tools used by graph tests."""

    def __init__(self, wrapped, *, extraction_failures=0, selection_failures=0, load_error=None):
        self.wrapped = wrapped
        self.extraction_failures = extraction_failures
        self.selection_failures = selection_failures
        self.load_error = load_error
        self.extraction_calls = 0
        self.selection_calls = 0

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    def load_job_context(self, job_id):
        if self.load_error is not None:
            raise self.load_error
        return self.wrapped.load_job_context(job_id)

    def extract_observations(self, fragment_ids, report_metadata):
        self.extraction_calls += 1
        if self.extraction_calls <= self.extraction_failures:
            raise AgentToolError(
                "AGENT_TOOL_FAILED", "Extraction output failed validation.",
                stage="extraction", retryable=True,
            )
        return self.wrapped.extract_observations(fragment_ids, report_metadata)

    def select_candidate(self, observation_key, observation, candidates, fragment_ids):
        self.selection_calls += 1
        if self.selection_calls <= self.selection_failures:
            raise AgentToolError(
                "AGENT_TOOL_FAILED", "Selection output failed validation.",
                stage="selection", retryable=True,
            )
        return self.wrapped.select_candidate(observation_key, observation, candidates, fragment_ids)


def initial(fixture: Fixture, *, counters=None, **updates):
    return create_initial_state(
        **IDS,
        job_id=str(fixture.job_id), project_id=str(fixture.project_id),
        report_id=str(fixture.report_id), schedule_version_id=str(fixture.schedule_id),
        counters=counters, **updates,
    )


def invoke(tools, state=None):
    graph = build_report_analysis_graph(MemorySaver(), tools)
    return graph.invoke(state, {"configurable": {"thread_id": str(uuid4())}})


def test_graph_manifest_is_exact_frozen_nodes_and_edges():
    fixture = Fixture()
    graph = build_report_analysis_graph(MemorySaver(), FaultingTools(fixture.tools()))
    snapshot = graph.get_graph()
    assert tuple(name for name in NODE_NAMES) == (
        "load_context", "extract", "validate_extraction", "repair_extraction", "retrieve",
        "select", "validate_selection", "repair_selection", "persist", "finalize", "record_failure",
    )
    assert set(snapshot.nodes) == {"__start__", "__end__", *NODE_NAMES}
    assert {(edge.source, edge.target) for edge in snapshot.edges} == {
        ("__start__", "load_context"),
        ("load_context", "extract"), ("load_context", "record_failure"),
        ("extract", "validate_extraction"),
        ("validate_extraction", "retrieve"), ("validate_extraction", "repair_extraction"),
        ("validate_extraction", "record_failure"),
        ("repair_extraction", "validate_extraction"),
        ("retrieve", "select"), ("select", "validate_selection"),
        ("validate_selection", "persist"), ("validate_selection", "repair_selection"),
        ("validate_selection", "record_failure"),
        ("repair_selection", "validate_selection"),
        ("persist", "finalize"), ("persist", "record_failure"),
        ("finalize", "__end__"), ("record_failure", "__end__"),
    }


def test_no_repair_path_and_empty_retrieval_abstain_without_model_selection():
    fixture = Fixture()
    wrapped = fixture.tools(retrieval_service=lambda *args, **kwargs: [])
    tools = FaultingTools(wrapped)
    result = invoke(tools, initial(fixture))
    assert result["terminal_state"] == "ready_for_review"
    assert result["counters"]["corrective_retries"] == 0
    assert result["selection_drafts"]["obs-0001"]["candidate_id"] is None
    assert fixture.model_calls == 1  # extraction only; empty-candidate abstention is deterministic.
    assert result["counters"]["node_executions"] == 8


def test_extraction_repair_reruns_once_and_recovers():
    fixture = Fixture()
    tools = FaultingTools(fixture.tools(), extraction_failures=1)
    result = invoke(tools, initial(fixture))
    assert result["terminal_state"] == "ready_for_review"
    assert tools.extraction_calls == 2
    assert result["counters"]["corrective_retries"] == 1
    assert result["counters"]["extraction_calls"] == 2


def test_selection_repair_reruns_once_and_recovers():
    fixture = Fixture()
    tools = FaultingTools(fixture.tools(), selection_failures=1)
    result = invoke(tools, initial(fixture))
    assert result["terminal_state"] == "ready_for_review"
    assert tools.selection_calls == 2
    assert result["counters"]["corrective_retries"] == 1


def test_later_selection_error_discards_partial_map_and_keeps_state_valid():
    fixture = Fixture()
    second = fixture.observation.model_copy(update={
        "quantity": Decimal("3"), "summary": "Installed an additional 3 m of cable.",
    })
    original_model = fixture.context.model_callable

    def model(**kwargs):
        if "schema" in kwargs and "properties" in kwargs["schema"] and "candidate_id" in kwargs["schema"]["properties"]:
            return original_model(**kwargs)
        fixture.model_calls += 1
        return {"observations": [fixture.observation.model_dump(mode="json"), second.model_dump(mode="json")]}

    fixture.context = AgentRuntimeContext(
        session_factory=fixture.context.session_factory, lease_token=fixture.token,
        model_callable=model, embedder=None, heartbeat_callback=lambda *args: True,
        shutdown_callback=lambda: False, clock=fixture.context.clock,
    )
    wrapped = fixture.tools()
    scope = wrapped.load_job_context(str(fixture.job_id))
    extracted = wrapped.extract_observations(scope.fragment_ids, wrapped.report_metadata)
    assert len(extracted.observations) == 2
    keys = observation_keys(2)
    candidates = {
        key: wrapped.retrieve_candidates(key, observation, scope.schedule_version_id).candidates
        for key, observation in zip(keys, extracted.observations, strict=True)
    }

    class FailSecondSelection(FaultingTools):
        def select_candidate(self, observation_key, observation, candidates, fragment_ids):
            if observation_key == "obs-0002" and not getattr(self, "failed_second", False):
                self.failed_second = True
                raise AgentToolError(
                    "AGENT_TOOL_FAILED", "Selection output failed validation.",
                    stage="selection", retryable=True,
                )
            return self.wrapped.select_candidate(observation_key, observation, candidates, fragment_ids)

    state = create_initial_state(
        **IDS, job_id=scope.job_id, project_id=scope.project_id, report_id=scope.report_id,
        schedule_version_id=scope.schedule_version_id, fragment_ids=scope.fragment_ids,
        activity_ids=scope.activity_ids, observation_drafts=extracted.observations,
        candidate_sets=candidates, next_action="select",
    )
    update = _nodes(FailSecondSelection(wrapped), policy)["select"](state)
    assert update["selection_drafts"] == {}
    AgentState.model_validate({**state.model_dump(mode="python"), **update})


def test_empty_extraction_and_stale_or_failure_are_terminal_and_stable():
    fixture = Fixture()
    empty = fixture.tools(extraction_service=lambda *args, **kwargs: [])
    empty_result = invoke(FaultingTools(empty), initial(fixture))
    assert empty_result["terminal_state"] == "ready_for_review"
    assert empty_result["observation_drafts"] == []

    stale_fixture = Fixture()
    stale_tools = FaultingTools(stale_fixture.tools(), load_error=AgentToolError(
        "SCHEDULE_VERSION_STALE", "The project schedule changed during this run.",
    ))
    stale = invoke(stale_tools, initial(stale_fixture))
    assert stale["terminal_state"] == "stale"
    assert stale["validation_errors"][0]["code"] == "SCHEDULE_VERSION_STALE"

    failed_fixture = Fixture()
    failed_tools = FaultingTools(failed_fixture.tools(), extraction_failures=2)
    failed = invoke(failed_tools, initial(failed_fixture))
    assert failed["terminal_state"] == "failed"
    assert failed["validation_errors"][0]["code"] == "AGENT_REPAIR_LIMIT"
    assert failed["counters"]["corrective_retries"] == 1


def test_impossible_route_node_limit_and_selection_only_repair_budget():
    fixture = Fixture()
    routers = conditional_routers(policy)
    impossible = initial(fixture, next_action="persist")
    assert routers[0](impossible) == "record_failure"

    exhausted = initial(fixture, counters={
        "node_executions": 16, "extraction_calls": 0, "selection_calls": 0, "corrective_retries": 0,
    })
    failed = invoke(FaultingTools(fixture.tools()), exhausted)
    assert failed["terminal_state"] == "failed"
    assert failed["counters"]["node_executions"] == 16
    assert failed["validation_errors"][0]["code"] == "AGENT_STEP_LIMIT"
    AgentCounters.model_validate(failed["counters"])

    selection_only_retry = initial(fixture, counters={
        "node_executions": 0, "extraction_calls": 1, "selection_calls": 0, "corrective_retries": 1,
    }, next_action="repair_selection")
    assert routers[2](selection_only_retry) == "record_failure"


def test_router_and_node_factories_use_injected_policy_object():
    fixture = Fixture()

    class PolicyProxy:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            target = getattr(policy, name)
            if not callable(target):
                return target
            def forwarded(*args, **kwargs):
                self.calls.append(name)
                return target(*args, **kwargs)
            return forwarded

    injected = PolicyProxy()
    node_set = _nodes(FaultingTools(fixture.tools()), injected)
    node_set["load_context"](initial(fixture))
    assert "validate_node_execution_budget" in injected.calls
    route_set = conditional_routers(injected)
    assert route_set[0](initial(fixture)) == "extract"
    assert "route_next_action" in injected.calls
