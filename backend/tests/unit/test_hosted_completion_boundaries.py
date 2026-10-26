"""Production hosted-completion parsing boundaries with injected responses."""
import pytest

from app.llm.groq import GroqChatAdapter, GroqTruncatedResponseError
from app.llm.ollama import OllamaResponseError
from app.llm.openrouter import OpenRouterChatAdapter


ADAPTERS = (GroqChatAdapter, OpenRouterChatAdapter)
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}},
          "required": ["ok"], "additionalProperties": False}


def completion(*, content='{"ok":true}', finish_reason="stop", refusal=None, extra=None):
    message = {"content": content}
    if extra is not None:
        message.update(extra)
    if refusal is not None:
        message["refusal"] = refusal
    return {"model": "fixture", "choices": [{"finish_reason": finish_reason, "message": message}]}


@pytest.mark.parametrize("adapter_type", ADAPTERS)
@pytest.mark.parametrize("body", [
    [],
    {},
    {"choices": "not-an-array"},
    {"choices": []},
    {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}},
                  {"finish_reason": "stop", "message": {"content": '{"ok":false}'}}]},
    {"choices": [None]},
    {"choices": [{"finish_reason": "stop", "message": None}]},
    completion(content="", finish_reason="stop"),
    completion(content=None, finish_reason="stop"),
    completion(content="   ", finish_reason="stop"),
    completion(content='{"ok":', finish_reason="length"),
    completion(content='{"ok":true}', finish_reason="length"),
    completion(content='{"ok":true}', finish_reason="content_filter"),
    completion(content='{"ok":true}', finish_reason=None),
    completion(content='[true]', finish_reason="stop"),
    completion(content='{"ok":"true"}', finish_reason="stop"),
    completion(content='{"ok":true,"private":"extra"}', finish_reason="stop"),
    completion(content='{"ok":true}', finish_reason="stop", refusal="private refusal"),
])
def test_non_single_complete_schema_valid_object_is_never_accepted(adapter_type, body):
    calls = []

    def transport(*args):
        calls.append(args)
        return 200, body

    adapter = adapter_type("fixture-model", bearer_token="test-key", transport=transport)
    with pytest.raises(OllamaResponseError):
        adapter.chat(system="system", user="synthetic", schema=SCHEMA)
    assert len(calls) == 1


@pytest.mark.parametrize("adapter_type", ADAPTERS)
def test_single_complete_schema_valid_object_is_accepted(adapter_type):
    calls = []

    def transport(*args):
        calls.append(args)
        return 200, completion()

    adapter = adapter_type("fixture-model", bearer_token="test-key", transport=transport)
    assert adapter.chat(system="system", user="synthetic", schema=SCHEMA).value == {"ok": True}
    assert len(calls) == 1


@pytest.mark.parametrize("adapter_type", ADAPTERS)
@pytest.mark.parametrize("finish_reason", ["length", "content_filter", "tool_calls", None])
def test_every_non_stop_finish_reason_is_rejected_as_incomplete(adapter_type, finish_reason):
    adapter = adapter_type("fixture-model", bearer_token="test-key", transport=lambda *args: (
        200, completion(finish_reason=finish_reason)))
    truncated = adapter_type is GroqChatAdapter and finish_reason == "length"
    error = GroqTruncatedResponseError if truncated else OllamaResponseError
    with pytest.raises(error, match="output limit" if truncated else "incomplete"):
        adapter.chat(system="system", user="synthetic", schema=SCHEMA)
