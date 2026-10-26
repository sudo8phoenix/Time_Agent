from app.llm.groq import GroqChatAdapter
from app.llm.ollama import OllamaChatAdapter
from app.llm.openrouter import OpenRouterChatAdapter
from app.llm.gonka import GonkaChatAdapter
from app.llm.provider import create_adapter, role_provider_config
from app.settings import Settings


def test_roles_default_to_existing_provider_and_model_settings():
    settings = Settings(_env_file=None, llm_provider="groq", groq_api_key="base")
    mapping = role_provider_config(settings)
    assert set(mapping) == {"orchestrator", "extraction", "selection"}
    assert all(config.provider is None and config.model is None and config.key_slot == 0
               for config in mapping.values())
    assert isinstance(create_adapter(settings, timeout=30, role="selection"), GroqChatAdapter)


def test_role_assignments_choose_provider_model_and_explicit_groq_key_slot():
    settings = Settings(_env_file=None,
        orchestrator_provider="openrouter", orchestrator_model="catalog/planner",
        openrouter_api_key="openrouter-mock",
        extraction_provider="groq", extraction_model="groq/extract", extraction_key_slot=1,
        groq_api_key_1="slot-one-mock",
        selection_provider="ollama", selection_model="local/selector")
    planner = create_adapter(settings, timeout=30, role="orchestrator")
    extraction = create_adapter(settings, timeout=30, role="extraction")
    selection = create_adapter(settings, timeout=30, role="selection")
    assert isinstance(planner, OpenRouterChatAdapter) and planner.model == "catalog/planner"
    assert isinstance(extraction, GroqChatAdapter) and extraction.model == "groq/extract"
    assert extraction._token == "slot-one-mock"
    assert isinstance(selection, OllamaChatAdapter) and selection.model == "local/selector"


def test_role_provider_override_wins_over_global_default():
    settings = Settings(_env_file=None, llm_provider="ollama", groq_api_key="groq-mock",
                        selection_provider="groq", selection_key_slot=0)
    adapter = create_adapter(settings, timeout=30, role="selection")
    assert isinstance(adapter, GroqChatAdapter)


def test_gonka_roles_use_the_same_broker_key_and_pinned_models():
    settings = Settings(_env_file=None, gonka_broker_llm="broker-mock",
        orchestrator_provider="gonka", orchestrator_model="MiniMaxAI/MiniMax-M2.7",
        selection_provider="gonka", selection_model="deepseek-ai/DeepSeek-V4-Flash-0731")
    planner = create_adapter(settings, timeout=30, role="orchestrator")
    selector = create_adapter(settings, timeout=30, role="selection")
    assert isinstance(planner, GonkaChatAdapter)
    assert isinstance(selector, GonkaChatAdapter)
    assert planner.model == "MiniMaxAI/MiniMax-M2.7"
    assert selector.model == "deepseek-ai/DeepSeek-V4-Flash-0731"
    assert planner._token == selector._token == "broker-mock"


def test_gonka_adapter_targets_broker_and_reports_runtime():
    observed = {}

    def transport(method, url, payload, timeout, headers):
        observed.update(url=url, model=payload["model"], headers=headers)
        return 200, {"choices": [{"finish_reason": "stop",
                                 "message": {"content": '{"action":"intake"}'}}]}

    adapter = GonkaChatAdapter("MiniMaxAI/MiniMax-M2.7", bearer_token="broker-mock",
                               transport=transport)
    result = adapter.chat(system="choose", user={"legal_actions": ["intake"]},
                          schema={"type": "object", "properties": {"action": {"type": "string"}},
                                  "required": ["action"]})
    assert observed["url"] == "https://proxy.gonkabroker.com/v1/chat/completions"
    assert observed["model"] == "MiniMaxAI/MiniMax-M2.7"
    assert observed["headers"] == {"Authorization": "Bearer broker-mock"}
    assert result.runtime == "gonka"


def test_gonka_adapter_has_room_for_full_report_extraction():
    observed = {}

    def transport(method, url, payload, timeout, headers):
        observed.update(payload)
        return 200, {"choices": [{"finish_reason": "stop",
                                 "message": {"content": '{"ok":true}'}}]}

    adapter = GonkaChatAdapter("deepseek-ai/DeepSeek-V4-Flash-0731",
                               bearer_token="broker-mock", transport=transport)
    adapter.chat(system="extract", user="report",
                 schema={"type": "object", "properties": {"ok": {"type": "boolean"}},
                         "required": ["ok"]}, settings={"num_predict": 15000})
    assert observed["max_tokens"] == 4096


def test_gonka_adapter_accepts_only_a_complete_json_fence():
    adapter = GonkaChatAdapter("deepseek-ai/DeepSeek-V4-Flash-0731",
        bearer_token="broker-mock", transport=lambda *args: (200, {
            "choices": [{"finish_reason": "stop", "message": {
                "content": '```json\n{"ok":true}\n```'}}]}))
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"]}
    assert adapter.chat(system="s", user="u", schema=schema).value == {"ok": True}
