from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.agent.hierarchy import build_hierarchical_report_graph, HierarchyExecution, ScopedTools, validated_decision
from app.agent.runtime import FRAMEWORK_VERSION, _create_or_load_run
from app.agent.state import create_hierarchical_state, HierarchicalAgentState
from app.agent.tools import AgentToolError
from app.db.models import AgentRun, AgentTask, Job
from app.settings import get_settings
from test_agent_tools import Fixture
from test_agent_graph import FaultingTools


def setup(execution=False):
    fixture = Fixture()
    initial = create_hierarchical_state(run_id=str(uuid4()), job_id=str(fixture.job_id),
        project_id=str(fixture.project_id), report_id=str(fixture.report_id),
        schedule_version_id=str(fixture.schedule_id))
    coordinator = None
    if execution:
        sessions = sessionmaker(fixture.engine, expire_on_commit=False)
        with sessions.begin() as db:
            db.add(AgentRun(id=UUID(initial.run_id), job_id=fixture.job_id,
                graph_version="report-analysis-v2", state_schema_version="agent-state-v2",
                framework_version=FRAMEWORK_VERSION, thread_id=initial.run_id,
                execution_mode="graph", state="created", counters={}, model_metadata={},
                prompt_metadata={}, config_metadata={}))
        coordinator = HierarchyExecution(sessions, initial, ensure_active=lambda: None)
        model = coordinator.model({"extraction": fixture.context.model_callable,
                                   "selection": fixture.context.model_callable})
        fixture.context = replace(fixture.context, model_callable=model)
    return fixture, initial, coordinator


@pytest.mark.parametrize("extraction_failures,selection_failures", [(0, 0), (1, 0), (0, 1), (2, 0), (0, 2)])
def test_nested_hierarchy_preserves_repair_and_review(extraction_failures, selection_failures):
    fixture, initial, execution = setup(True)
    tools = FaultingTools(fixture.tools(), extraction_failures=extraction_failures,
                         selection_failures=selection_failures)
    graph = build_hierarchical_report_graph(MemorySaver(), tools, execution)
    result = graph.invoke(initial.model_dump(mode="json"), {"configurable": {"thread_id": initial.run_id}})
    state = HierarchicalAgentState.model_validate(result)
    expected = "failed" if max(extraction_failures, selection_failures) == 2 else "ready_for_review"
    assert state.terminal_state == expected
    assert len(fixture.persist_calls) == (expected == "ready_for_review")
    with execution.sessions() as db:
        tasks = list(db.scalars(select(AgentTask)))
        roles = {task.agent_role for task in tasks}
        assert {"root", "intake", "analysis", "extraction"} <= roles
        if expected == "ready_for_review":
            assert {"matching", "selection", "evidence", "review"} <= roles
        matching = [task for task in tasks if task.agent_role == "matching"]
        selections = [task for task in tasks if task.agent_role == "selection"]
        if selections:
            assert len(matching) == 1
            assert {task.parent_task_id for task in selections} == {matching[0].id}
            assert matching[0].status == ("succeeded" if expected == "ready_for_review" else "failed")
        usage = db.get(AgentRun, UUID(initial.run_id)).config_metadata["hierarchy_usage"]
        assert usage.get("model_calls", 0) == fixture.model_calls


def test_specialists_cannot_persist_or_approve():
    fixture, _, _ = setup()
    for role in ("extraction", "matching", "evidence"):
        scoped = ScopedTools(fixture.tools(), None, role)
        with pytest.raises(AttributeError):
            scoped.persist_review_proposals
        with pytest.raises(AttributeError):
            scoped.approve


def test_planner_rejects_unknown_and_out_of_order_actions():
    assert validated_decision(lambda **_: {"action": "analysis"}, "analysis") == "analysis"
    with pytest.raises(AgentToolError):
        validated_decision(lambda **_: {"action": "review"}, "analysis")
    with pytest.raises(AgentToolError):
        validated_decision(lambda **_: {"action": "approve"}, "analysis")


def test_root_budget_reservation_is_durable_and_failed_calls_consume():
    fixture, initial, execution = setup(True)
    model = execution.model({"extraction": lambda **_: (_ for _ in ()).throw(RuntimeError("provider"))})
    with pytest.raises(RuntimeError):
        model()
    reloaded = HierarchyExecution(execution.sessions, initial, ensure_active=lambda: None)
    reloaded.reserve("model_calls", 2)
    with pytest.raises(AgentToolError):
        reloaded.reserve("model_calls", 2)


def test_flag_controls_creation_only(monkeypatch):
    fixture = Fixture()
    sessions = sessionmaker(fixture.engine, expire_on_commit=False)
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_hierarchy_enabled", True)
    with sessions.begin() as db:
        run = _create_or_load_run(db, db.get(Job, fixture.job_id), clock=fixture.context.clock)
        assert run.graph_version == "report-analysis-v2"
    monkeypatch.setattr(settings, "agent_hierarchy_enabled", False)
    with sessions() as db:
        assert _create_or_load_run(db, db.get(Job, fixture.job_id), clock=fixture.context.clock).graph_version == "report-analysis-v2"


def test_shadow_has_identical_fixture_outcomes_and_cannot_write():
    from app.agent.shadow import compare_report
    from test_agent_graph import initial as legacy_initial
    fixture = Fixture()
    result = compare_report(legacy_initial(fixture), fixture.tools)
    assert result["observations_equal"] and result["selections_equal"] and result["terminal_equal"]
    assert result["legacy_counters"] == result["hierarchy_counters"]
    assert fixture.persist_calls == []


def test_illegal_planner_action_fails_before_specialists_or_persistence():
    fixture, initial, execution = setup(True)
    execution.planner = lambda **kwargs: {"action": "approve"}
    graph = build_hierarchical_report_graph(MemorySaver(), fixture.tools(), execution)
    result = graph.invoke(initial.model_dump(mode="json"), {"configurable": {"thread_id": initial.run_id}})
    assert result["terminal_state"] == "failed"
    assert result["validation_errors"][0]["code"] == "AGENT_PLANNER_INVALID"
    assert fixture.model_calls == 0
    assert fixture.persist_calls == []


def test_v2_state_roundtrip_retains_distinct_runtime_identity():
    from app.agent.state import encode_agent_state, decode_agent_state
    _, initial, _ = setup()
    decoded = decode_agent_state(encode_agent_state(initial))
    assert isinstance(decoded, HierarchicalAgentState)
    assert decoded == initial


def test_role_snapshot_does_not_carry_a_model_across_provider_boundaries(monkeypatch):
    fixture = Fixture()
    sessions = sessionmaker(fixture.engine, expire_on_commit=False)
    settings = get_settings()
    # Exercise the unset-model fallback regardless of the developer's local role model.
    monkeypatch.setattr(settings, "extraction_model", None)
    monkeypatch.setattr(settings, "agent_hierarchy_enabled", True)
    monkeypatch.setattr(settings, "selection_provider", "openrouter")
    monkeypatch.setattr(settings, "selection_model", None)
    monkeypatch.setattr(settings, "openrouter_model", "catalog/free:free")
    with sessions.begin() as db:
        job = db.get(Job, fixture.job_id)
        job.config_snapshot = {"provider": "groq", "model": "baseline-groq"}
        run = _create_or_load_run(db, job, clock=fixture.context.clock)
        assert run.config_metadata["roles"]["selection"]["model"] == "catalog/free:free"
        assert run.config_metadata["roles"]["extraction"]["model"] == "baseline-groq"
