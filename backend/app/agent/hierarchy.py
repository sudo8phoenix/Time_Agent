"""Version two report hierarchy with scoped delegation and nested checkpoints."""
from __future__ import annotations

from datetime import timedelta, timezone
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select

from ..db.models import AgentRun
from . import policy
from .contracts import AgentRole, TaskEnvelope, TaskResult, TaskOutcome, TaskError, stable_task_id
from .nodes import _nodes, conditional_routers
from .state import HierarchicalAgentState, parse_agent_state, ValidationErrorRecord
from .task_store import TaskStore
from .tools import AgentToolError

GRAPH_VERSION = "report-analysis-v2"
STATE_SCHEMA_VERSION = "agent-state-v2"


class SupervisorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["intake", "analysis", "review"]


def validated_decision(model_call, expected: str) -> str:
    """A planner can only confirm the one legal next supervisor; fail closed."""
    response = model_call(system="Choose only the supplied legal next supervisor. Return JSON with action.",
        user={"legal_actions": [expected]}, schema=SupervisorDecision.model_json_schema())
    value = response.value if hasattr(response, "value") else response
    try:
        decision = SupervisorDecision.model_validate(value)
    except ValidationError:
        raise AgentToolError("AGENT_PLANNER_INVALID", "The planner proposed an invalid supervisor.") from None
    if decision.action != expected:
        raise AgentToolError("AGENT_PLANNER_INVALID", "The planner proposed an illegal supervisor.")
    return decision.action


class HierarchyExecution:
    """Ephemeral coordinator; durable reservations survive failed calls and restarts."""

    def __init__(self, session_factory, initial, *, ensure_active, planner=None, clock=None):
        self.sessions = session_factory
        self.initial = initial
        self.store = TaskStore(session_factory, UUID(initial.run_id))
        self.ensure_active = ensure_active
        self.planner = planner
        self.clock = clock
        self.active_role = "extraction"
        self.active_task = None
        self.envelopes = {}
        self.task_usage = {}
        with self.sessions() as db:
            started = db.get(AgentRun, UUID(initial.run_id)).started_at
            self.deadline = (started.replace(tzinfo=timezone.utc) if started.tzinfo is None else started) + timedelta(seconds=1800)
        self.root = self.envelope(AgentRole.ROOT)
        self.store.begin(self.root, input_fingerprint=self.fingerprint({"run": initial.run_id}))

    @staticmethod
    def fingerprint(value):
        return sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

    def reserve(self, counter, limit):
        self.ensure_active()
        with self.sessions.begin() as db:
            run = db.scalar(select(AgentRun).where(AgentRun.id == UUID(self.initial.run_id)).with_for_update())
            metadata = dict(run.config_metadata or {})
            usage = dict(metadata.get("hierarchy_usage", {}))
            # A single run deadline is pinned at run creation, never at child creation.
            now = self.clock() if self.clock else None
            started = run.started_at
            if now is not None:
                if started.tzinfo is None:
                    started = started.replace(tzinfo=now.tzinfo)
                if (now - started).total_seconds() > 1800:
                    raise AgentToolError("AGENT_DEADLINE", "The root run deadline is exhausted.")
            if usage.get(counter, 0) >= limit:
                raise AgentToolError("AGENT_BUDGET_EXHAUSTED", "The root run budget is exhausted.")
            usage[counter] = usage.get(counter, 0) + 1
            metadata["hierarchy_usage"] = usage
            run.config_metadata = metadata

    def envelope(self, role, parent=None, *, observation_key=None, attempt=1):
        task = TaskEnvelope(task_id=stable_task_id(run_id=UUID(self.initial.run_id),
            parent_task_id=parent.task_id if parent else None, agent_role=role,
            attempt=attempt, observation_key=observation_key),
            parent_task_id=parent.task_id if parent else None, run_id=UUID(self.initial.run_id),
            agent_role=role, project_id=UUID(self.initial.project_id), source_id=UUID(self.initial.report_id),
            schedule_version_id=UUID(self.initial.schedule_version_id), attempt=attempt,
            observation_key=observation_key, deadline=self.deadline,
            input_references=[f"source:{self.initial.report_id}", f"schedule:{self.initial.schedule_version_id}"] +
                ([f"observation:{observation_key}"] if observation_key else []),
            budget_allocation={"model_calls": 806, "tool_calls": 1010, "supervisor_transitions": 12})
        self.envelopes[task.task_id] = task
        return task

    def finish(self, task, *, error=None, unresolved=False):
        outcome = TaskOutcome.FAILED if error else TaskOutcome.UNRESOLVED if unresolved else TaskOutcome.COMPLETED
        self.store.finish(task, TaskResult(**{key: getattr(task, key) for key in (
            "task_id", "parent_task_id", "run_id", "agent_role", "project_id", "source_id", "schedule_version_id")},
            actual_usage=self.task_usage.get(task.task_id, {}),
            outcome=outcome, error=TaskError(code=getattr(error, "code", "AGENT_TOOL_FAILED")) if error else None,
            output_references=[f"checkpoint:{task.run_id}"]))

    def run(self, task, function, fingerprint):
        self.reserve("delegations", 1300)
        record = self.store.begin(task, input_fingerprint=fingerprint)
        previous = self.active_task
        self.active_task = task
        try:
            value = function()
        except BaseException:
            # A worker interruption leaves the attempt resumable. Domain failures
            # are returned as typed state and finalized in the success branch.
            raise
        else:
            failed = isinstance(value, dict) and value.get("next_action") == "fail"
            if not record.reused:
                mapping = getattr(getattr(value, "mapping_state", None), "value", None)
                self.finish(task, error=AgentToolError("AGENT_TOOL_FAILED", "Task failed safely.") if failed else None,
                    unresolved=mapping is not None and mapping != "suggested")
            return value
        finally:
            self.active_task = previous

    def supervisor(self, role, graph):
        def invoke(raw, config):
            state = parse_agent_state(raw) if isinstance(raw, dict) else raw
            task = self.envelope(AgentRole(role), self.root)
            def execute():
                self.reserve("supervisor_transitions", 12)
                if self.planner:
                    self.reserve("model_calls", 806)
                    try:
                        validated_decision(self.planner, role)
                    except AgentToolError:
                        raise
                    except Exception:
                        raise AgentToolError("AGENT_PLANNER_FAILED", "The planner failed safely.") from None
                return graph.invoke(state.model_dump(mode="json"), config)
            # Pin to identity: nested checkpoint input evolves during resume.
            try:
                return self.run(task, execute, self.fingerprint({"role": role, "run": state.run_id}))
            except AgentToolError as error:
                return {**state.model_dump(mode="json"), "next_action": "fail",
                    "validation_errors": [ValidationErrorRecord(stage=role, code=error.code,
                        message=error.safe_message, retryable=False).model_dump(mode="json")]}
        return invoke

    def model(self, models):
        def call(**kwargs):
            self.reserve("model_calls", 806)
            if self.active_task:
                usage = self.task_usage.setdefault(self.active_task.task_id, {})
                usage["model_calls"] = usage.get("model_calls", 0) + 1
            return models[self.active_role](**kwargs)
        return call


