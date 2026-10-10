"""Atomic, evidence-grounded observation extraction.

This module has no database or network side effects.  The model callable is injected
so worker jobs and tests can use the local adapter or deterministic fixtures.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Mapping, Sequence

from pydantic import ValidationError

from ..schemas.observation import Observation, ObservationBatch
from ..schemas.common import EventType, DateBasis, QuantityKind
from ..prompts.extraction_v1 import PROMPT_VERSION, SYSTEM_PROMPT

MAX_BATCH_CHARS = 12000
MAX_FRAGMENTS = 8


@dataclass(frozen=True)
class FragmentInput:
    fragment_id: str
    locator: str
    text: str
    ordinal: int = 0


@dataclass(frozen=True)
class BatchInput:
    batch_id: str
    fragments: tuple[FragmentInput, ...]
    report_date: date | None = None
    report_date_trusted: bool = False


@dataclass(frozen=True)
class ExtractionMetadata:
    prompt_version: str
    prompt_hash: str
    settings_hash: str
    model: str
    model_digest: str | None
    runtime: str | None
    batch_id: str


@dataclass(frozen=True)
class ExtractionResult:
    observations: tuple[Observation, ...]
    metadata: ExtractionMetadata
    errors: tuple[str, ...] = ()


class ExtractionError(ValueError):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def build_batches(fragments: Sequence[FragmentInput], *, report_date: date | None = None,
                  report_date_trusted: bool = False, max_chars: int = MAX_BATCH_CHARS) -> tuple[BatchInput, ...]:
    """Pack bounded contiguous fragments while retaining source identity."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    batches: list[BatchInput] = []
    current: list[FragmentInput] = []
    size = 0
    for fragment in fragments:
        if not fragment.text.strip():
            continue
        if len(fragment.text) > max_chars:
            raise ExtractionError(f"fragment {fragment.fragment_id} exceeds batch limit")
        if current and (len(current) >= MAX_FRAGMENTS or size + len(fragment.text) > max_chars):
            batches.append(BatchInput(f"batch-{len(batches)+1}", tuple(current), report_date, report_date_trusted))
            current, size = [], 0
        current.append(fragment)
        size += len(fragment.text)
    if current:
        batches.append(BatchInput(f"batch-{len(batches)+1}", tuple(current), report_date, report_date_trusted))
    return tuple(batches)


def extraction_schema() -> dict[str, Any]:
    return ObservationBatch.model_json_schema()


def _context(batch: BatchInput) -> str:
    header = f"Trusted report date: {batch.report_date.isoformat()}\n" if batch.report_date_trusted and batch.report_date else ""
    return header + "\n\n".join(f"[{f.fragment_id} | {f.locator}]\n{f.text}" for f in batch.fragments)


def _resolve_relative(value: date | None, basis: DateBasis, batch: BatchInput) -> tuple[date | None, DateBasis]:
    if value is not None:
        return value, basis
    return value, basis


def _validate_evidence(observation: Observation, fragments: Sequence[FragmentInput]) -> None:
    by_id = {f.fragment_id: f.text for f in fragments}
    for evidence in [*observation.evidence, *(ev for effect in observation.lifecycle_effects for ev in effect.evidence)]:
        source = by_id.get(evidence.fragment_id)
        if source is None or evidence.quote not in source:
            raise ExtractionError(f"evidence quote is not present in fragment {evidence.fragment_id}")
        # A repeated quote is ambiguous unless the model gives a locator field that
        # disambiguates it.  Evidence fields are the only permitted locator metadata.
        if source.count(evidence.quote) > 1 and not any("occurrence" in f.lower() or "offset" in f.lower() for f in evidence.fields):
            raise ExtractionError(f"evidence quote is ambiguous in fragment {evidence.fragment_id}")


def _fact_key(o: Observation) -> tuple[Any, ...]:
    return (o.discipline, o.work_type, o.event_type, o.observed_status, o.area,
            tuple(sorted(o.asset_tags)), o.explicit_activity_id, o.work_date,
            o.quantity, o.quantity_kind, o.unit, o.blocker, o.summary,
            tuple(effect.model_dump_json() for effect in o.lifecycle_effects))


