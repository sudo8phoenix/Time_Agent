import pytest
from evaluation.provider_pacing import ProviderPacer, duration_seconds


def test_groq_token_reset_and_retry_after_apply_to_same_provider_only():
    pacer = ProviderPacer(clock=lambda: 100)
    pacer.observe("groq", {"x-ratelimit-remaining-tokens": "10", "x-ratelimit-reset-tokens": "7.66s"}, 200)
    assert pacer.wait_seconds("groq", {"max_completion_tokens": 1536}) == pytest.approx(7.66)
    assert pacer.wait_seconds("openrouter", {}) == 0
    pacer.observe("groq", {"retry-after": "23"}, 429)
    assert pacer.wait_seconds("groq", {}) == 23


def test_excessive_or_daily_quota_exhaustion_stops_instead_of_switching_credentials():
    pacer = ProviderPacer(clock=lambda: 100)
    pacer.observe("groq", {"retry-after": "3600"}, 429)
    assert pacer.state["groq"]["exhausted"]
    with pytest.raises(RuntimeError, match="quota exhausted"):
        pacer.transport("POST", "https://api.groq.com/chat", {}, 10, {}, call={})


def test_safe_header_allowlist_never_retains_authentication_headers():
    pacer = ProviderPacer(clock=lambda: 100)
    safe = pacer.observe("groq", {"Authorization": "private", "set-cookie": "private",
        "x-ratelimit-remaining-tokens": "200", "x-ratelimit-limit-tokens": "8000"}, 200)
    assert safe == {"x-ratelimit-remaining-tokens": 200, "x-ratelimit-limit-tokens": 8000}
    assert "private" not in str(pacer.state)


@pytest.mark.parametrize("value,expected", [("2m59.56s", 179.56), ("7.66s", 7.66), ("25ms", .025), (None, 0), ("invalid", 0)])
def test_reset_duration_parser(value, expected):
    assert duration_seconds(value) == pytest.approx(expected)


def test_transport_preserves_production_user_agent_and_discards_unsafe_headers(monkeypatch):
    import evaluation.provider_pacing as module
    seen = {}
    class Response:
        status = 200
        headers = {"x-ratelimit-remaining-tokens": "4000", "set-cookie": "private"}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return b'{"choices":[]}'
    def open_request(request, timeout):
        seen.update(request.header_items())
        return Response()
    monkeypatch.setattr(module, "urlopen", open_request)
    pacer = ProviderPacer(clock=lambda: 100)
    call = {}
    assert pacer.transport("POST", "https://api.groq.com/chat", {}, 10,
        {"Authorization": "Bearer synthetic"}, call=call) == (200, {"choices": []})
    assert seen["User-agent"] == "site-progress-agent/0.1"
    assert "private" not in str(call)
