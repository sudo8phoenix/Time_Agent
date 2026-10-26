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


def test_http_rejection_is_distinct_from_invalid_model_output():
    from app.llm.hosted import HostedRequestError
    assert _failure_category(HostedRequestError('private provider detail')) == 'MODEL_REQUEST_FAILED'


def test_extraction_failure_category_reaches_terminal_graph_state():
    from test_agent_tools import Fixture
    from test_agent_graph import initial, invoke
    fixture = Fixture()
    delegate = fixture.tools()
    class RejectedExtraction:
        def __getattr__(self, name):
            return getattr(delegate, name)
        def extract_observations(self, *args):
            raise AgentToolError('AGENT_TOOL_FAILED', 'The provider rejected the request.',
                                 failure_category='MODEL_REQUEST_FAILED')
    result = invoke(RejectedExtraction(), initial(fixture))
    assert result['terminal_state'] == 'failed'
    assert result['validation_errors'][0]['code'] == 'MODEL_REQUEST_FAILED'
    assert fixture.persist_calls == []


@pytest.mark.parametrize('source,expected', [('extraction', 'extract'), ('selection', 'select'),
                                            ('analysis', 'extract'), ('runtime', 'parse')])
def test_terminal_failure_stage_is_not_reported_as_persistence(source, expected):
    from app.agent.runtime import _terminal_stage
    from app.agent.state import create_initial_state, ValidationErrorRecord
    from uuid import uuid4
    state = create_initial_state(**{key: str(uuid4()) for key in (
        'run_id', 'job_id', 'project_id', 'report_id', 'schedule_version_id')})
    state = state.model_copy(update={'terminal_state': 'failed', 'validation_errors': [
        ValidationErrorRecord(stage=source, code='MODEL_QUOTA_EXHAUSTED', message='Safe', retryable=False)]})
    assert _terminal_stage(state) == expected


@pytest.mark.parametrize('always_reject', [False, True])
@pytest.mark.parametrize('schema_field,counter', [('observations', 'extraction_calls'), ('candidate_id', 'selection_calls')])
def test_provider_generation_rejection_uses_only_one_budgeted_retry(always_reject, schema_field, counter):
    from dataclasses import replace
    from app.llm.hosted import HostedGenerationError
    from test_agent_tools import Fixture
    from test_agent_graph import initial, invoke
    fixture = Fixture()
    original = fixture.context.model_callable
    attempts = []
    def model(**kwargs):
        if schema_field in kwargs.get('schema', {}).get('properties', {}):
            attempts.append(1)
            if always_reject or len(attempts) == 1:
                raise HostedGenerationError('private failed generation')
        return original(**kwargs)
    fixture.context = replace(fixture.context, model_callable=model)
    result = invoke(fixture.tools(), initial(fixture))
    assert len(attempts) == 2
    assert result['counters'][counter] == 2
    assert result['counters']['corrective_retries'] == 1
    assert result['terminal_state'] == ('failed' if always_reject else 'ready_for_review')
    if always_reject:
        assert fixture.persist_calls == []
    assert 'private' not in str(result['validation_errors'])