ModelCall = Callable[..., Any]


_NULL_LITERALS = frozenset({"", "n/a", "na", "none", "null", "unknown"})
_NULLABLE_OBSERVATION_FIELDS = frozenset({
    "area", "explicit_activity_id", "work_date", "quantity", "unit", "raw_unit",
    "reported_percent", "actual_start", "actual_finish", "blocker",
})


def _normalise_nullable_literals(raw: Any) -> Any:
    """Convert model null placeholders to JSON null before strict schema validation.

    Local models occasionally emit ``\"unknown\"`` for optional scalar fields despite
    the supplied JSON schema.  That is absence of a fact, not a malformed report, so
    retain the observation and let the ordinary matching/review safeguards decide
    whether it is actionable.  Required fields and non-placeholder values remain
    strictly validated.
    """
    if not isinstance(raw, Mapping) or not isinstance(raw.get("observations"), list):
        return raw
    normalised = dict(raw)
    observations: list[Any] = []
    for item in raw["observations"]:
        if not isinstance(item, Mapping):
            observations.append(item)
            continue
        observation = dict(item)
        for field in _NULLABLE_OBSERVATION_FIELDS:
            value = observation.get(field)
            if isinstance(value, str) and value.strip().casefold() in _NULL_LITERALS:
                observation[field] = None
        observations.append(observation)
    normalised["observations"] = observations
    return normalised


