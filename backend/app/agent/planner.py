"""Configuration guard for the bounded, model-assisted report planner."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


ALLOWED_PLANNER_MODELS = frozenset({
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
})


class PlannerConfigurationError(ValueError):
    """Safe failure for an unsupported planner provider/model assignment."""


def create_planner(settings: Any, *, timeout: float,
                   adapter_factory: Callable[..., Any] | None = None) -> Callable[..., Any]:
    """Validate the persisted orchestrator assignment and return its chat callable.

    This guard is intentionally independent of runtime.py so configuration errors
    cannot create an import cycle. Only explicitly supported provider/model pairs
    are accepted; saved OpenRouter assignments remain valid.
    """
    provider = getattr(settings, "orchestrator_provider", None)
    model = getattr(settings, "orchestrator_model", None)
    supported = ((provider == "openrouter" and model in ALLOWED_PLANNER_MODELS)
                 or (provider == "groq" and model in {
                     "openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b",
                 }))
    if not supported:
        raise PlannerConfigurationError("Unsupported planner configuration")

    if adapter_factory is None:
        from ..llm.provider import create_adapter

        adapter_factory = create_adapter
    return adapter_factory(settings, timeout=timeout, role="orchestrator").chat
