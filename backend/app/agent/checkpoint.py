"""Strict serializer for the bounded set of historical agent checkpoint types."""
from __future__ import annotations

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from ..schemas.common import (
    DateBasis,
    Discipline,
    Evidence,
    EventType,
    MappingState,
    MatchStrength,
    MeasurementBasis,
    ObservedStatus,
    QuantityKind,
    ReviewState,
    Unit,
    WorkType,
)
from ..schemas.events import (
    Endpoint,
    EndpointPrecision,
    LifecycleEffect,
    LifecycleKind,
    LifecycleScope,
)
from ..schemas.matching import Candidate, Proposal
from ..schemas.observation import Observation
from .state import AgentCounters, AgentState, HierarchicalAgentState, AgentWarning, ModelMetadata, ValidationErrorRecord


# Exact historical application types only. LangGraph's safe built-ins remain
# available; arbitrary app modules and dynamically generated models are not.
_LEGACY_TYPES = (
    AgentCounters,
    AgentState,
    HierarchicalAgentState,
    AgentWarning,
    Candidate,
    DateBasis,
    Discipline,
    Endpoint,
    EndpointPrecision,
    Evidence,
    EventType,
    LifecycleEffect,
    LifecycleKind,
    LifecycleScope,
    MappingState,
    MatchStrength,
    MeasurementBasis,
    ModelMetadata,
    Observation,
    ObservedStatus,
    Proposal,
    QuantityKind,
    ReviewState,
    Unit,
    ValidationErrorRecord,
    WorkType,
)

_LEGACY_JSON_IDS = tuple(
    tuple(cls.__module__.split(".")) + (cls.__name__,) for cls in _LEGACY_TYPES
)


def make_checkpoint_serializer() -> JsonPlusSerializer:
    """Build a non-pickle serializer with exact legacy state/schema allowlists."""
    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_json_modules=_LEGACY_JSON_IDS,
        allowed_msgpack_modules=_LEGACY_TYPES,
    )
