"""Verify recorded application settings by inspecting effective adapter payloads."""
import pytest

from app.llm.groq import GroqChatAdapter
from app.llm.ollama import OllamaChatAdapter
from app.llm.openrouter import OpenRouterChatAdapter


@pytest.mark.parametrize('model,effort', [('openai/gpt-oss-20b', 'low'),
                                         ('openai/gpt-oss-120b', 'low'), ('other-model', None)])
def test_groq_effective_reasoning_is_fixed_and_temperature_is_recorded(model, effort):
    seen = {}
    def transport(method, url, payload, timeout, headers):
        seen.update(payload)
        return 200, {'model': model, 'choices': [
            {'finish_reason': 'stop', 'message': {'content': '{}'}}]}
    adapter = GroqChatAdapter(model, bearer_token='synthetic', transport=transport)
    result = adapter.chat(system='JSON', user='synthetic', schema={'type': 'object'},
                          settings={'reasoning_effort': 'medium', 'num_predict': 9000})
    assert seen['temperature'] == 0
    assert seen.get('reasoning_effort') == effort
    assert seen['max_completion_tokens'] == 8112
    assert 'num_ctx' not in seen
    assert adapter.max_retries == 0 and result.settings_hash


def test_openrouter_records_temperature_and_does_not_send_reasoning_override():
    seen = {}
    def transport(method, url, payload, timeout, headers):
        seen.update(payload)
        return 200, {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}
    adapter = OpenRouterChatAdapter('test-model', bearer_token='synthetic', transport=transport)
    adapter.chat(system='JSON', user='synthetic', schema={'type': 'object'},
                 settings={'temperature': .3, 'reasoning_effort': 'medium', 'num_predict': 9000})
    assert seen['temperature'] == .3 and seen['max_tokens'] == 1536
    assert 'reasoning_effort' not in seen and 'reasoning' not in seen
    assert adapter.max_retries == 0


@pytest.mark.parametrize('think', [False, True, None])
def test_ollama_records_think_and_bounded_generation_options(think):
    seen = {}
    def transport(method, url, payload, timeout, headers):
        seen.update(payload)
        return 200, {'message': {'content': '{}'}}
    adapter = OllamaChatAdapter('http://localhost:11434', 'test-model', transport=transport,
                                think=think, max_retries=0)
    adapter.chat(system='JSON', user='synthetic', schema={'type': 'object'},
                 settings={'num_ctx': 90000, 'num_predict': 90000})
    assert seen['options'] == dict(temperature=0, num_ctx=8192, num_predict=1536)
    assert ('think' in seen) == (think is not None)
    if think is not None:
        assert seen['think'] is think
