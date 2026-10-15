"""Admission limits apply across roles and credentials without quota bypass."""
import json
from threading import Event, Thread

import pytest

from app.llm import hosted
from app.llm.groq import GroqChatAdapter
from app.llm.openrouter import OpenRouterChatAdapter
from app.llm.ollama import OllamaConfigurationError, OllamaTransportError


SCHEMA = {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}
BODY = {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]}


def test_competing_roles_and_keys_serialize_and_release_after_failure():
    gate = hosted.HostedAdmission(intervals={})
    gate.acquire("groq", {}, 1)
    entered, done = Event(), Event()
    def second_role():
        entered.set()
        gate.acquire("groq", {}, 2)
        done.set()
        gate.release("groq")
    thread = Thread(target=second_role)
    thread.start()
    try:
        assert entered.wait(1)
        assert not done.wait(.03)
        gate.release("groq", status=503)
        assert done.wait(1)
    finally:
        thread.join(timeout=2)
    assert not thread.is_alive() and not gate.states["groq"].active


def test_other_provider_is_not_blocked_and_waiting_has_a_deadline():
    gate = hosted.HostedAdmission(intervals={})
    gate.acquire("groq", {}, 1)
    assert gate.acquire("openrouter", {}, 1) > 0
    with pytest.raises(hosted.HostedCapacityError):
        gate.acquire("groq", {}, .02)
    gate.release("groq")
    gate.release("openrouter")


def test_token_budget_daily_quota_and_cooldown_are_shared_without_key_rotation():
    gate = hosted.HostedAdmission(intervals={}, clock=lambda: 100)
    gate.acquire("groq", {}, 10)
    gate.release("groq", status=200, headers={"X-RateLimit-Remaining-Tokens": "5",
        "X-RateLimit-Reset-Tokens": "60s"})
    with pytest.raises(hosted.HostedCapacityError) as error:
        gate.acquire("groq", {"max_completion_tokens": 20}, 1)
    assert error.value.retry_after_seconds == 60
    gate.acquire("openrouter", {}, 10)
    gate.release("openrouter", status=429, headers={"Retry-After": "120"})
    with pytest.raises(hosted.HostedCapacityError):
        gate.acquire("openrouter", {}, 30)
    gate.states["groq"].remaining_requests = 0
    gate.states["groq"].request_reset = 200
    with pytest.raises(hosted.HostedQuotaError):
        gate.acquire("groq", {}, 1)


def test_only_numeric_quota_headers_are_retained():
    result = hosted.safe_headers({"Authorization": "secret", "Set-Cookie": "secret",
        "X-RateLimit-Remaining-Tokens": "200", "x-ratelimit-reset-tokens": "1m2.5s",
        "Retry-After": "10", "x-ratelimit-limit-requests": "NaN"})
    assert result == {"x-ratelimit-remaining-tokens": 200, "x-ratelimit-reset-tokens": 62.5,
                      "retry-after": 10}
    assert "secret" not in str(result)


@pytest.mark.parametrize("adapter", [GroqChatAdapter, OpenRouterChatAdapter])
def test_429_is_retryable_but_never_switches_keys_models_or_providers(adapter):
    calls = []
    def transport(*args):
        calls.append(args)
        return 429, {}
    model = adapter("explicit-model", bearer_token="test-key", transport=transport)
    with pytest.raises(hosted.HostedRateLimitError):
        model.chat(system="s", user="u", schema=SCHEMA)
    assert len(calls) == 1 and calls[0][2]["model"] == "explicit-model"
    assert calls[0][4] == {"Authorization": "Bearer test-key"}


@pytest.mark.parametrize("adapter", [GroqChatAdapter, OpenRouterChatAdapter])
def test_default_transport_timeout_releases_slot_and_sanitizes_error(adapter, monkeypatch):
    gate = hosted.HostedAdmission(intervals={})
    monkeypatch.setattr(hosted, "ADMISSION", gate)
    def fail(*args, **kwargs):
        raise TimeoutError("private source and credential")
    monkeypatch.setattr(hosted, "urlopen", fail)
    model = adapter("explicit-model", bearer_token="test-key", timeout=.1)
    with pytest.raises(OllamaTransportError) as error:
        model.chat(system="s", user="u", schema=SCHEMA)
    assert "private" not in str(error.value)
    assert not next(iter(gate.states.values())).active


