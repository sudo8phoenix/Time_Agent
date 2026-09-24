import pytest

from app.llm.ollama import (
    OllamaChatAdapter,
    OllamaConfigurationError,
    OllamaResponseError,
    OllamaTransportError,
)


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def response_transport(content='{"ok": true}'):
    def transport(method, url, payload, timeout, headers):
        assert url.endswith("/api/chat")
        assert payload["stream"] is False
        assert payload["format"] == SCHEMA
        assert payload["think"] is False
        assert payload["options"] == {"temperature": 0.0, "num_ctx": 8192, "num_predict": 1536}
        return 200, {"model": "fixture", "message": {"content": content}, "digest": "sha256:x", "runtime": "fixture"}
    return transport


def test_validates_and_records_hashes_and_model_metadata():
    result = OllamaChatAdapter("http://127.0.0.1:11434", "fixture", transport=response_transport()).chat(
        system="s", user="u", schema=SCHEMA
    )
    assert result.value == {"ok": True}
    assert result.model_digest == "sha256:x"
    assert len(result.settings_hash) == 64 and len(result.prompt_hash) == 64


def test_generation_settings_cannot_expand_reviewed_resource_caps():
    seen = {}

    def transport(method, url, payload, timeout, headers):
        seen.update(payload["options"])
        return 200, {"message": {"content": '{"ok": true}'}}

    OllamaChatAdapter(
        "http://127.0.0.1:11434", "fixture", transport=transport
    ).chat(
        system="s",
        user="u",
        schema=SCHEMA,
        settings={"num_ctx": 999999, "num_predict": 999999},
    )
    assert seen["num_ctx"] == 8192
    assert seen["num_predict"] == 1536


@pytest.mark.parametrize("setting", [{"num_ctx": 0}, {"num_predict": "invalid"}])
def test_invalid_generation_limits_fail_closed(setting):
    with pytest.raises(OllamaConfigurationError, match="positive integers"):
        OllamaChatAdapter(
            "http://127.0.0.1:11434", "fixture", transport=response_transport()
        ).chat(system="s", user="u", schema=SCHEMA, settings=setting)


def test_timeout_is_bounded_and_retried_once():
    calls = 0
    def transport(*args):
        nonlocal calls
        calls += 1
        raise TimeoutError("fixture timeout")
    with pytest.raises(OllamaTransportError):
        OllamaChatAdapter("http://127.0.0.1:11434", "fixture", transport=transport).chat(system="s", user="u", schema=SCHEMA)
    assert calls == 2


def test_malformed_json_fails_closed():
    with pytest.raises(OllamaResponseError, match="malformed JSON"):
        OllamaChatAdapter("http://127.0.0.1:11434", "fixture", transport=response_transport("nope")).chat(system="s", user="u", schema=SCHEMA)


def test_missing_model_is_visible():
    def missing(method, url, payload, timeout, headers):
        return 404, {"error": "not found"}
    with pytest.raises(OllamaResponseError, match="not installed"):
        OllamaChatAdapter("http://127.0.0.1:11434", "missing", transport=missing).chat(system="s", user="u", schema=SCHEMA)


@pytest.mark.parametrize("url", ["https://8.8.8.8:11434", "http://example.com:11434", "file:///tmp/ollama"])
def test_blocks_untrusted_endpoint_configuration(url):
    with pytest.raises(OllamaConfigurationError):
        OllamaChatAdapter(url, "fixture", transport=response_transport())


def test_accepts_tailscale_cgnat_address():
    adapter = OllamaChatAdapter("http://100.100.20.5:11434", "fixture", transport=response_transport())
    assert adapter.base_url == "http://100.100.20.5:11434"


def test_adds_optional_bearer_auth_without_exposing_token(monkeypatch):
    seen = {}

    def transport(method, url, payload, timeout, headers):
        seen.update(headers)
        return 200, {"message": {"content": '{"ok":true}'}}

    secret = "only-on-server"
    result = OllamaChatAdapter("https://100.100.20.5:11434", "fixture",
                               bearer_token=secret, transport=transport).chat(
                                   system="s", user="u", schema=SCHEMA)
    assert seen == {"Authorization": f"Bearer {secret}"}
    assert secret not in repr(result)


def test_health_reports_runtime_and_digest_without_requesting_chat():
    def transport(method, url, payload, timeout, headers):
        if url.endswith("/api/version"):
            return 200, {"version": "0.23.2"}
        if url.endswith("/api/tags"):
            return 200, {"models": [{"name": "fixture", "digest": "sha256:model"}]}
        assert url.endswith("/api/show")
        return 200, {"details": {"family": "fixture", "parameter_size": "4B",
                                  "quantization_level": "Q4_K_M"}}

    result = OllamaChatAdapter("http://100.100.20.5:11434", "fixture", transport=transport).health()
    assert result == {"ok": True, "runtime": "0.23.2", "model": "fixture",
                      "installed": True, "model_digest": "sha256:model",
                      "model_metadata": {"family": "fixture", "parameter_size": "4B",
                                         "quantization_level": "Q4_K_M"}}


def test_https_tailscale_hostname_may_use_default_port(monkeypatch):
    monkeypatch.setattr("app.llm.ollama.socket.getaddrinfo",
                        lambda host, port: [(None, None, None, None, ("100.100.20.5", port))])
    adapter = OllamaChatAdapter("https://ollama.example.ts.net", "fixture",
                                transport=response_transport())
    assert adapter.base_url == "https://ollama.example.ts.net"


def test_rejects_header_injection_token():
    with pytest.raises(OllamaConfigurationError, match="invalid header"):
        OllamaChatAdapter("http://127.0.0.1:11434", "fixture", bearer_token="bad\nvalue")
