"""Exercise the real shared transport with injected network failures only."""
from io import BytesIO
from urllib.error import HTTPError

import pytest

from app.llm import hosted
from app.llm.groq import GroqChatAdapter
from app.llm.metrics import capture_provider_metrics
from app.llm.ollama import OllamaResponseError, OllamaTransportError
from app.llm.openrouter import OpenRouterChatAdapter

ADAPTERS = [GroqChatAdapter, OpenRouterChatAdapter]
OPTIONS = dict(system='synthetic', user='synthetic', schema={'type': 'object'})


@pytest.mark.parametrize('adapter_type', ADAPTERS)
@pytest.mark.parametrize('status', [400, 401, 403, 404, 429, 500, 503])
def test_http_failure_matrix_keeps_one_attempt_releases_admission_and_hides_body(monkeypatch, adapter_type, status):
    gate = hosted.HostedAdmission(intervals={})
    monkeypatch.setattr(hosted, 'ADMISSION', gate)
    calls = []
    body = BytesIO(b'private report and secret from error response')
    def fail(request, **kwargs):
        calls.append(request)
        raise HTTPError(request.full_url, status, 'private report', {'Retry-After': '2'}, body)
    monkeypatch.setattr(hosted, 'urlopen', fail)
    model = adapter_type('fixed-model', bearer_token='fixed-key', timeout=1)
    with capture_provider_metrics() as metrics:
        with pytest.raises((OllamaResponseError, OllamaTransportError)) as error:
            model.chat(**OPTIONS)
    assert 'private' not in str(error.value) and 'fixed-key' not in str(error.value)
    assert len(calls) == 1 and body.closed
    assert not next(iter(gate.states.values())).active
    measured = next(iter(metrics.values()))
    assert measured['calls'] == measured['admitted'] == 1
    assert measured['responses_429' if status == 429 else 'responses_other'] == 1
    if status == 429:
        assert isinstance(error.value, hosted.HostedRateLimitError)


@pytest.mark.parametrize('adapter_type', ADAPTERS)
@pytest.mark.parametrize('failure', [TimeoutError, OSError])
def test_transport_failure_releases_admitted_slot_without_retry(monkeypatch, adapter_type, failure):
    gate = hosted.HostedAdmission(intervals={})
    monkeypatch.setattr(hosted, 'ADMISSION', gate)
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise failure('private endpoint credentials')
    monkeypatch.setattr(hosted, 'urlopen', fail)
    with capture_provider_metrics() as metrics:
        with pytest.raises(OllamaTransportError) as error:
            adapter_type('fixed-model', bearer_token='fixed-key', timeout=1).chat(**OPTIONS)
    assert 'private' not in str(error.value)
    assert calls == [1] and not next(iter(gate.states.values())).active
    measured = next(iter(metrics.values()))
    assert measured['admitted'] == measured['no_response'] == 1


@pytest.mark.parametrize('adapter_type', ADAPTERS)
@pytest.mark.parametrize('kind', ['malformed', 'oversized'])
def test_malformed_or_oversized_success_body_is_rejected_and_released(monkeypatch, adapter_type, kind):
    raw = b'private invalid JSON' if kind == 'malformed' else b'x' * (hosted.MAX_RESPONSE_BYTES+1)
    gate = hosted.HostedAdmission(intervals={})
    monkeypatch.setattr(hosted, 'ADMISSION', gate)
    class Response:
        status, headers = 200, {}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit):
            assert limit == hosted.MAX_RESPONSE_BYTES+1
            return raw
    monkeypatch.setattr(hosted, 'urlopen', lambda *args, **kwargs: Response())
    with pytest.raises((OllamaTransportError, OllamaResponseError)) as error:
        adapter_type('fixed-model', bearer_token='fixed-key', timeout=1).chat(**OPTIONS)
    assert 'private' not in str(error.value)
    assert not next(iter(gate.states.values())).active


@pytest.mark.parametrize('adapter_type', ADAPTERS)
def test_admission_expiry_never_opens_transport_or_counts_as_admitted(monkeypatch, adapter_type):
    class Expired(hosted.HostedAdmission):
        def acquire(self, *args):
            raise hosted.HostedCapacityError('Admission deadline exhausted')
    monkeypatch.setattr(hosted, 'ADMISSION', Expired(intervals={}))
    def forbidden(*args, **kwargs):
        pytest.fail('Expired admission must not open network transport')
    monkeypatch.setattr(hosted, 'urlopen', forbidden)
    with capture_provider_metrics() as metrics:
        with pytest.raises(hosted.HostedCapacityError):
            adapter_type('fixed-model', bearer_token='fixed-key', timeout=1).chat(**OPTIONS)
    measured = next(iter(metrics.values()))
    assert measured['calls'] == measured['no_response'] == 1
    assert measured['admitted'] == 0 and measured['transport_ms'] == 0
