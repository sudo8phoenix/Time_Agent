import pytest
from app.llm.groq import GroqChatAdapter
from app.llm.ollama import OllamaConfigurationError, OllamaResponseError
from app.llm.provider import create_adapter
from app.settings import Settings


def test_groq_payload_and_result():
    seen = {}
    def transport(method, url, payload, timeout, headers):
        seen.update(payload)
        assert url == 'https://api.groq.com/openai/v1/chat/completions'
        assert headers == {'Authorization': 'Bearer test-key'}
        return 200, {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}]}
    adapter = GroqChatAdapter('openai/gpt-oss-20b', bearer_token='test-key', transport=transport)
    result = adapter.chat(system='JSON', user={'request': 'ok'}, schema={'type': 'object'},
                          settings={'num_predict': 9000, 'num_ctx': 8192})
    assert result.value == {'ok': True}
    assert result.runtime == 'groq'
    assert seen['max_completion_tokens'] == 1536
    assert seen['reasoning_effort'] == 'low'
    assert 'options' not in seen
    assert seen['response_format']['json_schema']['schema'] == {'type': 'object'}


@pytest.mark.parametrize('body', [
    {}, {'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]},
    {'choices': [{'finish_reason': 'stop', 'message': {'content': '[]'}}]},
])
def test_invalid_response(body):
    adapter = GroqChatAdapter('model', bearer_token='key', transport=lambda *args: (200, body))
    with pytest.raises(OllamaResponseError):
        adapter.chat(system='JSON', user='ok', schema={})


def test_rejects_json_that_does_not_match_local_schema():
    adapter = GroqChatAdapter('model', bearer_token='key', transport=lambda *args: (
        200, {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":"yes"}'}}]}))
    with pytest.raises(OllamaResponseError, match='did not match'):
        adapter.chat(system='JSON', user='ok', schema={
            'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']})


def test_missing_key():
    with pytest.raises(OllamaConfigurationError):
        create_adapter(Settings(_env_file=None, llm_provider='groq'), timeout=30)
