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
    assert seen['max_completion_tokens'] == 8112
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


@pytest.mark.parametrize('body,category', [
    ({'choices': [{'finish_reason': 'length', 'message': {'content': '{'}}]}, 'MODEL_OUTPUT_TRUNCATED'),
    ({'choices': [{'finish_reason': 'stop', 'message': {'content': 'private invalid text'}}]}, 'MODEL_JSON_INVALID'),
    ({'choices': [{'finish_reason': 'stop', 'message': {'content': '[]'}}]}, 'MODEL_JSON_INVALID'),
    ({'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":"yes"}'}}]}, 'MODEL_SCHEMA_MISMATCH'),
    ({'choices': [{'finish_reason': 'stop', 'message': {'refusal': 'private refusal'}}]}, 'MODEL_REFUSED'),
    ({}, 'MODEL_ENVELOPE_INVALID'),
    ({'choices': [{'finish_reason': 'stop', 'message': {}}]}, 'MODEL_ENVELOPE_INVALID'),
])
def test_response_failure_diagnostics_are_specific_and_safe(body, category):
    from app.agent.tools import AgentToolError, _failure_category
    adapter = GroqChatAdapter('model', bearer_token='key', transport=lambda *args: (200, body))
    with pytest.raises(OllamaResponseError) as failure:
        adapter.chat(system='JSON', user='ok', schema={
            'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']})
    assert _failure_category(failure.value) == category
    assert AgentToolError('AGENT_TOOL_FAILED', 'Safe', failure_category=category).failure_category == category
    assert 'private' not in str(failure.value)


def test_strict_extraction_schema_requires_defaults_without_mutating_original():
    from app.llm.extract import extraction_schema
    from app.llm.groq import _response_schema
    schema = extraction_schema()
    prepared, strict = _response_schema(schema, 'openai/gpt-oss-20b')
    assert strict is True
    assert 'lifecycle_effects' not in schema['$defs']['Observation']['required']
    assert 'lifecycle_effects' in prepared['$defs']['Observation']['required']
    assert prepared['$defs']['Observation']['additionalProperties'] is False


@pytest.mark.parametrize('model,schema', [
    ('other-model', {'type': 'object', 'additionalProperties': False}),
    ('openai/gpt-oss-20b', {'type': 'object', 'additionalProperties': {'type': 'string'}}),
])
def test_incompatible_schemas_keep_original_contract(model, schema):
    from app.llm.groq import _response_schema
    assert _response_schema(schema, model) == (schema, False)


def test_provider_schema_simplification_keeps_local_array_bounds():
    from app.llm.groq import _response_schema, _validate_schema
    schema = {'type': 'object', 'additionalProperties': False, 'properties': {
        'values': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 1}}, 'required': ['values']}
    prepared, strict = _response_schema(schema, 'openai/gpt-oss-20b')
    assert strict
    assert 'maxItems' not in prepared['properties']['values']
    assert schema['properties']['values']['maxItems'] == 1
    with pytest.raises(OllamaResponseError):
        _validate_schema({'values': ['a', 'b']}, schema)


def test_strict_nullable_enum_avoids_ambiguous_reference_union():
    from app.llm.extract import extraction_schema
    from app.llm.groq import _response_schema
    prepared, strict = _response_schema(extraction_schema(), 'openai/gpt-oss-20b')
    assert strict
    unit = prepared['$defs']['Observation']['properties']['unit']
    assert unit['type'] == ['string', 'null']
    assert 'kg' in unit['enum'] and None in unit['enum']
    assert 'anyOf' not in unit


def test_qwen_planner_uses_strict_closed_routing_schema():
    from app.agent.hierarchy import SupervisorDecision
    seen = {}
    def transport(method, url, payload, timeout, headers):
        seen.update(payload)
        return 200, {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"action":"analysis"}'}}]}
    adapter = GroqChatAdapter('qwen/qwen3.8-27b', bearer_token='test-key', transport=transport)
    adapter.chat(system='Route', user='analysis', schema=SupervisorDecision.model_json_schema(),
                 settings={'num_predict': 128})
    contract = seen['response_format']['json_schema']
    assert contract['strict'] is True
    assert contract['schema']['additionalProperties'] is False
    assert contract['schema']['required'] == ['action']
    assert seen['max_completion_tokens'] == 128