class ScopedTools:
    """Role-specific capability view; denied methods never reach domain tools."""

    METHODS = {
        "intake": {"load_job_context"},
        "extraction": {"extract_observations", "report_metadata"},
        "matching": {"retrieve_candidates", "select_candidate", "model_metadata"},
        "evidence": {"validate_proposal_drafts"},
        "review": {"persist_review_proposals"},
    }

    def __init__(self, tools, execution, role):
        self.tools, self.execution, self.role = tools, execution, role

    def __getattr__(self, name):
        if name not in self.METHODS[self.role]:
            raise AttributeError(f"{self.role} has no capability {name}")
        value = getattr(self.tools, name)
        if not callable(value) or self.execution is None:
            return value
        def invoke(*args, **kwargs):
            execution = self.execution
            execution.reserve("tool_calls", 1010)
            parent = execution.active_task
            key = args[0] if name in {"retrieve_candidates", "select_candidate"} else None
            role = AgentRole.SELECTION if name == "select_candidate" else AgentRole(self.role)
            # Matching owns retrieval and delegates selection, one scope per observation.
            if self.role == "matching":
                matching = execution.envelope(AgentRole.MATCHING,
                    execution.envelope(AgentRole.ANALYSIS, execution.root), observation_key=key)
                execution.store.begin(matching, input_fingerprint=execution.fingerprint({"observation": key}))
                parent = matching
                if name == "retrieve_candidates":
                    execution.active_role = "selection"
                    previous = execution.active_task
                    execution.active_task = matching
                    try:
                        return value(*args, **kwargs)
                    finally:
                        execution.active_task = previous
            if role == AgentRole.INTAKE or role == AgentRole.REVIEW:
                return value(*args, **kwargs)
            # Repairs have distinct stable task identities from the persisted attempt counter.
            from ..db.models import AgentTask
            with execution.sessions() as db:
                from sqlalchemy import func
                attempt = int(db.scalar(select(func.count()).select_from(AgentTask).where(
                    AgentTask.run_id == UUID(execution.initial.run_id), AgentTask.agent_role == role.value,
                    AgentTask.observation_key == key))) + 1
            task = execution.envelope(role, parent, observation_key=key, attempt=attempt)
            execution.active_role = "selection" if role == AgentRole.SELECTION else "extraction"
            try:
                return execution.run(task, lambda: value(*args, **kwargs),
                    execution.fingerprint({"name": name, "args": args}))
            finally:
                if self.role == "matching":
                    execution.finish(matching)
        return invoke


