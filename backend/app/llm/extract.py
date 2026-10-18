"""Atomic, evidence-grounded observation extraction.

This module has no database or network side effects.  The model callable is injected
so worker jobs and tests can use the local adapter or deterministic fixtures.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Mapping, Sequence

from pydantic import ValidationError

from ..schemas.observation import Observation, ObservationBatch
from ..schemas.common import EventType, DateBasis, QuantityKind, WorkType
from ..prompts.extraction_v1 import LEGACY_PROMPT_VERSION, EVIDENCE_COVERAGE_VERSIONS, V18_PROMPT_VERSION, V19_PROMPT_VERSION, V20_PROMPT_VERSION, SOURCE_NORMALIZATION_VERSIONS, CLAUSE_NORMALIZATION_VERSIONS, get_extraction_prompt

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


def _restore_non_actual_date(observation: Observation, batch: BatchInput, *, correct_context=False) -> Observation:
    """Restore one unambiguous relative day from validated quoted source only."""
    if (observation.event_type not in {EventType.planned_work, EventType.material_delivery}
            or not ((observation.work_date is None and observation.date_basis == DateBasis.unknown)
                or (correct_context and (observation.date_basis == DateBasis.relative_resolved or
                    (observation.date_basis == DateBasis.report_context and observation.work_date == batch.report_date))))
            or not batch.report_date_trusted or batch.report_date is None
            or _conflicting_today_context(observation, batch)):
        return observation
    offsets = {"yesterday": -1, "today": 0, "tomorrow": 1}
    chosen = []
    for evidence in observation.evidence:
        quote = evidence.quote
        words = re.findall(r"\b(yesterday|today|tomorrow)\b", quote, re.I)
        if not words:
            continue
        # Conflicting dates, alternatives, negation and loose historical phrasing
        # need clarification rather than deterministic date inference.
        if (re.search(r"\b(?:not|never|no|or|maybe|possibly|unclear|typo|before|after|until|since|by)\b", quote, re.I)
                or re.search(r"\b\d{4}-\d{2}-\d{2}\b|\d[/-]\d|\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b", quote, re.I)):
            return observation
        chosen.extend((offsets[word.lower()], evidence) for word in words)
    if not chosen or len({offset for offset, _ in chosen}) != 1:
        return observation
    try:
        resolved = batch.report_date + timedelta(days=chosen[0][0])
    except OverflowError:
        return observation
    evidence = list(observation.evidence)
    index = evidence.index(chosen[0][1])
    if "work_date" not in evidence[index].fields and len(evidence[index].fields) < 30:
        evidence[index] = evidence[index].model_copy(update={"fields": [*evidence[index].fields, "work_date"]})
    updates = {"work_date": resolved, "date_basis": DateBasis.relative_resolved, "evidence": evidence}
    if observation.work_date is not None and observation.work_date != resolved:
        updates["warnings"] = [*observation.warnings[:29],
            "Report-context date corrected to the exact source-stated relative day."]
    return observation.model_copy(update=updates)


def _unwrap_exact_source_quotes(observation: Observation, batch: BatchInput) -> Observation:
    """Remove only exact application-rendered wrappers, never rewrite source text."""
    by_id = {fragment.fragment_id: fragment for fragment in batch.fragments}
    changed = False
    def repair(evidence):
        nonlocal changed
        fragment = by_id.get(evidence.fragment_id)
        if fragment is None or len(fragment.text) > 2000:
            return evidence
        wrapper = f"[{fragment.fragment_id} | {fragment.locator}]\n{fragment.text}"
        context = (f"Trusted report date: {batch.report_date.isoformat()}\n"
                   if batch.report_date_trusted and batch.report_date else "") + wrapper
        if evidence.quote in {wrapper, context} and evidence.quote != fragment.text:
            changed = True
            return evidence.model_copy(update={"quote": fragment.text})
        return evidence
    evidence = [repair(e) for e in observation.evidence]
    effects = [effect.model_copy(update={"evidence": [repair(e) for e in effect.evidence]})
               for effect in observation.lifecycle_effects]
    if not changed:
        return observation
    return observation.model_copy(update={"evidence": evidence, "lifecycle_effects": effects,
        "warnings": [*observation.warnings[:29], "Exact input wrapper removed from source evidence quote."]})


def _remove_repeated_source_heading(observation: Observation, batch: BatchInput) -> Observation:
    """Remove a copied leading heading only before a unique exact source span.

    This never repairs words, punctuation or fragment identity. Restrict the
    heading to the source's first line and refuse another non-clock colon in
    intervening text, where a new heading could have changed ownership.
    """
    sources = {f.fragment_id: f.text for f in batch.fragments}
    changed = False

    def repair(evidence):
        nonlocal changed
        source = sources.get(evidence.fragment_id)
        if not source or evidence.quote in source:
            return evidence
        heading = re.match(r"[^:\n]{1,120}:\s+", source)
        if heading is None or not evidence.quote.startswith(heading.group()):
            return evidence
        body = evidence.quote[len(heading.group()):]
        if not body.strip() or source.count(body) != 1:
            return evidence
        offset = source.index(body)
        if offset < heading.end() or re.search(r"(?<!\d):|:(?!\d)", source[heading.end():offset]):
            return evidence
        changed = True
        return evidence.model_copy(update={"quote": body})

    evidence = [repair(e) for e in observation.evidence]
    effects = [effect.model_copy(update={"evidence": [repair(e) for e in effect.evidence]})
               for effect in observation.lifecycle_effects]
    if not changed:
        return observation
    return observation.model_copy(update={"evidence": evidence, "lifecycle_effects": effects,
        "warnings": [*observation.warnings[:29], "Repeated source heading removed before unique exact evidence span."]})


def _normalise_explicit_blocker_clause(observation: Observation, batch: BatchInput) -> Observation:
    """Ground a blocker in one uniquely identified source work clause.

    This is deliberately narrow: no event creation, schedule matching or nearest
    clause guesses. Multiple matching scopes remain unresolved for review.
    """
    if observation.event_type != EventType.blocker:
        return observation
    patterns = {
        WorkType.rebar_installation: r"\b(?:reinforcement\s+fixing|fixing\s+(?:reinforcement|rebar)|rebar\s+(?:fixing|installation))\b",
        WorkType.welding: r"\bwelding\b",
        WorkType.other: r"\b(?:testing|inspection|painting)\b",
    }
    matched = [(kind, pattern) for kind, pattern in patterns.items()
               if re.search(pattern, observation.summary, re.I)]
    if len(matched) != 1:
        return observation
    kind, pattern = matched[0]
    fragments = {f.fragment_id: f for f in batch.fragments}
    ids = {e.fragment_id for e in observation.evidence}
    if len(ids) != 1 or not ids <= fragments.keys():
        return observation
    source = fragments[next(iter(ids))].text
    clauses = source.split(";")
    own = [clause for clause in clauses if re.search(pattern, clause, re.I)]
    if len(own) != 1:
        return observation
    updates = {}
    if observation.work_type != kind:
        updates["work_type"] = kind
    area = observation.area
    # Only an explicit location heading is shared. An asset ID or a cause label
    # before ':' is not silently promoted to a location.
    heading_match = re.match(r"\s*((?:zone|area|bay|sector|section|gallery|compound|yard|floor|level|duct|cut)\b[^:;\n]{0,90}):", source, re.I)
    heading = heading_match.group(1).strip() if heading_match else None
    if area and area.casefold() not in own[0].casefold() and (not heading or area.casefold() != heading.casefold()):
        updates["area"] = None
    elif area is None and heading:
        updates["area"] = heading
    if not updates:
        return observation
    updates["warnings"] = [*observation.warnings[:29],
        "Blocker work/location normalized to its uniquely supported source clause; reviewer verification required."]
    return observation.model_copy(update=updates)


def _warn_missing_constraint(observations: list[Observation], batch: BatchInput, *, extended: bool = False) -> list[Observation]:
    """Flag a clearly stated present/past stoppage with no blocker observation.

    This is a conservative presence check, not semantic adjudication. It never
    constructs a blocker, activity match, date or progress effect from a regex.
    """
    missing = set()
    for fragment in batch.fragments:
        clauses = re.split(r"[;\n.!?]", fragment.text)
        explicit = False
        for clause in clauses:
            match = re.search(r"\b(?:stopped|halted|suspended|blocked|held)\s+(?:due to|because(?: of)?|by|for lack of)\b", clause, re.I)
            if match and not re.search(r"\b(?:not|never|no|will|would|could|may|if|might)\b", clause[:match.start()], re.I):
                explicit = True
        if extended:
            # A source-stated work stoppage need not put its cause after the verb.
            for clause in clauses:
                match = re.search(r"\b(?:work|testing|welding|fixing|erection|installation|painting|pouring)\s+(?:was |is |has been |had been )?(?:stopped|halted|suspended|blocked|held)\b", clause, re.I)
                if match and not re.search(r"\b(?:not|never|no|will|would|could|may|if|might|whether|example|say|said|instruction)\b", clause, re.I):
                    explicit = True
            explicit = explicit or any(o.event_type != EventType.blocker and o.blocker and any(
                e.fragment_id == fragment.fragment_id for e in o.evidence) for o in observations)
        covered = any(o.event_type == EventType.blocker and any(
            e.fragment_id == fragment.fragment_id for e in o.evidence) for o in observations)
        if explicit and not covered:
            missing.add(fragment.fragment_id)
    warning = "Source-stated work constraint has no separate blocker observation; reviewer clarification required."
    result = []
    for observation in observations:
        if any(e.fragment_id in missing for e in observation.evidence) and warning not in observation.warnings:
            observation = observation.model_copy(update={"warnings": [*observation.warnings[:29], warning]})
        result.append(observation)
    return result


def _repair_decorated_fragment_ids(observation: Observation, batch: BatchInput) -> Observation:
    """Unwrap only an exact supplied header with an exact, unique body quote.

    Never guess a source from its text or modify an evidence quote. A warning
    preserves reviewer visibility of this model-format repair.
    """
    decorated = {}
    for fragment in batch.fragments:
        for key in (f"{fragment.fragment_id} | {fragment.locator}",
                    f"[{fragment.fragment_id} | {fragment.locator}]"):
            decorated[key] = fragment
    canonical_ids = {fragment.fragment_id for fragment in batch.fragments}
    changed = False
    def repair(evidence):
        nonlocal changed
        if evidence.fragment_id in canonical_ids:
            return evidence
        fragment = decorated.get(evidence.fragment_id)
        if fragment and fragment.text.count(evidence.quote) == 1:
            changed = True
            return evidence.model_copy(update={"fragment_id": fragment.fragment_id})
        return evidence
    evidence = [repair(e) for e in observation.evidence]
    effects = [effect.model_copy(update={"evidence": [repair(e) for e in effect.evidence]})
               for effect in observation.lifecycle_effects]
    if not changed:
        return observation
    return observation.model_copy(update={"evidence": evidence, "lifecycle_effects": effects,
        "warnings": [*observation.warnings[:29],
            "Evidence fragment identifier restored from an exact supplied header; reviewer verification required."]})


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
            o.quantity, o.quantity_kind, o.unit, o.reported_percent, o.blocker, o.summary,
            tuple(effect.model_dump_json() for effect in o.lifecycle_effects))


ModelCall = Callable[..., Any]


_NULL_LITERALS = frozenset({"", "n/a", "na", "none", "null", "unknown"})
_NULLABLE_OBSERVATION_FIELDS = frozenset({
    "area", "explicit_activity_id", "work_date", "quantity", "unit", "raw_unit",
    "reported_percent", "actual_start", "actual_finish", "blocker",
})


def _normalise_nullable_literals(raw: Any, *, fill_missing=False) -> Any:
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
        missing = []
        for field in _NULLABLE_OBSERVATION_FIELDS:
            if fill_missing and field not in observation:
                observation[field] = None
                missing.append(field)
            value = observation.get(field)
            if isinstance(value, str) and value.strip().casefold() in _NULL_LITERALS:
                observation[field] = None
        if missing and isinstance(observation.get("warnings"), list):
            observation["warnings"] = [*observation["warnings"][:29],
                "Omitted optional scalar fields retained as unknown: " + ", ".join(sorted(missing))]
        observations.append(observation)
    normalised["observations"] = observations
    return normalised


def _repair_unitless_percent_quantity(raw: Any, fragments: Sequence[FragmentInput]) -> Any:
    """Keep source-stated percentages without a model-invented measured quantity."""
    if not isinstance(raw, Mapping) or not isinstance(raw.get("observations"), list):
        return raw
    sources = {fragment.fragment_id: fragment.text for fragment in fragments}
    repaired = dict(raw)
    items = []
    for original in raw["observations"]:
        item = dict(original) if isinstance(original, Mapping) else original
        if (isinstance(item, dict) and item.get("reported_percent") is not None
                and item.get("quantity") is not None and item.get("unit") is None
                and item.get("raw_unit") is None and item.get("event_type") == "actual_progress"):
            try:
                percent = Decimal(str(item["reported_percent"]))
                quantity = Decimal(str(item["quantity"]))
                supported = any(
                    isinstance(e, Mapping) and isinstance(e.get("quote"), str)
                    and e["quote"] in sources.get(e.get("fragment_id"), "")
                    and any(Decimal(number) == percent for number in
                            re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:%|percent\b)", e["quote"], re.I))
                    for e in item.get("evidence", [])
                )
                if supported and percent.is_finite() and 0 <= percent <= 100 and quantity in {percent, percent / 100}:
                    item["quantity"] = None
                    item["quantity_kind"] = "none"
                    item["warnings"] = [*item.get("warnings", [])[:29],
                                        "Model's unitless quantity removed; source reports a percentage."]
            except (InvalidOperation, ValueError, TypeError):
                pass  # Unsupported or malformed output still undergoes strict validation.
        items.append(item)
    repaired["observations"] = items
    return repaired


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


def _conflicting_today_context(observation: Observation, batch: BatchInput) -> bool:
    """Check explicit present-day anchors, not arbitrary dates of historical work."""
    fragment_ids = {e.fragment_id for e in observation.evidence}
    anchors = {batch.report_date} if batch.report_date_trusted and batch.report_date else set()
    pattern = r"\b(?:today(?:\s+is)?|(?:source|report)\s+(?:header|date))\s*[:=-]?\s*(\d{4}-\d{2}-\d{2})\b"
    for fragment in batch.fragments:
        if fragment.fragment_id not in fragment_ids:
            continue
        for raw in re.findall(pattern, fragment.text, flags=re.I):
            try:
                anchors.add(date.fromisoformat(raw))
            except ValueError:
                continue
    return len(anchors) > 1


def extract_batch(batch: BatchInput, model_call: ModelCall, *, model: str = "unknown",
                 model_digest: str | None = None, runtime: str | None = None,
                 settings: Mapping[str, Any] | None = None,
                 prompt_version: str | None = None) -> ExtractionResult:
    """Call an injected model, validate output/evidence, resolve supported dates, dedupe."""
    try:
        prompt_version, system_prompt = get_extraction_prompt(prompt_version)
    except ValueError as exc:
        raise ExtractionError(str(exc)) from None
    settings = dict(settings or {"temperature": 0.0})
    user = _context(batch)
    prompt_hash = _hash({"system": system_prompt, "user": user})
    settings_hash = _hash(settings)
    try:
        raw = model_call(system=system_prompt, user=user, schema=extraction_schema(), settings=settings)
    except TypeError:
        raw = model_call(system_prompt, user, extraction_schema(), settings)
    if hasattr(raw, "value"):
        model_digest = getattr(raw, "model_digest", model_digest)
        runtime = getattr(raw, "runtime", runtime)
        model = getattr(raw, "model", model)
        raw = raw.value
    try:
        normalised = _normalise_nullable_literals(raw, fill_missing=prompt_version in {V18_PROMPT_VERSION, V19_PROMPT_VERSION, V20_PROMPT_VERSION})
        repaired = _repair_unitless_percent_quantity(normalised, batch.fragments)
        parsed = ObservationBatch.model_validate(_repair_source_stated_clock(repaired))
    except ValidationError as exc:
        raise ExtractionError(f"model output failed observation schema: {exc}") from exc
    accepted: list[Observation] = []
    errors: list[str] = []
    for observation in parsed.observations:
        try:
            if prompt_version in SOURCE_NORMALIZATION_VERSIONS:
                observation = _unwrap_exact_source_quotes(observation, batch)
            if prompt_version in EVIDENCE_COVERAGE_VERSIONS:
                observation = _repair_decorated_fragment_ids(observation, batch)
            if prompt_version == V20_PROMPT_VERSION:
                observation = _remove_repeated_source_heading(observation, batch)
            _validate_evidence(observation, batch.fragments)
            if prompt_version in CLAUSE_NORMALIZATION_VERSIONS:
                observation = _normalise_explicit_blocker_clause(observation, batch)
            date_conflict = observation.date_basis == DateBasis.conflicting or _conflicting_today_context(observation, batch)
            if date_conflict:
                observation = observation.model_copy(update={
                    "work_date": None, "date_basis": DateBasis.unknown,
                    "actual_start": None, "actual_finish": None, "lifecycle_effects": [],
                    "warnings": [*observation.warnings[:29],
                        "Conflicting report/current-day dates require reviewer clarification."],
                })
            if prompt_version != LEGACY_PROMPT_VERSION and not date_conflict:
                observation = _restore_non_actual_date(observation, batch,
                    correct_context=prompt_version in SOURCE_NORMALIZATION_VERSIONS)
            unsupported_context = (
                observation.date_basis in {DateBasis.report_context, DateBasis.relative_resolved}
                and (not batch.report_date_trusted or (
                    observation.date_basis == DateBasis.report_context and
                    observation.work_date != batch.report_date))
            ) or any(
                effect.endpoint.basis == "report_context"
                and (not batch.report_date_trusted or effect.endpoint.local_date != batch.report_date)
                for effect in observation.lifecycle_effects
            )
            if unsupported_context:
                # Preserve the evidence-backed assertion for clarification, but
                # never turn an untrusted model date into a ledger effect.
                observation = observation.model_copy(update={
                    "work_date": None, "date_basis": DateBasis.unknown,
                    "actual_start": None, "actual_finish": None,
                    "lifecycle_effects": [],
                    "warnings": [*observation.warnings[:29],
                                 "Work date needs reviewer clarification; unsupported report-context dates were removed."],
                })
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
    if prompt_version != LEGACY_PROMPT_VERSION:
        accepted = _warn_missing_constraint(accepted, batch, extended=prompt_version in EVIDENCE_COVERAGE_VERSIONS)
        if prompt_version in EVIDENCE_COVERAGE_VERSIONS and errors:
            # A rejected sibling may be a separate constraint or activity. Prevent
            # partial success from silently approving only the retained work.
            accepted = [o.model_copy(update={"warnings": [*o.warnings[:29],
                "Some source observations failed evidence validation; reviewer completeness check required."]})
                for o in accepted]
    metadata = ExtractionMetadata(prompt_version, prompt_hash, settings_hash, model, model_digest, runtime, batch.batch_id)
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
