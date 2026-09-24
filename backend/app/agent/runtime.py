"""Lease-owned LangGraph execution with PostgreSQL checkpoints and durable resume."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import version
import os
from typing import Any, Callable, Iterator
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Checkpoint deserialization must never import arbitrary Python objects.
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.postgres import PostgresSaver

from ..db.models import (
    Activity,
    ActivityState,
    AgentRun,
    Fragment,
    Job,
    Observation as DBObservation,
    Project,
    Proposal as DBProposal,
)
from ..jobs.service import publish_stage
from ..llm.extract import extract_fragments
from ..matching.selection import select_candidate
from ..retrieval.index import retrieve_candidates
from ..settings import get_settings
from .context import AgentRuntimeContext
from .graph import build_report_analysis_graph
from .state import (
    GRAPH_VERSION,
    STATE_SCHEMA_VERSION,
    AgentCounters,
    AgentState,
    AgentStateError,
    ValidationErrorRecord,
    create_initial_state,
    validate_identity_transition,
)
from .telemetry import TelemetryRecorder, TelemetryTools
from .tools import AgentToolError, AgentTools, PersistenceResult

FRAMEWORK_VERSION = (
    f"langgraph-{version('langgraph')}/checkpoint-postgres-"
    f"{version('langgraph-checkpoint-postgres')}"
)
SAFE_ERRORS = {
    "AGENT_CHECKPOINT_FAILED": "The durable graph checkpoint operation failed.",
    "AGENT_CHECKPOINT_INCOMPATIBLE": "The saved graph state is incompatible.",
    "AGENT_INTERNAL_ERROR": "The report analysis run failed safely.",
    "AGENT_RUN_CONFLICT": "Existing persisted output is incompatible with this run.",
    "JOB_LEASE_LOST": "The job lease is no longer valid.",
    "SCHEDULE_VERSION_STALE": "The project schedule changed during this run.",
}


class AgentRuntimeError(RuntimeError):
    def __init__(self, code: str, safe_message: str | None = None):
        self.code = code
        self.safe_message = safe_message or SAFE_ERRORS.get(code, SAFE_ERRORS["AGENT_INTERNAL_ERROR"])
        super().__init__(self.safe_message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _checkpoint_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
        raise AgentRuntimeError(
            "AGENT_FRAMEWORK_UNAVAILABLE", "Graph mode requires PostgreSQL checkpoints."
        )
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def _checkpoint_scope(database_url: str, checkpointer: Any | None) -> Iterator[Any]:
    if checkpointer is not None:
        yield checkpointer
        return
    # setup() is deliberately absent: Alembic/deployment owns saver DDL.
    with PostgresSaver.from_conn_string(_checkpoint_url(database_url)) as saver:
        yield saver


def _create_or_load_run(db: Session, job: Job, *, clock: Callable[[], datetime]) -> AgentRun:
    run = db.scalar(select(AgentRun).where(AgentRun.job_id == job.id).with_for_update())
    if run is None:
        run_id = uuid4()
        run = AgentRun(
            id=run_id,
            job_id=job.id,
            graph_version=GRAPH_VERSION,
            state_schema_version=STATE_SCHEMA_VERSION,
            framework_version=FRAMEWORK_VERSION,
            thread_id=str(run_id),
            execution_mode="graph",
            state="created",
            current_node="load_context",
            counters={
                "node_executions": 0,
                "extraction_calls": 0,
                "selection_calls": 0,
                "corrective_retries": 0,
            },
            model_metadata={},
            prompt_metadata={},
            config_metadata={},
            started_at=clock(),
        )
        db.add(run)
        try:
            db.flush()
        except IntegrityError as exc:
            raise AgentRuntimeError("AGENT_RUN_CONFLICT") from exc
    if (
        run.graph_version != GRAPH_VERSION
        or run.state_schema_version != STATE_SCHEMA_VERSION
        or run.framework_version != FRAMEWORK_VERSION
        or run.thread_id != str(run.id)
        or run.execution_mode != "graph"
    ):
        raise AgentRuntimeError("AGENT_CHECKPOINT_INCOMPATIBLE")
    return run


def _ensure_active(
    session_factory,
    job_id: UUID,
    token: str,
    *,
    job_for_heartbeat: Job,
    heartbeat_callback: Callable[[Job, str], bool] | None,
    should_stop: Callable[[], bool] | None,
    clock: Callable[[], datetime],
) -> None:
    if should_stop and should_stop():
        from ..jobs.worker import WorkerShutdown

        raise WorkerShutdown()
    if heartbeat_callback and not heartbeat_callback(job_for_heartbeat, token):
        raise AgentRuntimeError("JOB_LEASE_LOST")
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise AgentRuntimeError("JOB_LEASE_LOST")
        now = clock()
        expires = job.lease_expires_at
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if (
            job.state != "running"
            or job.lease_token != token
            or expires is None
            or expires <= now
        ):
            raise AgentRuntimeError("JOB_LEASE_LOST")
        project = db.get(Project, job.project_id)
        if project is None or project.active_schedule_version_id != job.schedule_version_id:
            raise AgentRuntimeError("SCHEDULE_VERSION_STALE")


def _model_callable() -> Callable[..., Any]:
    from ..llm.ollama import OllamaChatAdapter

    settings = get_settings()
    adapter = OllamaChatAdapter(
        settings.ollama_base_url,
        settings.ollama_model,
        bearer_token=(
            settings.ollama_api_key.get_secret_value() if settings.ollama_api_key else None
        ),
    )
    return adapter.chat


def _json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _effects(observation: Any) -> dict[str, Any]:
    if observation.event_type.value != "actual_progress":
        return {}
    result: dict[str, Any] = {}
    if observation.quantity is not None:
        result["quantity"] = str(observation.quantity)
    if observation.unit is not None:
        result["unit"] = observation.unit.value
    if observation.work_date is not None:
        result["effective_date"] = observation.work_date.isoformat()
    return result


def _persisted_rows(db: Session, job_id: UUID) -> list[DBObservation]:
    return list(db.scalars(select(DBObservation).where(
        DBObservation.job_id == job_id
    ).order_by(DBObservation.ordinal, DBObservation.id)))


def _verify_existing_output(db: Session, state: AgentState, rows: list[DBObservation]) -> None:
    if len(rows) != len(state.observation_drafts):
        raise AgentToolError("AGENT_RUN_CONFLICT", SAFE_ERRORS["AGENT_RUN_CONFLICT"])
    keys = [f"obs-{index:04d}" for index in range(1, len(rows) + 1)]
    for row, key, observation in zip(rows, keys, state.observation_drafts, strict=True):
        evidence = [item.model_dump(mode="json") for item in observation.evidence]
        if row.fields != observation.model_dump(mode="json") or row.field_evidence != {
            "evidence": evidence
        }:
            raise AgentToolError("AGENT_RUN_CONFLICT", SAFE_ERRORS["AGENT_RUN_CONFLICT"])
        proposal = db.scalar(select(DBProposal).where(DBProposal.observation_id == row.id))
        expected = state.selection_drafts[key]
        if proposal is None or (
            str(proposal.chosen_activity_id) if proposal.chosen_activity_id else None
        ) != (str(expected.candidate_id) if expected.candidate_id else None):
            raise AgentToolError("AGENT_RUN_CONFLICT", SAFE_ERRORS["AGENT_RUN_CONFLICT"])
        if (
            proposal.candidates != [item.model_dump(mode="json") for item in expected.candidates]
            or proposal.mapping_state != expected.mapping_state.value
            or proposal.match_strength != expected.match_strength.value
            or proposal.review_state != expected.review_state.value
            or proposal.proposed_effects != _effects(observation)
        ):
            raise AgentToolError("AGENT_RUN_CONFLICT", SAFE_ERRORS["AGENT_RUN_CONFLICT"])


def _persistence_callback(session_factory, token: str, state: AgentState, *, idempotency_key: str):
    if idempotency_key != state.run_id:
        raise AgentToolError("AGENT_RUN_CONFLICT", SAFE_ERRORS["AGENT_RUN_CONFLICT"])
    try:
        with session_factory.begin() as db:
            run = db.get(AgentRun, UUID(state.run_id))
            job = db.get(Job, UUID(state.job_id))
            project = db.get(Project, UUID(state.project_id))
            if run is None or job is None or project is None or run.job_id != job.id:
                raise AgentToolError("AGENT_RUN_CONFLICT", SAFE_ERRORS["AGENT_RUN_CONFLICT"])
            now = _now()
            expires = job.lease_expires_at
            if expires is not None and expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if (
                job.state != "running"
                or job.lease_token != token
                or expires is None
                or expires <= now
            ):
                raise AgentToolError("JOB_LEASE_LOST", SAFE_ERRORS["JOB_LEASE_LOST"])
            if project.active_schedule_version_id != job.schedule_version_id:
                raise AgentToolError(
                    "SCHEDULE_VERSION_STALE", SAFE_ERRORS["SCHEDULE_VERSION_STALE"]
                )
            existing = _persisted_rows(db, job.id)
            if existing:
                _verify_existing_output(db, state, existing)
                return PersistenceResult(
                    extracted_count=len(existing),
                    proposal_count=len(state.selection_drafts),
                    already_persisted=True,
                )

            fragments = {
                str(row.id): row
                for row in db.scalars(select(Fragment).where(Fragment.report_id == job.report_id))
            }
            activities = {
                str(row.id): row
                for row in db.scalars(select(Activity).where(
                    Activity.schedule_version_id == job.schedule_version_id,
                    Activity.is_leaf.is_(True),
                ))
            }
            state_rows = {
                row.activity_id: row
                for row in db.scalars(select(ActivityState).where(
                    ActivityState.activity_id.in_([row.id for row in activities.values()])
                ))
            }
            for index, observation in enumerate(state.observation_drafts):
                key = f"obs-{index + 1:04d}"
                source_id = observation.evidence[0].fragment_id
                source = fragments.get(source_id)
                selection = state.selection_drafts.get(key)
                if source is None or selection is None:
                    raise AgentToolError(
                        "AGENT_RUN_CONFLICT", SAFE_ERRORS["AGENT_RUN_CONFLICT"]
                    )
                ordinal = source.ordinal * 1000 + index
                row = DBObservation(
                    job_id=job.id,
                    fragment_id=source.id,
                    ordinal=ordinal,
                    fields=observation.model_dump(mode="json"),
                    field_evidence={
                        "evidence": [item.model_dump(mode="json") for item in observation.evidence]
                    },
                )
                db.add(row)
                db.flush()
                chosen = activities.get(str(selection.candidate_id)) if selection.candidate_id else None
                if selection.candidate_id is not None and chosen is None:
                    raise AgentToolError(
                        "AGENT_RUN_CONFLICT", SAFE_ERRORS["AGENT_RUN_CONFLICT"]
                    )
                db.add(DBProposal(
                    observation_id=row.id,
                    project_id=job.project_id,
                    chosen_activity_id=chosen.id if chosen else None,
                    candidates=[item.model_dump(mode="json") for item in selection.candidates],
                    mapping_state=selection.mapping_state.value,
                    match_strength=selection.match_strength.value,
                    review_state=selection.review_state.value,
                    warnings=list(observation.warnings),
                    proposed_effects=_effects(observation),
                    base_activity_revision=(state_rows.get(chosen.id).revision if chosen and state_rows.get(chosen.id) else 0),
                ))
            job.extracted_count = len(state.observation_drafts)
            job.proposal_count = len(state.selection_drafts)
            db.flush()
            return PersistenceResult(
                extracted_count=len(state.observation_drafts),
                proposal_count=len(state.selection_drafts),
                already_persisted=False,
            )
    except AgentToolError:
        raise
    except IntegrityError:
        # A transaction outcome from a previous worker is checked on the next
        # resume; never continue after an ambiguous or partial local flush.
        raise AgentToolError("AGENT_RUN_CONFLICT", SAFE_ERRORS["AGENT_RUN_CONFLICT"]) from None
    except Exception:
        raise AgentToolError("AGENT_TOOL_FAILED", "Persistence failed safely.") from None


def _terminal_error(state: AgentState) -> tuple[str | None, str | None]:
    if state.terminal_state == "ready_for_review":
        return None, None
    if state.validation_errors:
        error = state.validation_errors[0]
        return error.code, error.message
    code = "SCHEDULE_VERSION_STALE" if state.terminal_state == "stale" else "AGENT_INTERNAL_ERROR"
    return code, SAFE_ERRORS[code]


def _finalize(session_factory, job_id: UUID, token: str, run_id: UUID, state: AgentState) -> dict[str, Any]:
    now = _now()
    with session_factory.begin() as db:
        run = db.get(AgentRun, run_id)
        job = db.get(Job, job_id)
        if run is None or job is None:
            raise AgentRuntimeError("AGENT_RUN_CONFLICT")
        observations = int(db.scalar(select(func.count()).select_from(DBObservation).where(
            DBObservation.job_id == job_id
        )) or 0)
        proposals = int(db.scalar(select(func.count()).select_from(DBProposal).join(
            DBObservation, DBProposal.observation_id == DBObservation.id
        ).where(DBObservation.job_id == job_id)) or 0)
        terminal = state.terminal_state or "failed"
        error_code, error_message = _terminal_error(state)
        published = publish_stage(
            db,
            job_id,
            token,
            stage="persist",
            state=terminal,
            extracted_count=observations,
            proposal_count=proposals,
            error_code=error_code,
            error_message=error_message,
            now=now,
        )
        if published.state == "stale":
            terminal = "stale"
            error_code = published.error_code or "SCHEDULE_VERSION_STALE"
            error_message = published.error_message or SAFE_ERRORS["SCHEDULE_VERSION_STALE"]
        run.state = terminal
        run.current_node = "finalize" if terminal == "ready_for_review" else "record_failure"
        run.counters = state.counters.model_dump(mode="json")
        run.updated_at = now
        run.completed_at = now
        run.error_code = error_code
        run.error_message = error_message
        metadata = state.model_metadata
        job.model_version = (
            f"{metadata.model_tag}:{metadata.model_digest}"
            if metadata.model_tag and metadata.model_digest
            else metadata.model_tag
        )
        job.prompt_version = metadata.selection_prompt_version or metadata.extraction_prompt_version
        job.config_version = metadata.settings_hash
        return {
            "stage": "persist",
            "state": terminal,
            "extracted_count": observations,
            "proposal_count": proposals,
            "error_code": error_code,
            "error_message": error_message,
            "published": True,
        }


def _failed_state(state: AgentState, code: str, message: str, *, stale: bool = False) -> AgentState:
    return state.model_copy(update={
        "validation_errors": [ValidationErrorRecord(
            stage="runtime", code=code, message=message, retryable=False
        )],
        "next_action": "fail",
        "terminal_state": "stale" if stale else "failed",
    })


def process_job_with_graph(
    db: Session,
    job: Job,
    *,
    token: str,
    session_factory,
    database_url: str | None = None,
    should_stop: Callable[[], bool] | None = None,
    heartbeat_callback: Callable[[Job, str], bool] | None = None,
    model_callable: Callable[..., Any] | None = None,
    embedder: Callable[..., Any] | None = None,
    extraction_service: Callable[..., Any] = extract_fragments,
    retrieval_service: Callable[..., Any] = retrieve_candidates,
    selection_service: Callable[..., Any] = select_candidate,
    checkpointer: Any | None = None,
    clock: Callable[[], datetime] = _now,
) -> dict[str, Any]:
    """Create or durably resume the single graph run owned by ``token``."""
    try:
        run = _create_or_load_run(db, job, clock=clock)
    except AgentRuntimeError as exc:
        db.rollback()
        with session_factory() as lookup:
            existing = lookup.scalar(select(AgentRun).where(AgentRun.job_id == job.id))
        if existing is None:
            raise
        incompatible = create_initial_state(
            run_id=str(existing.id),
            job_id=str(job.id),
            project_id=str(job.project_id),
            report_id=str(job.report_id),
            schedule_version_id=str(job.schedule_version_id),
        )
        return _finalize(
            session_factory,
            job.id,
            token,
            existing.id,
            _failed_state(incompatible, exc.code, exc.safe_message),
        )
    db.commit()  # saver and telemetry sessions must see the run record
    if run.state == "ready_for_review":
        return {
            "stage": "persist", "state": "ready_for_review",
            "extracted_count": job.extracted_count, "proposal_count": job.proposal_count,
            "published": job.state == "ready_for_review",
        }
    initial = create_initial_state(
        run_id=str(run.id),
        job_id=str(job.id),
        project_id=str(job.project_id),
        report_id=str(job.report_id),
        schedule_version_id=str(job.schedule_version_id),
    )
    context = AgentRuntimeContext(
        session_factory=session_factory,
        lease_token=token,
        model_callable=model_callable or _model_callable(),
        embedder=embedder,
        heartbeat_callback=heartbeat_callback or (lambda *_: True),
        shutdown_callback=should_stop or (lambda: False),
        clock=clock,
    )
    base_tools = AgentTools(
        context,
        extraction_service=extraction_service,
        retrieval_service=retrieval_service,
        selection_service=selection_service,
        persistence_callback=lambda state, **kwargs: _persistence_callback(
            session_factory, token, state, **kwargs
        ),
    )
    recorder = TelemetryRecorder(session_factory, run.id, clock=clock)
    tools = TelemetryTools(base_tools, recorder)
    config = {"configurable": {"thread_id": str(run.id)}}
    current = initial

    try:
        _ensure_active(
            session_factory, job.id, token, job_for_heartbeat=job,
            heartbeat_callback=heartbeat_callback, should_stop=should_stop, clock=clock,
        )
        with _checkpoint_scope(database_url or get_settings().database_url, checkpointer) as saver:
            graph = build_report_analysis_graph(saver, tools)
            try:
                snapshot = graph.get_state(config)
            except Exception as exc:
                raise AgentRuntimeError("AGENT_CHECKPOINT_FAILED") from exc
            if snapshot.values:
                try:
                    current = AgentState.model_validate(snapshot.values)
                    validate_identity_transition(initial, current)
                    tools.rehydrate_provenance(current)
                except (AgentStateError, AgentToolError, ValueError) as exc:
                    raise AgentRuntimeError("AGENT_CHECKPOINT_INCOMPATIBLE") from exc
                next_nodes = tuple(snapshot.next)
                recorder.reconcile_checkpoint(next_nodes, current)
                graph_input = None
            else:
                next_nodes = ("load_context",)
                graph_input = initial

            # A synchronous saver failure after the domain transaction can
            # leave the last readable checkpoint with no scheduled task even
            # though the persisted state says ``persist``.  Under the new
            # lease, re-run only the idempotent persistence verifier and the
            # state-only finalizer; never repeat extraction or selection.
            if (
                not next_nodes
                and current.terminal_state is None
                and current.next_action == "persist"
            ):
                recorder.begin_step("persist", current)
                tools.persist_review_proposals(current)
                counters = current.counters.model_dump(mode="python")
                counters["node_executions"] += 1
                current = current.model_copy(update={
                    "counters": AgentCounters.model_validate(counters),
                    "validation_errors": [],
                })
                recorder.finish_step(current)
                recorder.begin_step("finalize", current)
                counters = current.counters.model_dump(mode="python")
                counters["node_executions"] += 1
                current = current.model_copy(update={
                    "counters": AgentCounters.model_validate(counters),
                    "terminal_state": "ready_for_review",
                })
                recorder.finish_step(current)

            if next_nodes:
                events = graph.stream(
                    graph_input, config, stream_mode="updates", durability="sync"
                )
                try:
                    while next_nodes:
                        expected = next_nodes[0]
                        _ensure_active(
                            session_factory, job.id, token, job_for_heartbeat=job,
                            heartbeat_callback=heartbeat_callback, should_stop=should_stop,
                            clock=clock,
                        )
                        recorder.begin_step(expected, current)
                        try:
                            event = next(events)
                        except StopIteration as exc:
                            raise AgentRuntimeError("AGENT_CHECKPOINT_FAILED") from exc
                        except Exception as exc:
                            raise AgentRuntimeError("AGENT_CHECKPOINT_FAILED") from exc
                        node, _update = next(iter(event.items()))
                        if node != expected or len(event) != 1:
                            raise AgentRuntimeError("AGENT_CHECKPOINT_INCOMPATIBLE")
                        try:
                            snapshot = graph.get_state(config)
                            resumed = AgentState.model_validate(snapshot.values)
                            validate_identity_transition(current, resumed)
                        except Exception as exc:
                            raise AgentRuntimeError("AGENT_CHECKPOINT_FAILED") from exc
                        recorder.finish_step(resumed)
                        current = resumed
                        next_nodes = tuple(snapshot.next)
                        _ensure_active(
                            session_factory, job.id, token, job_for_heartbeat=job,
                            heartbeat_callback=heartbeat_callback, should_stop=should_stop,
                            clock=clock,
                        )
                finally:
                    events.close()
            if current.terminal_state not in {"ready_for_review", "failed", "stale", "cancelled"}:
                raise AgentRuntimeError("AGENT_CHECKPOINT_INCOMPATIBLE")
        return _finalize(session_factory, job.id, token, run.id, current)
    except AgentRuntimeError as exc:
        recorder.fail_step(exc.code, exc.safe_message)
        if exc.code == "JOB_LEASE_LOST":
            raise
        current = _failed_state(
            current,
            exc.code,
            exc.safe_message,
            stale=exc.code == "SCHEDULE_VERSION_STALE",
        )
        return _finalize(session_factory, job.id, token, run.id, current)


__all__ = ["FRAMEWORK_VERSION", "AgentRuntimeError", "process_job_with_graph"]