def _repair_source_stated_clock(raw: Any) -> Any:
    """Repair only clock details repeated in exact source evidence.

    A quoted clock can supply an omitted local time or its minute precision. A
    model-added UTC suffix is removed only when the quote gives a local clock.
    Other timezone-bearing or unsupported clock values still fail validation.
    """
    if not isinstance(raw, Mapping) or not isinstance(raw.get("observations"), list):
        return raw
    repaired = dict(raw)
    observations = []
    for original in raw["observations"]:
        item = dict(original) if isinstance(original, Mapping) else original
        if isinstance(item, dict):
            effects = []
            for original_effect in item.get("lifecycle_effects", []):
                effect = dict(original_effect) if isinstance(original_effect, Mapping) else original_effect
                if isinstance(effect, dict) and isinstance(effect.get("endpoint"), Mapping):
                    endpoint = dict(effect["endpoint"])
                    clock = endpoint.get("local_time")
                    quotes = [e.get("quote", "") for e in effect.get("evidence", []) if isinstance(e, Mapping)]
                    if clock is None and endpoint.get("precision") == "date":
                        match = re.search(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", str(endpoint.get("raw_expression", "")))
                        if match and any(match.group(0) in quote for quote in quotes):
                            endpoint["local_time"] = match.group(0) + ":00"
                            endpoint["precision"] = "minute"
                            effect["endpoint"] = endpoint
                            item["warnings"] = [*item.get("warnings", []),
                                                "source-stated clock restored from date-only model endpoint"]
                    clock = endpoint.get("local_time")
                    if clock is None and endpoint.get("precision") == "minute":
                        match = re.search(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", str(endpoint.get("raw_expression", "")))
                        if match and any(match.group(0) in quote for quote in quotes):
                            endpoint["local_time"] = match.group(0) + ":00"
                            effect["endpoint"] = endpoint
                            item["warnings"] = [*item.get("warnings", []),
                                                "source-stated clock restored to incomplete model endpoint"]
                    clock = endpoint.get("local_time")
                    if (isinstance(clock, str) and endpoint.get("precision") == "date"
                            and len(clock) in {5, 8} and clock[:5] in " ".join(quotes)
                            and (len(clock) == 5 or clock.endswith(":00"))):
                        endpoint["precision"] = "minute"
                        effect["endpoint"] = endpoint
                        item["warnings"] = [*item.get("warnings", []),
                                            "model date precision corrected to source-stated clock minute"]
                    if (isinstance(clock, str) and clock.endswith("Z") and len(clock) == 9
                            and endpoint.get("timezone") is None
                            and any(clock[:5] in quote and "UTC" not in quote and "Z" not in quote
                                    for quote in quotes)):
                        endpoint["local_time"] = clock[:-1]
                        effect["endpoint"] = endpoint
                        item["warnings"] = [*item.get("warnings", []),
                                            "model-added UTC suffix removed from source-local clock"]
                effects.append(effect)
            if "lifecycle_effects" in item:
                item["lifecycle_effects"] = effects
        observations.append(item)
    repaired["observations"] = observations
    return repaired


def extract_batch(batch: BatchInput, model_call: ModelCall, *, model: str = "unknown",
                 model_digest: str | None = None, runtime: str | None = None,
                 settings: Mapping[str, Any] | None = None) -> ExtractionResult:
    """Call an injected model, validate output/evidence, resolve supported dates, dedupe."""
    settings = dict(settings or {"temperature": 0.0})
    user = _context(batch)
    prompt_hash = _hash({"system": SYSTEM_PROMPT, "user": user})
    settings_hash = _hash(settings)
    try:
        raw = model_call(system=SYSTEM_PROMPT, user=user, schema=extraction_schema(), settings=settings)
    except TypeError:
        raw = model_call(SYSTEM_PROMPT, user, extraction_schema(), settings)
    if hasattr(raw, "value"):
        model_digest = getattr(raw, "model_digest", model_digest)
        runtime = getattr(raw, "runtime", runtime)
        model = getattr(raw, "model", model)
        raw = raw.value
    try:
        parsed = ObservationBatch.model_validate(_repair_source_stated_clock(_normalise_nullable_literals(raw)))
    except ValidationError as exc:
        raise ExtractionError(f"model output failed observation schema: {exc}") from exc
    accepted: list[Observation] = []
    errors: list[str] = []
    for observation in parsed.observations:
        try:
            _validate_evidence(observation, batch.fragments)
            if observation.event_type in {EventType.actual_start, EventType.actual_finish}:
                if observation.quantity is not None or observation.reported_percent is not None:
                    raise ExtractionError("lifecycle assertion must not carry quantity or percent")
                for effect in observation.lifecycle_effects:
                    if effect.kind.value != observation.event_type.value:
                        raise ExtractionError("lifecycle endpoint kind does not match observation")
                    if effect.endpoint.basis == "report_context":
                        if not batch.report_date_trusted or effect.endpoint.local_date != batch.report_date:
                            raise ExtractionError("lifecycle endpoint requires trusted matching report date")
                    if observation.work_date and effect.endpoint.local_date != observation.work_date:
                        raise ExtractionError("lifecycle endpoint conflicts with work date")
            # Relative dates are accepted only when a trusted report context exists.
            if observation.date_basis == DateBasis.relative_resolved and not batch.report_date_trusted:
                raise ExtractionError("relative date requires trusted report date")
            if observation.event_type in {EventType.planned_work, EventType.no_work, EventType.blocker, EventType.material_delivery}:
                if observation.event_type != EventType.blocker and observation.quantity is not None:
                    observation = observation.model_copy(update={"quantity": None, "quantity_kind": QuantityKind.none, "unit": None})
            if _fact_key(observation) not in {_fact_key(existing) for existing in accepted}:
                accepted.append(observation)
        except ExtractionError as exc:
            errors.append(str(exc))
    metadata = ExtractionMetadata(PROMPT_VERSION, prompt_hash, settings_hash, model, model_digest, runtime, batch.batch_id)
    return ExtractionResult(tuple(accepted), metadata, tuple(errors))


def extract_fragments(fragments: Sequence[FragmentInput], model_call: ModelCall, **kwargs: Any) -> tuple[ExtractionResult, ...]:
    batch_options = {k: kwargs.pop(k) for k in ("report_date", "report_date_trusted", "max_chars") if k in kwargs}
    return tuple(extract_batch(batch, model_call, **kwargs) for batch in build_batches(fragments, **batch_options))


def deduplicate_results(results: Sequence[ExtractionResult]) -> tuple[Observation, ...]:
    """Collapse identical facts produced by overlapping fragment batches."""
    seen: set[tuple[Any, ...]] = set()
    output: list[Observation] = []
    for result in results:
        for observation in result.observations:
            key = _fact_key(observation)
            if key not in seen:
                seen.add(key)
                output.append(observation)
    return tuple(output)
