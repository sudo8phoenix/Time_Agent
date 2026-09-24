from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.agent import AgentRunStatus


def _payload() -> dict:
    started = datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc)
    return {
        "id": uuid4(),
        "job_id": uuid4(),
        "graph_version": "report-analysis-v1",
        "framework_version": "1.2.12",
        "state": "running",
        "current_stage": "Validating evidence",
        "counters": {
            "node_executions": 3,
            "extraction_calls": 1,
            "selection_calls": 0,
            "corrective_retries": 0,
        },
        "steps": [
            {
                "ordinal": 1,
                "node": "load_context",
                "label": "Loading context",
                "state": "succeeded",
                "attempt": 1,
                "duration_ms": 18,
                "error_code": None,
            },
            {
                "ordinal": 2,
                "node": "extract",
                "label": "Extracting observations",
                "state": "succeeded",
                "attempt": 1,
                "duration_ms": 25,
                "error_code": None,
            },
        ],
        "error_code": None,
        "error_message": None,
        "started_at": started,
        "updated_at": started + timedelta(seconds=3),
        "completed_at": None,
    }


def test_canonical_agent_status_has_only_sanitized_public_fields():
    status = AgentRunStatus.model_validate(_payload())
    body = status.model_dump(mode="json")

    assert set(body) == {
        "id",
        "job_id",
        "graph_version",
        "framework_version",
        "state",
        "current_stage",
        "counters",
        "steps",
        "error_code",
        "error_message",
        "started_at",
        "updated_at",
        "completed_at",
    }
    serialized = status.model_dump_json().lower()
    for forbidden in (
        "prompt",
        "reasoning",
        "checkpoint",
        "report_body",
        "tool_input",
        "tool_output",
        "lease_token",
        "database_url",
        "ollama_url",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize("field", ["prompt", "checkpoint", "execution_controls"])
def test_agent_status_forbids_unknown_sensitive_fields(field):
    payload = _payload()
    payload[field] = "must not be accepted"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentRunStatus.model_validate(payload)


def test_agent_status_requires_exact_counter_shape():
    payload = _payload()
    payload["counters"]["prompt_tokens"] = 12
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentRunStatus.model_validate(payload)


def test_agent_status_enforces_frozen_counter_and_step_limits():
    payload = _payload()
    payload["counters"]["node_executions"] = 17
    with pytest.raises(ValidationError):
        AgentRunStatus.model_validate(payload)

    payload = _payload()
    payload["steps"] = [
        dict(payload["steps"][0], ordinal=ordinal, attempt=ordinal)
        for ordinal in range(1, 18)
    ]
    with pytest.raises(ValidationError):
        AgentRunStatus.model_validate(payload)


def test_agent_status_rejects_unordered_or_duplicate_steps():
    payload = _payload()
    payload["steps"][1]["ordinal"] = 1
    with pytest.raises(ValidationError, match="unique ascending ordinals"):
        AgentRunStatus.model_validate(payload)


def test_agent_step_rejects_private_or_mismatched_stage_label():
    payload = _payload()
    payload["steps"][0]["label"] = "Extracting observations"
    with pytest.raises(ValidationError, match="public label for node"):
        AgentRunStatus.model_validate(payload)

    payload = _payload()
    payload["current_stage"] = "Thinking about the report"
    with pytest.raises(ValidationError):
        AgentRunStatus.model_validate(payload)


def test_running_step_has_no_duration_and_nonfailed_step_has_no_error():
    payload = _payload()
    payload["steps"][0].update(state="running", duration_ms=1)
    with pytest.raises(ValidationError, match="duration must be null"):
        AgentRunStatus.model_validate(payload)

    payload = _payload()
    payload["steps"][0]["error_code"] = "AGENT_TOOL_FAILED"
    with pytest.raises(ValidationError, match="only allowed for failed"):
        AgentRunStatus.model_validate(payload)


def test_successful_run_cannot_expose_error_text():
    payload = _payload()
    payload.update(state="ready_for_review", error_message="raw exception")
    with pytest.raises(ValidationError, match="only allowed"):
        AgentRunStatus.model_validate(payload)


def test_agent_status_rejects_invalid_timestamps():
    payload = _payload()
    payload["updated_at"] = payload["started_at"] - timedelta(seconds=1)
    with pytest.raises(ValidationError, match="must not precede"):
        AgentRunStatus.model_validate(payload)
