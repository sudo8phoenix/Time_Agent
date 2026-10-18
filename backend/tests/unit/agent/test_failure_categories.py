"""Operational diagnostics preserve known categories without service messages."""
import pytest

from app.agent.tools import AgentToolError, _failure_category
from app.llm.hosted import HostedCapacityError, HostedQuotaError, HostedRateLimitError
from app.llm.ollama import OllamaResponseError, OllamaTransportError


@pytest.mark.parametrize("error,category", [
    (HostedCapacityError("private content"), "MODEL_CAPACITY_TIMEOUT"),
    (HostedQuotaError("private content"), "MODEL_QUOTA_EXHAUSTED"),
    (HostedRateLimitError("private content"), "MODEL_RATE_LIMITED"),
    (OllamaTransportError("private content"), "MODEL_REQUEST_FAILED"),
    (OllamaResponseError("private content"), "MODEL_RESPONSE_INVALID"),
    (RuntimeError("MODEL_RATE_LIMITED: private content"), None),
])
def test_failure_category_uses_known_types_not_exception_text(error, category):
    assert _failure_category(error) == category


def test_tool_error_rejects_arbitrary_diagnostic_fields():
    error = AgentToolError("AGENT_TOOL_FAILED", "Safe message", failure_category="private content")
    assert error.failure_category is None
