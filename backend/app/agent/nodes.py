"""The fixed report-analysis graph nodes; all domain operations use AgentTools."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .policy import AgentPolicyError
from .state import (
    AgentState,
    AgentStateError,
    AgentWarning,
    ValidationErrorRecord,
    encode_agent_state,
    observation_keys,
)
from .tools import AgentToolError


def _state(value: AgentState | dict[str, Any]) -> AgentState:
    return value if isinstance(value, AgentState) else AgentState.model_validate(value)


def _record(code: str, message: str, *, stage: str, retryable: bool = False) -> dict[str, Any]:
    return ValidationErrorRecord(
        stage=stage, code=code, message=message, retryable=retryable,
    ).model_dump(mode="json")


def _error_update(error: AgentToolError, *, node: str) -> dict[str, Any]:
    retry_stage = error.stage if error.retryable and error.stage in {"extraction", "selection"} else None
    terminal = "stale" if error.code == "SCHEDULE_VERSION_STALE" else None
    return {
        "validation_errors": [_record(
            error.code, error.safe_message, stage=error.stage or node,
            retryable=retry_stage is not None,
        )],
        "next_action": "repair_extraction" if retry_stage == "extraction" else (
            "repair_selection" if retry_stage == "selection" else "fail"
        ),
        "terminal_state": terminal,
    }


def _unexpected_update(*, node: str) -> dict[str, Any]:
    return {
        "validation_errors": [_record(
            "AGENT_INTERNAL_ERROR", "The report analysis step failed safely.", stage=node,
        )],
        "next_action": "fail",
    }


def _repair_attempts(state: AgentState, stage: str) -> int:
    # Extraction is always the first model stage. Its second call proves an
    # extraction repair occurred; remaining global retries belong to selection.
    extraction_repairs = min(max(state.counters.extraction_calls - 1, 0), 1)
    return extraction_repairs if stage == "extraction" else max(
        0, state.counters.corrective_retries - extraction_repairs,
    )


def _count(state: AgentState, policy: Any) -> dict[str, Any]:
    executions = state.counters.node_executions + 1
    try:
        policy.validate_node_execution_budget(
            executions=executions, repairs=state.counters.corrective_retries,
        )
    except AgentPolicyError as error:
        return {
            # AgentCounters caps executions at 16; preserve the last valid
            # value when rejecting an attempted seventeenth execution.
            "counters": state.counters.model_dump(mode="python"),
            "validation_errors": [_record(error.code, str(error), stage="policy")],
            "next_action": "fail",
        }
    return {"counters": {**state.counters.model_dump(mode="python"), "node_executions": executions}}


def _merge(state: AgentState, updates: dict[str, Any]) -> dict[str, Any]:
    counters = updates.pop("counters", state.counters.model_dump(mode="python"))
    result = {**updates, "counters": counters}
    try:
        merged = AgentState.model_validate({
            **state.model_dump(mode="python", warnings=False),
            **result,
        })
        encode_agent_state(merged)
    except (AgentStateError, ValidationError) as error:
        code = error.code if isinstance(error, AgentStateError) else "AGENT_STATE_INVALID"
        return {
            "counters": counters,
            "validation_errors": [_record(code, "Agent state failed validation.", stage="state")],
            "next_action": "fail",
            "terminal_state": "failed",
        }
    return result


def _nodes(tools: Any, policy: Any) -> dict[str, Callable[[AgentState], dict[str, Any]]]:
    """Create the exact fixed node set bound to one invocation's accepted tools."""
    def load_context(raw: AgentState) -> dict[str, Any]:
        state = _state(raw)
        counted = _count(state, policy)
        if counted.get("next_action") == "fail":
            return counted
        try:
            context = tools.load_job_context(state.job_id)
            if (context.job_id != state.job_id or context.project_id != state.project_id
                    or context.report_id != state.report_id
                    or context.schedule_version_id != state.schedule_version_id):
                raise AgentToolError("AGENT_STATE_INVALID", "Loaded context identity does not match the run.")
            return _merge(state, {
                **counted, "fragment_ids": list(context.fragment_ids),
                "activity_ids": list(context.activity_ids), "next_action": "extract",
                "validation_errors": [], "terminal_state": None,
            })
        except AgentToolError as error:
            return _merge(state, {**counted, **_error_update(error, node="load_context")})
        except Exception:
            return _merge(state, {**counted, **_unexpected_update(node="load_context")})

    def extraction_call(raw: AgentState, *, repair: bool) -> dict[str, Any]:
        state = _state(raw)
        counted = _count(state, policy)
        if counted.get("next_action") == "fail":
            return counted
        counters = dict(counted["counters"])
        counters["extraction_calls"] += 1
        if repair:
            counters["corrective_retries"] += 1
        try:
            result = tools.extract_observations(state.fragment_ids, tools.report_metadata)
            return _merge(state, {
                **counted, "counters": counters,
                "observation_drafts": [item.model_dump(mode="python") for item in result.observations],
                "model_metadata": result.model_metadata.model_dump(mode="python"),
                "warnings": [*state.warnings, *[item.model_dump(mode="python") for item in result.warnings]],
                "validation_errors": [item.model_dump(mode="python") for item in result.errors],
                "next_action": "retrieve" if not result.errors else "repair_extraction" if any(
                    item.stage == "extraction" and item.retryable for item in result.errors
                ) else "fail",
            })
        except AgentToolError as error:
            return _merge(state, {**counted, "counters": counters, **_error_update(error, node="extract")})
        except Exception:
            return _merge(state, {**counted, "counters": counters, **_unexpected_update(node="extract")})

    def extract(raw: AgentState) -> dict[str, Any]:
        return extraction_call(raw, repair=False)

    def repair_extraction(raw: AgentState) -> dict[str, Any]:
        return extraction_call(raw, repair=True)

    def validate_extraction(raw: AgentState) -> dict[str, Any]:
        state = _state(raw)
        counted = _count(state, policy)
        if counted.get("next_action") == "fail":
            return counted
        try:
            errors = list(state.validation_errors)
            if any(item.stage == "extraction" and item.retryable for item in errors):
                action = "repair_extraction"
            elif errors:
                action = "fail"
            else:
                metadata = tools.report_metadata
                observation_errors: list[ValidationErrorRecord] = []
                for observation in state.observation_drafts:
                    if not observation.evidence or any(
                        item.fragment_id not in state.fragment_ids for item in observation.evidence
                    ):
                        observation_errors.append(ValidationErrorRecord(
                            stage="extraction", code="AGENT_TOOL_FAILED",
                            message="Observation evidence is outside the loaded report scope.", retryable=False,
                        ))
                    if observation.date_basis.value == "relative_resolved" and not metadata.report_date_trusted:
                        observation_errors.append(ValidationErrorRecord(
                            stage="extraction", code="AGENT_TOOL_FAILED",
                            message="Relative dates require a trusted report date.", retryable=True,
                        ))
                if observation_errors:
                    errors = observation_errors
                    action = "repair_extraction" if any(item.retryable for item in errors) else "fail"
                else:
                    errors = []
                    action = "retrieve"
            if action == "repair_extraction":
                try:
                    policy.route_extraction_validation(
                        state.model_copy(update={"next_action": action}),
                        attempted_repairs=_repair_attempts(state, "extraction"),
                    )
                except AgentPolicyError as error:
                    errors = [ValidationErrorRecord(stage="extraction", code=error.code, message=str(error), retryable=False)]
                    action = "fail"
            return _merge(state, {
                **counted, "validation_errors": [item.model_dump(mode="python") for item in errors],
                "next_action": action,
            })
        except (AgentToolError, ValidationError):
            return _merge(state, {**counted, **_unexpected_update(node="validate_extraction")})

    def retrieve(raw: AgentState) -> dict[str, Any]:
        state = _state(raw)
        counted = _count(state, policy)
        if counted.get("next_action") == "fail":
            return counted
        try:
            candidates: dict[str, list[dict[str, Any]]] = {}
            warnings = list(state.warnings)
            for key, observation in zip(
                observation_keys(len(state.observation_drafts)), state.observation_drafts, strict=True,
            ):
                result = tools.retrieve_candidates(key, observation, state.schedule_version_id)
                candidates[key] = [item.model_dump(mode="python") for item in result.candidates]
                warnings.extend(item.model_dump(mode="python") for item in result.warnings)
            return _merge(state, {
                **counted, "candidate_sets": candidates, "warnings": warnings,
                "validation_errors": [], "next_action": "select",
            })
        except AgentToolError as error:
            return _merge(state, {**counted, **_error_update(error, node="retrieve")})
        except Exception:
            return _merge(state, {**counted, **_unexpected_update(node="retrieve")})

    def selection_call(raw: AgentState, *, repair: bool) -> dict[str, Any]:
        state = _state(raw)
        counted = _count(state, policy)
        if counted.get("next_action") == "fail":
            return counted
        counters = dict(counted["counters"])
        if repair:
            counters["corrective_retries"] += 1
        proposals: dict[str, Any] = {}
        errors: list[dict[str, Any]] = []
        try:
            keys = observation_keys(len(state.observation_drafts))
            for key, observation in zip(keys, state.observation_drafts, strict=True):
                counters["selection_calls"] += 1
                try:
                    proposal = tools.select_candidate(
                        key, observation, state.candidate_sets[key], state.fragment_ids,
                    )
                    proposals[key] = proposal.model_dump(mode="python")
                except AgentToolError as error:
                    errors.append(_record(
                        error.code, error.safe_message, stage=error.stage or "selection",
                        retryable=error.retryable,
                    ))
                    if not error.retryable:
                        break
            return _merge(state, {
                **counted, "counters": counters,
                "selection_drafts": {} if errors else proposals,
                "model_metadata": tools.model_metadata.model_dump(mode="python"),
                "validation_errors": errors,
                "next_action": "repair_selection" if errors and any(e["retryable"] for e in errors) else "fail" if errors else "persist",
            })
        except AgentToolError as error:
            return _merge(state, {**counted, "counters": counters, **_error_update(error, node="select")})
        except Exception:
            return _merge(state, {**counted, "counters": counters, **_unexpected_update(node="select")})

    def select(raw: AgentState) -> dict[str, Any]:
        return selection_call(raw, repair=False)

    def repair_selection(raw: AgentState) -> dict[str, Any]:
        return selection_call(raw, repair=True)

    def validate_selection(raw: AgentState) -> dict[str, Any]:
        state = _state(raw)
        counted = _count(state, policy)
        if counted.get("next_action") == "fail":
            return counted
        errors = list(state.validation_errors)
        warnings = list(state.warnings)
        if any(item.stage == "selection" and item.retryable for item in errors):
            action = "repair_selection"
        elif errors:
            action = "fail"
        else:
            try:
                result = tools.validate_proposal_drafts(state)
                errors = list(result.errors)
                warnings = [*state.warnings, *[item.model_dump(mode="python") for item in result.warnings]]
                action = "persist" if result.valid else (
                    "repair_selection" if any(item.retryable for item in result.errors) else "fail"
                )
            except AgentToolError as error:
                return _merge(state, {**counted, **_error_update(error, node="validate_selection")})
            except Exception:
                return _merge(state, {**counted, **_unexpected_update(node="validate_selection")})
        if action == "repair_selection":
            try:
                policy.route_selection_validation(
                    state.model_copy(update={"next_action": action}),
                    attempted_repairs=_repair_attempts(state, "selection"),
                )
            except AgentPolicyError as error:
                errors = [ValidationErrorRecord(stage="selection", code=error.code, message=str(error), retryable=False)]
                action = "fail"
        return _merge(state, {
            **counted, "validation_errors": [item.model_dump(mode="python") for item in errors],
            "warnings": warnings, "next_action": action,
        })

    def persist(raw: AgentState) -> dict[str, Any]:
        state = _state(raw)
        counted = _count(state, policy)
        if counted.get("next_action") == "fail":
            return counted
        try:
            result = tools.persist_review_proposals(state)
            return _merge(state, {
                **counted, "next_action": "persist", "validation_errors": [],
                "warnings": [*state.warnings, AgentWarning(
                    code="PERSISTED_COUNTS", message=f"Saved {result.extracted_count} observations and {result.proposal_count} proposals for review.",
                ).model_dump(mode="python")],
            })
        except AgentToolError as error:
            return _merge(state, {**counted, **_error_update(error, node="persist")})
        except Exception:
            return _merge(state, {**counted, **_unexpected_update(node="persist")})

    def finalize(raw: AgentState) -> dict[str, Any]:
        state = _state(raw)
        counted = _count(state, policy)
        if counted.get("next_action") == "fail":
            return counted
        return _merge(state, {**counted, "terminal_state": "ready_for_review"})

    def record_failure(raw: AgentState) -> dict[str, Any]:
        state = _state(raw)
        counted = _count(state, policy)
        terminal = state.terminal_state or "failed"
        if counted and counted.get("next_action") == "fail":
            # Preserve stale classification already supplied by the originating tool.
            terminal = state.terminal_state or "failed"
        errors = state.validation_errors or [ValidationErrorRecord(
            stage="routing", code="AGENT_STATE_INVALID",
            message="The graph reached failure without a typed cause.", retryable=False,
        )]
        return _merge(state, {
            **counted, "terminal_state": terminal, "next_action": "fail",
            "validation_errors": [item.model_dump(mode="python") for item in errors],
        })

    return {
        "load_context": load_context,
        "extract": extract,
        "validate_extraction": validate_extraction,
        "repair_extraction": repair_extraction,
        "retrieve": retrieve,
        "select": select,
        "validate_selection": validate_selection,
        "repair_selection": repair_selection,
        "persist": persist,
        "finalize": finalize,
        "record_failure": record_failure,
    }


def conditional_routers(policy: Any):
    """Return the three exact, state-only branch functions used by this graph."""

    def load_route(state: AgentState | dict[str, Any]) -> str:
        try:
            destination = policy.route_next_action(_state(state))
            return destination if destination == "extract" else "record_failure"
        except AgentPolicyError:
            return "record_failure"

    def extraction_route(state: AgentState | dict[str, Any]) -> str:
        parsed = _state(state)
        try:
            return policy.route_extraction_validation(parsed, attempted_repairs=_repair_attempts(parsed, "extraction"))
        except AgentPolicyError:
            return "record_failure"

    def selection_route(state: AgentState | dict[str, Any]) -> str:
        parsed = _state(state)
        try:
            return policy.route_selection_validation(parsed, attempted_repairs=_repair_attempts(parsed, "selection"))
        except AgentPolicyError:
            return "record_failure"

    def persist_route(state: AgentState | dict[str, Any]) -> str:
        try:
            return policy.route_persist(_state(state))
        except AgentPolicyError:
            return "record_failure"

    return load_route, extraction_route, selection_route, persist_route


__all__ = ["_nodes", "conditional_routers"]
