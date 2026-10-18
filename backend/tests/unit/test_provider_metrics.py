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
        "responses_other": 0, "no_response": 0}
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


def test_error_response_counts_status_without_reading_private_body(monkeypatch):
    body = BytesIO(b"private")
    monkeypatch.setattr(hosted, "ADMISSION", hosted.HostedAdmission(intervals={}))
    def error(*args, **kwargs):
        raise HTTPError("https://example.com", 429, "private", {}, body)
    monkeypatch.setattr(hosted, "urlopen", error)
    with capture_provider_metrics() as metrics:
        assert hosted.request("groq", "POST", "https://example.com", {}, 1, {}) == (429, {})
    assert body.closed and metrics["groq"]["responses_429"] == 1
