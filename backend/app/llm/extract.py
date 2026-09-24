"""Atomic, evidence-grounded observation extraction.

This module has no database or network side effects.  The model callable is injected
so worker jobs and tests can use the local adapter or deterministic fixtures.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
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
    for evidence in observation.evidence:
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
            o.quantity, o.quantity_kind, o.unit, o.blocker, o.summary)


ModelCall = Callable[..., Any]


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
        parsed = ObservationBatch.model_validate(raw)
    except ValidationError as exc:
        raise ExtractionError(f"model output failed observation schema: {exc}") from exc
    accepted: list[Observation] = []
    errors: list[str] = []
    for observation in parsed.observations:
        try:
            _validate_evidence(observation, batch.fragments)
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
