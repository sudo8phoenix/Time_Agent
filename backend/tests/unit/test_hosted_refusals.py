import pytest

from app.llm.groq import GroqChatAdapter
from app.llm.ollama import OllamaResponseError
from app.llm.openrouter import OpenRouterChatAdapter


@pytest.mark.parametrize('adapter_type', [GroqChatAdapter, OpenRouterChatAdapter])
def test_schema_valid_refusal_never_becomes_a_successful_application_result(adapter_type):
    calls = []
    def transport(*args):
        calls.append(args)
        return 200, {'model': 'fixture-model', 'choices': [{'finish_reason': 'stop', 'message': {
            'content': '{"ok":true}', 'refusal': 'private refusal text must not be exported'}}]}
    adapter = adapter_type('fixture-model', bearer_token='test-key', max_retries=0, transport=transport)
    with pytest.raises(OllamaResponseError, match='refused') as error:
        adapter.chat(system='s', user='u', schema={'type': 'object', 'required': ['ok']})
    assert 'private refusal' not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize('adapter_type', [GroqChatAdapter, OpenRouterChatAdapter])
def test_empty_refusal_marker_does_not_reject_normal_response(adapter_type):
    adapter = adapter_type('fixture-model', bearer_token='test-key', transport=lambda *args: (
        200, {'model': 'fixture-model', 'choices': [{'finish_reason': 'stop', 'message': {
            'content': '{"ok":true}', 'refusal': None}}]}))
    assert adapter.chat(system='s', user='u', schema={'type': 'object'}).value == {'ok': True}


@pytest.mark.parametrize('adapter_type', [GroqChatAdapter, OpenRouterChatAdapter])
@pytest.mark.parametrize('choice', [None, 'private malformed choice', {'message': None}, {'message': 'private malformed message'}])
def test_malformed_message_is_a_sanitized_response_failure(adapter_type, choice):
    adapter = adapter_type('fixture-model', bearer_token='test-key', transport=lambda *args: (
        200, {'choices': [choice]}))
    with pytest.raises(OllamaResponseError) as error:
        adapter.chat(system='s', user='u', schema={'type': 'object'})
    assert 'private malformed' not in str(error.value)