def test_default_transport_observes_headers_and_does_not_read_error_body(monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError
    gate = hosted.HostedAdmission(intervals={})
    monkeypatch.setattr(hosted, "ADMISSION", gate)
    error_body = BytesIO(b"private error body")
    def fail(*args, **kwargs):
        raise HTTPError("https://api.groq.com/", 429, "ignored", {"Retry-After": "80"}, error_body)
    monkeypatch.setattr(hosted, "urlopen", fail)
    with pytest.raises(hosted.HostedRateLimitError) as error:
        GroqChatAdapter("explicit", bearer_token="key").chat(system="s", user="u", schema=SCHEMA)
    assert error.value.retry_after_seconds > 79
    assert gate.states["groq"].headers == {"retry-after": 80}
    assert error_body.closed


def test_successful_default_transport_schema_and_quota_observation(monkeypatch):
    monkeypatch.setattr(hosted, "ADMISSION", hosted.HostedAdmission(intervals={}))
    class Response:
        status = 200
        headers = {"x-ratelimit-remaining-tokens": "6000"}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, size):
            return json.dumps(BODY).encode()
    monkeypatch.setattr(hosted, "urlopen", lambda *args, **kwargs: Response())
    assert GroqChatAdapter("explicit", bearer_token="key").chat(system="s", user="u", schema=SCHEMA).value == {"ok": True}
    assert hosted.ADMISSION.states["groq"].remaining_tokens == 6000


@pytest.mark.parametrize("timeout", [float("inf"), float("nan"), 901, -1])
def test_groq_timeout_is_finite_and_bounded(timeout):
    with pytest.raises(OllamaConfigurationError):
        GroqChatAdapter("model", bearer_token="key", timeout=timeout)


def test_excessive_numeric_header_is_discarded_without_holding_a_slot():
    gate = hosted.HostedAdmission(intervals={})
    gate.acquire("groq", {}, 1)
    gate.release("groq", status=200, headers={"x-ratelimit-remaining-tokens": "9" * 5000})
    assert not gate.states["groq"].active
    assert gate.states["groq"].headers == {}


def test_advertised_token_limit_smooths_even_with_tokens_remaining():
    now = [100.0]
    gate = hosted.HostedAdmission(intervals={}, clock=lambda: now[0])
    gate.acquire("groq", {"max_completion_tokens": 2000}, 60)
    estimate = gate.states["groq"].last_estimate
    gate.release("groq", status=200, headers={"x-ratelimit-limit-tokens": "8000",
        "x-ratelimit-remaining-tokens": "7000", "x-ratelimit-reset-tokens": "2s"})
    with pytest.raises(hosted.HostedCapacityError) as error:
        gate.acquire("groq", {"max_completion_tokens": 2000}, 1)
    assert error.value.retry_after_seconds == pytest.approx(60 * estimate / 8000)
    now[0] += 60 * estimate / 8000
    gate.acquire("groq", {}, 1)
    gate.release("groq")


def test_expired_request_quota_is_cleared_on_reset():
    gate = hosted.HostedAdmission(intervals={}, clock=lambda: 100)
    gate.acquire("groq", {}, 1)
    gate.release("groq", status=200, headers={"x-ratelimit-remaining-requests": "0",
        "x-ratelimit-reset-requests": "1s"})
    with pytest.raises(hosted.HostedQuotaError):
        gate.acquire("groq", {}, 1)
    gate.clock = lambda: 102
    gate.acquire("groq", {}, 1)
    assert gate.states["groq"].remaining_requests is None
    gate.release("groq")


def test_openrouter_epoch_millisecond_reset_is_converted(monkeypatch):
    monkeypatch.setattr(hosted.time, "time", lambda: 2_000_000_000)
    gate = hosted.HostedAdmission(intervals={}, clock=lambda: 100)
    gate.acquire("openrouter", {}, 1)
    gate.release("openrouter", status=429, headers={"x-ratelimit-reset": "2000000090000"})
    assert gate.states["openrouter"].cooldown == 190


def test_trickled_body_cannot_renew_timeout_and_slot_is_released(monkeypatch):
    from types import SimpleNamespace
    now, timeouts = [100.0], []
    gate = hosted.HostedAdmission(intervals={}, clock=lambda: now[0])
    monkeypatch.setattr(hosted, "ADMISSION", gate)
    monkeypatch.setattr(hosted.time, "monotonic", lambda: now[0])
    class Response:
        status, headers = 200, {}
        fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=timeouts.append)))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read1(self, size):
            now[0] += 2
            return b"x"
    monkeypatch.setattr(hosted, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(OllamaTransportError):
        GroqChatAdapter("fixture", bearer_token="test-key", timeout=3).chat(system="s", user="u", schema=SCHEMA)
    assert timeouts == [3, 1]
    assert not gate.states["groq"].active


def test_expired_replaced_reservation_cannot_return_model_output(monkeypatch):
    class Coordinator:
        def acquire(self, *args):
            return "old-owner", 1
        def release(self, *args, **kwargs):
            return False
    gate = hosted.DeploymentHostedAdmission()
    monkeypatch.setattr(gate, "_coordinator", lambda: Coordinator())
    monkeypatch.setattr(hosted, "ADMISSION", gate)
    class Response:
        status, headers = 200, {}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, size):
            return json.dumps(BODY).encode()
    monkeypatch.setattr(hosted, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(hosted.HostedCapacityError):
        GroqChatAdapter("fixture", bearer_token="test-key", timeout=1).chat(system="s", user="u", schema=SCHEMA)
    assert not gate.states["groq"].active
