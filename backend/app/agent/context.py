"""Ephemeral invocation dependencies; this object is never checkpointed."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class AgentRuntimeContext:
    session_factory: Callable[..., Any]
    lease_token: str
    model_callable: Callable[..., Any]
    embedder: Callable[..., Any] | None
    heartbeat_callback: Callable[..., Any]
    shutdown_callback: Callable[..., Any]
    clock: Callable[..., Any]
