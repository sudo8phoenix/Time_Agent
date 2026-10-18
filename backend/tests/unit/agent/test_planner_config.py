from types import SimpleNamespace

import pytest

from app.agent.planner import (
    ALLOWED_PLANNER_MODELS,
    PlannerConfigurationError,
    create_planner,
)


class Adapter:
    def chat(self, **kwargs):
        return kwargs


def test_groq_planner_preserves_separate_credential_assignment():
    settings = SimpleNamespace(orchestrator_provider="groq",
                               orchestrator_model="openai/gpt-oss-120b",
                               orchestrator_key_slot=1, extraction_key_slot=0,
                               selection_key_slot=0)
    calls = []

    def factory(actual_settings, *, timeout, role):
        calls.append((actual_settings.orchestrator_key_slot, role))
        return Adapter()

    create_planner(settings, timeout=17, adapter_factory=factory)
    assert calls == [(1, "orchestrator")]
    assert settings.extraction_key_slot == settings.selection_key_slot == 0


@pytest.mark.parametrize("model", sorted(ALLOWED_PLANNER_MODELS))
def test_planner_accepts_allowlisted_openrouter_models_and_honors_pinned_model(model):
    settings = SimpleNamespace(orchestrator_provider="openrouter", orchestrator_model=model)
    calls = []

    def factory(actual_settings, *, timeout, role):
        calls.append((actual_settings, timeout, role))
        return Adapter()

    planner = create_planner(settings, timeout=17, adapter_factory=factory)

    assert calls == [(settings, 17, "orchestrator")]
    assert planner(messages=[{"role": "user", "content": "synthetic"}]) == {
        "messages": [{"role": "user", "content": "synthetic"}]
    }


@pytest.mark.parametrize(("provider", "model"), [
    ("groq", "nvidia/nemotron-3-super-120b-a12b:free"),
    ("ollama", "nvidia/nemotron-3.5-super-vl:free"),
    ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b"),
    ("openrouter", "nvidia/nemotron-3-super-120b-a12b"),
    ("openrouter", "openrouter/auto:free"),
    ("openrouter", "some/unknown-model:free"),
    ("openrouter", None),
    (None, "nvidia/nemotron-3-ultra-550b-a55b:free"),
])
def test_planner_rejects_unapproved_provider_or_model_before_adapter_call(provider, model):
    settings = SimpleNamespace(orchestrator_provider=provider, orchestrator_model=model)
    calls = []

    def factory(*args, **kwargs):
        calls.append((args, kwargs))
        return Adapter()

    with pytest.raises(PlannerConfigurationError):
        create_planner(settings, timeout=17, adapter_factory=factory)

    assert calls == []


def test_planner_requires_exact_pinned_model_id():
    settings = SimpleNamespace(orchestrator_provider="openrouter",
                               orchestrator_model=" nvidia/nemotron-3-super-120b-a12b:free ")
    with pytest.raises(PlannerConfigurationError):
        create_planner(settings, timeout=17, adapter_factory=lambda *args, **kwargs: Adapter())