def build_hierarchical_report_graph(checkpointer, tools, execution=None):
    """Compile nested supervisor graphs using the installed LangGraph API."""
    def nodes(role):
        domain = _nodes(ScopedTools(tools, execution, role), policy)
        def boundary(function):
            def invoke(raw):
                state = parse_agent_state(raw) if isinstance(raw, dict) else raw
                if execution:
                    execution.ensure_active()
                if state.fragment_ids:
                    tools.rehydrate_provenance(state)
                return function(state)
            return invoke
        return {name: boundary(function) for name, function in domain.items()}
    intake_nodes, extraction, matching, evidence, review = [nodes(role) for role in (
        "intake", "extraction", "matching", "evidence", "review")]
    _, extraction_route, selection_route, _ = conditional_routers(policy)

    match = StateGraph(HierarchicalAgentState)
    for name in ("retrieve", "select", "repair_selection"):
        match.add_node(name, matching[name], input_schema=HierarchicalAgentState)
    match.add_node("validate_selection", evidence["validate_selection"], input_schema=HierarchicalAgentState)
    match.add_edge(START, "retrieve")
    match.add_edge("retrieve", "select")
    match.add_edge("select", "validate_selection")
    match.add_edge("repair_selection", "validate_selection")
    match.add_conditional_edges("validate_selection", selection_route,
        {"persist": END, "repair_selection": "repair_selection", "record_failure": END})

    analysis = StateGraph(HierarchicalAgentState)
    for name in ("extract", "validate_extraction", "repair_extraction"):
        analysis.add_node(name, extraction[name], input_schema=HierarchicalAgentState)
    analysis.add_node("matching", match.compile())
    analysis.add_edge(START, "extract")
    analysis.add_edge("extract", "validate_extraction")
    analysis.add_edge("repair_extraction", "validate_extraction")
    analysis.add_conditional_edges("validate_extraction", extraction_route,
        {"retrieve": "matching", "repair_extraction": "repair_extraction", "record_failure": END})
    analysis.add_edge("matching", END)

    intake = StateGraph(HierarchicalAgentState)
    intake.add_node("load_context", intake_nodes["load_context"], input_schema=HierarchicalAgentState)
    intake.add_edge(START, "load_context")
    intake.add_edge("load_context", END)
    preparation = StateGraph(HierarchicalAgentState)
    preparation.add_node("persist", review["persist"], input_schema=HierarchicalAgentState)
    preparation.add_edge(START, "persist")
    preparation.add_edge("persist", END)
    root = StateGraph(HierarchicalAgentState)
    for role, graph in (("intake", intake.compile()), ("analysis", analysis.compile()), ("review", preparation.compile())):
        root.add_node(role, execution.supervisor(role, graph) if execution else graph)
    # Finalizers are state-only operations, without specialist capabilities.
    finals = _nodes(ScopedTools(tools, execution, "review"), policy)
    root.add_node("finalize", finals["finalize"], input_schema=HierarchicalAgentState)
    root.add_node("record_failure", finals["record_failure"], input_schema=HierarchicalAgentState)
    root.add_edge(START, "intake")
    for source, target in (("intake", "analysis"), ("analysis", "review"), ("review", "finalize")):
        root.add_conditional_edges(source, lambda state: "fail" if state.next_action == "fail" else "continue",
            {"fail": "record_failure", "continue": target})
    root.add_edge("finalize", END)
    root.add_edge("record_failure", END)
    return root.compile(checkpointer=checkpointer)
