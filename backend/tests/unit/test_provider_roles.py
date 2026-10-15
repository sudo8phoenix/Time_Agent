from app.llm.groq import GroqChatAdapter
from app.llm.ollama import OllamaChatAdapter
from app.llm.openrouter import OpenRouterChatAdapter
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
