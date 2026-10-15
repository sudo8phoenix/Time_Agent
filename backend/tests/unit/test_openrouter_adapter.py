import pytest

from app.llm.ollama import OllamaConfigurationError, OllamaResponseError, OllamaTransportError
from app.llm.openrouter import OpenRouterChatAdapter
from app.settings import Settings
from app.llm.provider import create_adapter


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def test_sends_bounded_json_schema_request_and_returns_llm_result():
    observed = {}

    def transport(method, url, payload, timeout, headers):
        observed.update(method=method, url=url, payload=payload, timeout=timeout, headers=headers)
        return 200, {"model": "catalog/model", "choices": [{
            "finish_reason": "stop", "message": {"content": '{"ok":true}'},
        }]}

    adapter = OpenRouterChatAdapter("catalog/model", bearer_token="mock-secret", timeout=11,
                                    transport=transport)
    result = adapter.chat(system="system", user={"prompt": "hello"}, schema=SCHEMA,
                          settings={"num_predict": 9000})
    assert observed["method"] == "POST"
    assert observed["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert observed["timeout"] == 11
    assert observed["headers"] == {"Authorization": "Bearer mock-secret"}
    assert observed["payload"]["max_tokens"] == 1536
    assert "response_format" not in observed["payload"]
    assert result.value == {"ok": True}
    assert result.model == "catalog/model"
    assert result.runtime == "openrouter"
    assert len(result.prompt_hash) == len(result.settings_hash) == 64
    assert "mock-secret" not in repr(result)


@pytest.mark.parametrize("model,key,timeout,retries", [
    (None, "key", 10, 0), (" ", "key", 10, 0), ("model", None, 10, 0),
    ("model", "key", 0, 0), ("model", "key", 901, 0), ("model", "key", 10, 2),
])
def test_rejects_missing_or_unbounded_configuration(model, key, timeout, retries):
    with pytest.raises(OllamaConfigurationError):
        OpenRouterChatAdapter(model, bearer_token=key, timeout=timeout, max_retries=retries,
                              transport=lambda *args: (200, {}))


@pytest.mark.parametrize("body", [
    {}, {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": "[]"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]},
])
def test_rejects_invalid_provider_responses(body):
    adapter = OpenRouterChatAdapter("model", bearer_token="key", transport=lambda *args: (200, body))
    with pytest.raises(OllamaResponseError):
        adapter.chat(system="s", user="u", schema=SCHEMA)


def test_rejects_json_that_does_not_match_local_schema():
    adapter = OpenRouterChatAdapter("model", bearer_token="key", transport=lambda *args: (
        200, {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":"yes"}'}}]}))
    with pytest.raises(OllamaResponseError, match="did not match"):
        adapter.chat(system="s", user="u", schema=SCHEMA)


def test_transport_failure_is_sanitized_and_retry_count_is_bounded():
    calls = 0

    def transport(*args):
        nonlocal calls
        calls += 1
        raise TimeoutError("secret and prompt contents")

    adapter = OpenRouterChatAdapter("model", bearer_token="key", max_retries=1, transport=transport)
    with pytest.raises(OllamaTransportError, match="timed out or failed") as error:
        adapter.chat(system="s", user="private prompt", schema=SCHEMA)
    assert calls == 2
    assert "private prompt" not in str(error.value)
    assert "secret" not in str(error.value)


def test_provider_factory_requires_explicit_openrouter_model():
    settings = Settings(_env_file=None, llm_provider="openrouter", openrouter_api_key="mock")
    with pytest.raises(OllamaConfigurationError, match="explicit OPENROUTER_MODEL"):
        create_adapter(settings, timeout=30)
