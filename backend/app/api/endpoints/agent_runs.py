"""Read-only, project-scoped public status for bounded graph runs."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...agent.policy import public_stage
from ...agent.state import GRAPH_VERSION
from ...db.models import AgentRun, AgentStep, AgentTask, User
from ...db.session import get_session
from ...schemas.agent import (
    AgentCounters,
    AgentNode,
    AgentRunResponse,
    AgentRunState,
    AgentHierarchyUsage,
    AgentStepStatus,
    AgentTraceState,
    AgentTaskOutcome,
    AgentTaskRole,
    AgentTaskStatus,
)
from ..dependencies import current_user
from .jobs import _job_for_user

router = APIRouter(prefix="/jobs", tags=["agent-runs"])

# O-04 froze these exact package versions. Values stored in application rows are
# assertions, so the API only returns these constants when they match exactly.
_KNOWN_FRAMEWORK_VERSION = "langgraph-1.2.12/checkpoint-postgres-3.1.2"
_UNKNOWN_VERSION = "unrecognized"
_KNOWN_GRAPH_VERSIONS = frozenset({GRAPH_VERSION, "report-analysis-v2"})
_MAX_COUNTERS = {
    "node_executions": 16,
    "extraction_calls": 2,
    "selection_calls": 400,
    "corrective_retries": 2,
}

_SAFE_ERRORS = {
    "AGENT_FRAMEWORK_UNAVAILABLE": "The agent framework is unavailable.",
    "AGENT_STATE_INVALID": "The report analysis state is invalid.",
    "AGENT_STATE_TOO_LARGE": "The report analysis state exceeded its size limit.",
    "AGENT_STEP_LIMIT": "The report analysis exceeded its step limit.",
    "AGENT_OBSERVATION_LIMIT": "The report exceeded the observation limit.",
    "AGENT_REPAIR_LIMIT": "The correction retry limit was reached.",
    "AGENT_CHECKPOINT_FAILED": "The durable graph checkpoint operation failed.",
    "AGENT_CHECKPOINT_INCOMPATIBLE": "The saved graph state is incompatible.",
    "AGENT_TOOL_FAILED": "The report analysis tool failed safely.",
    "AGENT_RUN_CONFLICT": "Existing persisted output is incompatible with this run.",
    "AGENT_INTERNAL_ERROR": "The report analysis run failed safely.",
    "JOB_CANCELLED": "The job was cancelled.",
    "JOB_LEASE_LOST": "The job lease is no longer valid.",
    "SCHEDULE_VERSION_STALE": "The project schedule changed during this run.",
}


def _safe_error_code(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) and value in _SAFE_ERRORS else "AGENT_INTERNAL_ERROR"


def _safe_counters(value: object) -> AgentCounters:
    raw = value if isinstance(value, dict) else {}
    counters = {}
    for name, limit in _MAX_COUNTERS.items():
        count = raw.get(name)
        if type(count) is not int or not 0 <= count <= limit:
            raise ValueError("agent counters do not match the public contract")
        counters[name] = count
    return AgentCounters.model_validate(counters)


def _safe_version(value: object, expected: str) -> str:
    return expected if value == expected else _UNKNOWN_VERSION


def _safe_graph_version(value: object) -> str:
    return value if isinstance(value, str) and value in _KNOWN_GRAPH_VERSIONS else _UNKNOWN_VERSION


def _safe_tasks(rows: list[AgentTask]) -> list[AgentTaskStatus]:
    result = []
    for row in rows:
        try:
            role = AgentTaskRole(row.agent_role)
            state = AgentTraceState(row.status)
            outcome = AgentTaskOutcome(row.outcome) if row.outcome is not None else None
            result.append(AgentTaskStatus(id=row.id, parent_task_id=row.parent_task_id,
                role=role, status=state, attempt=row.attempt, outcome=outcome))
        except (TypeError, ValueError):
            # Task payloads and error text never cross the public boundary.
            continue
    return result


def _safe_hierarchy_usage(value: object) -> AgentHierarchyUsage | None:
    raw = value.get("hierarchy_usage") if isinstance(value, dict) else None
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("hierarchy usage is invalid")
    limits = {"delegations": 1300, "supervisor_transitions": 12,
              "model_calls": 806, "tool_calls": 1010}
    clean = {}
    for name, limit in limits.items():
        count = raw.get(name, 0)
        if type(count) is not int or not 0 <= count <= limit:
            raise ValueError("hierarchy usage is invalid")
        clean[name] = count
    return AgentHierarchyUsage.model_validate(clean)


def _safe_steps(rows: list[AgentStep], run_state: str) -> list[AgentStepStatus]:
    result = []
    for row in rows:
        try:
            node = AgentNode(row.node)
            state = AgentTraceState(row.state)
            terminal_state = run_state if node is AgentNode.record_failure else None
            label = public_stage(node.value, terminal_state)
            error_code = _safe_error_code(row.error_code) if state is AgentTraceState.failed else None
            result.append(AgentStepStatus(
                ordinal=row.ordinal,
                node=node,
                label=label,
                state=state,
                attempt=row.attempt,
                duration_ms=None if state is AgentTraceState.running else row.duration_ms,
                error_code=error_code,
            ))
        except (TypeError, ValueError):
            # Invalid legacy/corrupt trace fields cannot be represented by the
            # frozen public schema and are omitted without exposing their values.
            continue
    return result


@router.get("/{job_id}/agent-run", response_model=AgentRunResponse)
def agent_run_status(
    job_id: UUID,
    response: Response,
    db: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> AgentRunResponse:
    """Return sanitized trace status for a graph run owned by this project member."""
    job = _job_for_user(db, job_id, user)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    run = db.scalar(select(AgentRun).where(
        AgentRun.job_id == job.id,
        AgentRun.execution_mode == "graph",
    ))
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    rows = list(db.scalars(
        select(AgentStep)
        .where(AgentStep.run_id == run.id)
        .order_by(AgentStep.ordinal, AgentStep.id)
    ))
    task_rows = list(db.scalars(
        select(AgentTask)
        .where(AgentTask.run_id == run.id)
        .order_by(AgentTask.started_at, AgentTask.id)
        .limit(1301)
    ))
    state = AgentRunState(run.state)
    error_code = _safe_error_code(run.error_code) if state in {
        AgentRunState.failed, AgentRunState.stale, AgentRunState.cancelled
    } else None
    error_message = _SAFE_ERRORS.get(error_code) if error_code else None
    if state is AgentRunState.cancelled:
        current_stage = None
    elif run.current_node is None:
        current_stage = None
    else:
        try:
            current_stage = public_stage(run.current_node, state.value)
        except (TypeError, ValueError):
            current_stage = None
    response.headers["Cache-Control"] = "no-store"
    try:
        counters = _safe_counters(run.counters)
        hierarchy_usage = _safe_hierarchy_usage(run.config_metadata)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail={"code": "AGENT_STATUS_INVALID"}) from exc
    return AgentRunResponse(
        id=run.id,
        job_id=run.job_id,
        graph_version=_safe_graph_version(run.graph_version),
        framework_version=_safe_version(run.framework_version, _KNOWN_FRAMEWORK_VERSION),
        state=state,
        current_stage=current_stage,
        counters=counters,
        steps=_safe_steps(rows, state.value),
        tasks=_safe_tasks(task_rows),
        hierarchy_usage=hierarchy_usage,
        error_code=error_code,
        error_message=error_message,
        started_at=run.started_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
    )
