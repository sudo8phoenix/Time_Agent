"""Select model providers from trusted runtime configuration."""
from __future__ import annotations

from typing import Literal, NamedTuple


Role = Literal["orchestrator", "extraction", "selection"]
Provider = Literal["ollama", "groq", "openrouter"]
KeySlot = Literal[0, 1, 2]


class RoleProviderConfig(NamedTuple):
    """Trusted model assignment for one registered application role."""

    provider: Provider | None = None
    model: str | None = None
    key_slot: KeySlot = 0


def role_provider_config(settings) -> dict[Role, RoleProviderConfig]:
    """Build the fixed role map; values come only from validated settings."""
    return {
        role: RoleProviderConfig(
            getattr(settings, f"{role}_provider", None),
            getattr(settings, f"{role}_model", None),
            getattr(settings, f"{role}_key_slot", 0),
        )
        for role in ("orchestrator", "extraction", "selection")
    }


def create_adapter(settings, *, timeout, model_name=None, provider=None, role: Role | None = None):
    """Construct the selected adapter without accepting provider data from prompts."""
    assignment = role_provider_config(settings).get(role) if role else None
    provider = provider or (assignment.provider if assignment else None) or getattr(settings, "llm_provider", "ollama")
    model_name = model_name or (assignment.model if assignment else None)
    key_slot = assignment.key_slot if assignment else 0

    if provider == "groq":
        from .groq import GroqChatAdapter
        from .account_scopes import resolve_scope
        key = {
            0: settings.groq_api_key,
            1: getattr(settings, "groq_api_key_1", None),
            2: getattr(settings, "groq_api_key_2", None),
        }.get(key_slot)
        return GroqChatAdapter(model_name or settings.groq_model,
            bearer_token=key.get_secret_value() if key else None,
            timeout=timeout, max_retries=0, capacity_scope=resolve_scope(settings, key_slot))
    if provider == "openrouter":
        from .openrouter import OpenRouterChatAdapter
        token = getattr(settings, "openrouter_api_key", None)
        model = model_name or getattr(settings, "openrouter_model", None)
        return OpenRouterChatAdapter(model,
            bearer_token=token.get_secret_value() if token else None,
            timeout=timeout, max_retries=0)
    if provider != "ollama":
        raise ValueError("Unknown model provider")
    from .ollama import OllamaChatAdapter
    return OllamaChatAdapter(settings.ollama_base_url, model_name or settings.ollama_model,
        timeout=timeout, max_retries=0,
        bearer_token=settings.ollama_api_key.get_secret_value() if settings.ollama_api_key else None)
