"""Distinguish admission waits from transport, including failed calls, without text."""
import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from app.llm import hosted
from app.llm.metrics import capture_provider_metrics


def test_admission_wait_and_transport_are_separate_and_scoped(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(hosted.time, "monotonic", lambda: now[0])
    class Gate:
        def acquire(self, *args):
            now[0] += 7
            return 10
        def release(self, *args, **kwargs):
            now[0] += 1  # Coordinator release is not provider transport.
    class Response:
        status, headers = 200, {}
        def __enter__(self):
            now[0] += 2
            return self
        def __exit__(self, *args):
            return False
        def read(self, size):
            return b'{"private":"source"}'
    monkeypatch.setattr(hosted, "ADMISSION", Gate())
    monkeypatch.setattr(hosted, "urlopen", lambda *args, **kwargs: Response())
    with capture_provider_metrics() as outer:
        with capture_provider_metrics() as metrics:
            hosted.request("groq", "POST", "https://example.com", {"private": "source"}, 20, {"Authorization": "secret"})
        assert outer == {}
    assert metrics["groq"] == {"calls": 1, "admitted": 1, "admission_ms": 7000,
        "transport_ms": 2000, "responses_2xx": 1, "responses_429": 0,
        "responses_other": 0, "no_response": 0, "http_status_counts": {"200": 1}}
    assert "private" not in json.dumps(metrics) and "secret" not in json.dumps(metrics)


def test_failed_admission_is_recorded_without_transport_or_release(monkeypatch):
    class Gate:
        def acquire(self, *args):
            raise hosted.HostedCapacityError("private")
        def release(self, *args, **kwargs):
            raise AssertionError("no lease acquired")
    monkeypatch.setattr(hosted, "ADMISSION", Gate())
    with capture_provider_metrics() as metrics, pytest.raises(hosted.HostedCapacityError):
        hosted.request("groq", "POST", "https://example.com", {}, 1, {})
    assert metrics["groq"]["admitted"] == 0
    assert metrics["groq"]["transport_ms"] == 0
    assert metrics["groq"]["no_response"] == 1


def test_error_response_counts_status_without_retaining_private_body(monkeypatch):
    body = BytesIO(b"private")
    monkeypatch.setattr(hosted, "ADMISSION", hosted.HostedAdmission(intervals={}))
    def error(*args, **kwargs):
        raise HTTPError("https://example.com", 429, "private", {}, body)
    monkeypatch.setattr(hosted, "urlopen", error)
    with capture_provider_metrics() as metrics:
        assert hosted.request("groq", "POST", "https://example.com", {}, 1, {}) == (429, {})
    assert body.closed and metrics["groq"]["responses_429"] == 1


@pytest.mark.parametrize('code,retained', [('json_validate_failed', True), ('private report secret', False)])
def test_http_rejection_retains_only_allowlisted_code(monkeypatch, code, retained):
    body = BytesIO(json.dumps({'error': {'code': code, 'message': 'private report secret',
                                        'failed_generation': 'private report secret'}}).encode())
    monkeypatch.setattr(hosted, 'ADMISSION', hosted.HostedAdmission(intervals={}))
    def error(*args, **kwargs):
        raise HTTPError('https://example.com', 400, 'private', {}, body)
    monkeypatch.setattr(hosted, 'urlopen', error)
    with capture_provider_metrics() as metrics:
        if retained:
            with pytest.raises(hosted.HostedGenerationError):
                hosted.request('groq', 'POST', 'https://example.com', {}, 1, {})
        else:
            assert hosted.request('groq', 'POST', 'https://example.com', {}, 1, {}) == (400, {})
    row = metrics['groq']
    assert row['http_status_counts'] == {'400': 1}
    assert (row.get('last_error_code') == code) is retained
    assert 'private' not in json.dumps(metrics)
    assert body.closed


def test_finish_reason_is_allowlisted():
    from app.llm.metrics import record_provider_request, record_provider_finish
    with capture_provider_metrics() as metrics:
        record_provider_request('groq', admission_ms=0, transport_ms=0, admitted=True, status=200)
        record_provider_finish('groq', 'length')
        record_provider_finish('groq', 'private source text')
    assert metrics['groq']['last_finish_reason'] == 'length'
    assert 'private' not in json.dumps(metrics)


def test_oversized_error_body_preserves_original_http_status(monkeypatch):
    body = BytesIO(b'x' * 70000)
    monkeypatch.setattr(hosted, 'ADMISSION', hosted.HostedAdmission(intervals={}))
    def error(*args, **kwargs):
        raise HTTPError('https://example.com', 400, 'private', {}, body)
    monkeypatch.setattr(hosted, 'urlopen', error)
    with capture_provider_metrics() as metrics:
        assert hosted.request('groq', 'POST', 'https://example.com', {}, 1, {}) == (400, {})
    assert body.closed
    assert metrics['groq']['http_status_counts'] == {'400': 1}
    assert 'last_error_code' not in metrics['groq']


def test_quota_diagnostics_keep_only_numbers_and_registered_labels(monkeypatch):
    raw = {'error': {'code': 'rate_limit_exceeded', 'message':
        'Private account tokens per day (TPD): Limit 200000, Used 199000, Requested 3000. private secret'}}
    body = BytesIO(json.dumps(raw).encode())
    monkeypatch.setattr(hosted, 'ADMISSION', hosted.HostedAdmission(intervals={}))
    def error(*args, **kwargs):
        raise HTTPError('https://example.com', 429, 'private', {}, body)
    monkeypatch.setattr(hosted, 'urlopen', error)
    with capture_provider_metrics() as metrics, pytest.raises(hosted.HostedQuotaError):
        hosted.request('groq', 'POST', 'https://example.com', {}, 1, {})
    assert metrics['groq']['last_rejection'] == {
        'quota_kind': 'tokens_per_day', 'quota_limit': 200000,
        'quota_used': 199000, 'quota_requested': 3000}
    assert 'private' not in json.dumps(metrics)


def test_schema_rejection_details_never_store_message_or_property_names():
    result = hosted._safe_rejection_details({'message':
        'Invalid schema private property secret has unsupported type enum null'})
    assert result == {'reason': 'schema_rejected', 'schema_features': ['type', 'enum', 'null']}
