"""Sanitized, local operational telemetry for bounded graph execution."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from ..db.models import AgentRun, AgentStep, AgentToolCall
from .state import AgentState, encode_agent_state
from .tools import AgentToolError

MAX_SUMMARY_BYTES = 65_536
SAFE_INTERNAL_MESSAGE = "The report analysis operation failed safely."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_hash(state: AgentState) -> str:
    return sha256(encode_agent_state(state)).hexdigest()


def _bounded_summary(value: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > MAX_SUMMARY_BYTES:
        raise ValueError("sanitized trace summary exceeds 64 KiB")
    return value


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return max(0, int((finished_at - started_at).total_seconds() * 1000))


def _step_summary(state: AgentState) -> dict[str, Any]:
    return _bounded_summary({
        "observation_count": len(state.observation_drafts),
        "candidate_set_count": len(state.candidate_sets),
        "selection_count": len(state.selection_drafts),
        "warning_count": len(state.warnings),
        "validation_error_count": len(state.validation_errors),
        "error_codes": sorted({item.code for item in state.validation_errors}),
        "next_action": state.next_action,
        "terminal_state": state.terminal_state,
        "counters": state.counters.model_dump(mode="json"),
    })


def _tool_input_summary(name: str, args: tuple[Any, ...]) -> dict[str, Any]:
    if name == "load_job_context":
        return {"job_id": str(args[0])}
    if name == "extract_observations":
        return {"fragment_count": len(args[0])}
    if name == "retrieve_candidates":
        return {"observation_key": str(args[0]), "schedule_version_id": str(args[2])}
    if name == "select_candidate":
        return {
            "observation_key": str(args[0]),
            "candidate_count": len(args[2]),
            "fragment_count": len(args[3]),
        }
    state = args[0] if args else None
    if name in {"validate_proposal_drafts", "persist_review_proposals"} and isinstance(
        state, AgentState
    ):
        return {
            "run_id": state.run_id,
            "observation_count": len(state.observation_drafts),
            "candidate_set_count": len(state.candidate_sets),
            "selection_count": len(state.selection_drafts),
        }
    return {}


def _tool_output_summary(name: str, value: Any) -> dict[str, Any]:
    if name == "load_job_context":
        return {
            "fragment_count": len(value.fragment_ids),
            "activity_count": len(value.activity_ids),
        }
    if name == "extract_observations":
        return {
            "observation_count": len(value.observations),
            "warning_count": len(value.warnings),
            "error_count": len(value.errors),
        }
    if name == "retrieve_candidates":
        return {"candidate_count": len(value.candidates), "warning_count": len(value.warnings)}
    if name == "select_candidate":
        return {
            "selected": value.candidate_id is not None,
            "candidate_count": len(value.candidates),
            "mapping_state": value.mapping_state.value,
        }
    if name == "validate_proposal_drafts":
        return {
            "valid": value.valid,
            "warning_count": len(value.warnings),
            "error_count": len(value.errors),
        }
    if name == "persist_review_proposals":
        return {
            "extracted_count": value.extracted_count,
            "proposal_count": value.proposal_count,
            "already_persisted": value.already_persisted,
        }
    return {}


class TelemetryRecorder:
    """Write one sanitized trace stream using independent short transactions."""

    def __init__(self, session_factory, run_id: UUID, *, clock=_now):
        self._session_factory = session_factory
        self.run_id = run_id
        self._clock = clock
        self.active_step_id: UUID | None = None

    def reconcile_checkpoint(self, next_nodes: tuple[str, ...], state: AgentState) -> None:
        """Repair telemetry left between a durable node checkpoint and trace commit."""
        now = self._clock()
        with self._session_factory.begin() as db:
            steps = list(db.scalars(select(AgentStep).where(
                AgentStep.run_id == self.run_id,
                AgentStep.state == "running",
            ).with_for_update()))
            for step in steps:
                calls = list(db.scalars(select(AgentToolCall).where(
                    AgentToolCall.step_id == step.id,
                    AgentToolCall.state == "running",
                ).with_for_update()))
                if step.node in next_nodes:
                    for call in calls:
                        call.state = "failed"
                        call.finished_at = now
                        call.duration_ms = _duration_ms(call.started_at, now)
                        call.error_code = "AGENT_INTERNAL_ERROR"
                        call.error_message = "The prior worker stopped before the node checkpoint."
                    continue
                for call in calls:
                    call.state = "succeeded"
                    call.finished_at = now
                    call.duration_ms = _duration_ms(call.started_at, now)
                    call.sanitized_output_summary = {"recovered_from_checkpoint": True}
                step.state = "succeeded"
                step.finished_at = now
                step.duration_ms = _duration_ms(step.started_at, now)
                step.output_hash = _state_hash(state)
                step.sanitized_summary = _step_summary(state)

    def begin_step(self, node: str, state: AgentState) -> UUID:
        now = self._clock()
        with self._session_factory.begin() as db:
            existing = db.scalar(select(AgentStep).where(
                AgentStep.run_id == self.run_id,
                AgentStep.node == node,
                AgentStep.state == "running",
            ).with_for_update())
            if existing is not None:
                self.active_step_id = existing.id
                return existing.id
            ordinal = int(db.scalar(select(func.coalesce(func.max(AgentStep.ordinal), 0)).where(
                AgentStep.run_id == self.run_id
            )) or 0) + 1
            attempt = int(db.scalar(select(func.count()).select_from(AgentStep).where(
                AgentStep.run_id == self.run_id,
                AgentStep.node == node,
            )) or 0) + 1
            step = AgentStep(
                run_id=self.run_id,
                ordinal=ordinal,
                node=node,
                attempt=attempt,
                state="running",
                input_hash=_state_hash(state),
                sanitized_summary={},
                started_at=now,
            )
            db.add(step)
            run = db.get(AgentRun, self.run_id)
            if run is None:
                raise RuntimeError("agent run disappeared")
            run.state = "running"
            run.current_node = node
            run.updated_at = now
            run.completed_at = None
            run.error_code = None
            run.error_message = None
            db.flush()
            self.active_step_id = step.id
            return step.id

    def finish_step(self, state: AgentState) -> None:
        if self.active_step_id is None:
            raise RuntimeError("no active agent step")
        now = self._clock()
        with self._session_factory.begin() as db:
            step = db.get(AgentStep, self.active_step_id)
            run = db.get(AgentRun, self.run_id)
            if step is None or run is None:
                raise RuntimeError("agent trace disappeared")
            step.state = "succeeded"
            step.finished_at = now
            step.duration_ms = _duration_ms(step.started_at, now)
            step.output_hash = _state_hash(state)
            step.sanitized_summary = _step_summary(state)
            run.counters = state.counters.model_dump(mode="json")
            metadata = state.model_metadata.model_dump(mode="json")
            run.model_metadata = {
                key: metadata[key] for key in ("model_tag", "model_digest") if metadata[key]
            }
            run.prompt_metadata = {
                key: metadata[key]
                for key in (
                    "extraction_prompt_version", "extraction_prompt_hash",
                    "selection_prompt_version", "selection_prompt_hash",
                )
                if metadata[key]
            }
            run.config_metadata = (
                {"settings_hash": metadata["settings_hash"]} if metadata["settings_hash"] else {}
            )
            run.updated_at = now
        self.active_step_id = None

    def fail_step(self, code: str, message: str) -> None:
        if self.active_step_id is None:
            return
        now = self._clock()
        with self._session_factory.begin() as db:
            step = db.get(AgentStep, self.active_step_id)
            if step is not None and step.state == "running":
                step.state = "failed"
                step.finished_at = now
                step.duration_ms = _duration_ms(step.started_at, now)
                step.error_code = code
                step.error_message = message[:1000]
        self.active_step_id = None

    def call_tool(self, name: str, function, *args: Any, **kwargs: Any) -> Any:
        if self.active_step_id is None:
            return function(*args, **kwargs)
        started = self._clock()
        with self._session_factory.begin() as db:
            attempt = int(db.scalar(select(func.count()).select_from(AgentToolCall).where(
                AgentToolCall.step_id == self.active_step_id,
                AgentToolCall.tool_name == name,
            )) or 0) + 1
            call = AgentToolCall(
                step_id=self.active_step_id,
                tool_name=name,
                attempt=attempt,
                state="running",
                sanitized_input_summary=_bounded_summary(_tool_input_summary(name, args)),
                sanitized_output_summary={},
                started_at=started,
            )
            db.add(call)
            db.flush()
            call_id = call.id
        try:
            value = function(*args, **kwargs)
        except AgentToolError as exc:
            self._finish_tool(call_id, "failed", code=exc.code, message=exc.safe_message)
            raise
        except Exception:
            self._finish_tool(
                call_id, "failed", code="AGENT_TOOL_FAILED", message=SAFE_INTERNAL_MESSAGE
            )
            raise
        self._finish_tool(
            call_id, "succeeded", output=_bounded_summary(_tool_output_summary(name, value))
        )
        return value

    def _finish_tool(
        self,
        call_id: UUID,
        state: str,
        *,
        output: dict[str, Any] | None = None,
        code: str | None = None,
        message: str | None = None,
    ) -> None:
        now = self._clock()
        with self._session_factory.begin() as db:
            call = db.get(AgentToolCall, call_id)
            if call is None:
                raise RuntimeError("agent tool trace disappeared")
            call.state = state
            call.finished_at = now
            call.duration_ms = _duration_ms(call.started_at, now)
            call.sanitized_output_summary = output or {}
            call.error_code = code
            call.error_message = message[:1000] if message else None


class TelemetryTools:
    """Control-plane proxy; the model never sees this registry or its names."""

    _TRACED = frozenset({
        "load_job_context", "extract_observations", "retrieve_candidates",
        "select_candidate", "validate_proposal_drafts", "persist_review_proposals",
    })

    def __init__(self, tools: Any, recorder: TelemetryRecorder):
        self._tools = tools
        self._recorder = recorder

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._tools, name)
        if name not in self._TRACED or not callable(value):
            return value

        def traced(*args: Any, **kwargs: Any) -> Any:
            return self._recorder.call_tool(name, value, *args, **kwargs)

        return traced

    def rehydrate_provenance(self, state: AgentState) -> None:
        self._tools.rehydrate_provenance(state)


__all__ = ["TelemetryRecorder", "TelemetryTools"]
