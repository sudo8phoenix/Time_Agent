"""Deterministic, database-free progress recomputation.

The function in this module deliberately has no notion of wall-clock time or
approval. Callers pass only the immutable baseline and the active approved
events they want considered.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


_CONVERSIONS: dict[tuple[str, str], Decimal] = {
    ("cm", "m"): Decimal("0.01"), ("m", "cm"): Decimal("100"),
    ("mm", "m"): Decimal("0.001"), ("m", "mm"): Decimal("1000"),
    ("t", "kg"): Decimal("1000"), ("kg", "t"): Decimal("0.001"),
}
_NON_PROGRESS = {"planned_work", "no_work", "blocker", "material_delivery", "delivery"}


@dataclass(frozen=True)
class ActivityBaseline:
    planned_quantity: Decimal | int | str | None
    unit: str | None
    baseline_quantity: Decimal | int | str | None
    baseline_date: date | None = None
    measurement_basis: str = "quantity_ratio"


@dataclass(frozen=True)
class ProgressEvent:
    event_id: str
    effective_date: date | None
    quantity: Decimal | int | str | None = None
    unit: str | None = None
    quantity_semantics: str = "unknown"  # delta, cumulative, unknown
    event_type: str = "work"
    source_id: str | None = None
    active: bool = True
    supersedes_event_id: str | None = None
    correction_of: str | None = None


@dataclass
class ProgressResult:
    completed_quantity: Decimal | None
    physical_percent: Decimal | None
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    applied_event_ids: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.conflicts


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def quantity_ratio(completed: Any, planned: Any, *, completed_unit: str | None = None,
                   planned_unit: str | None = None) -> Decimal:
    """Return a percentage using Decimal and only the documented MVP units."""
    c, p = _decimal(completed), _decimal(planned)
    if c is None or p is None or p <= 0:
        raise ValueError("planned quantity must be greater than zero")
    if completed_unit and planned_unit and completed_unit != planned_unit:
        factor = _CONVERSIONS.get((completed_unit.lower(), planned_unit.lower()))
        if factor is None:
            raise ValueError(f"unsupported unit conversion: {completed_unit} -> {planned_unit}")
        c *= factor
    elif (completed_unit or planned_unit) and completed_unit != planned_unit:
        raise ValueError("both units are required when units differ")
    return (Decimal("100") * c / p)


def recompute_progress(baseline: ActivityBaseline | Mapping[str, Any],
                       events: Sequence[ProgressEvent | Mapping[str, Any]]) -> ProgressResult:
    """Recompute one activity from baseline and active immutable events.

    Dates are mandatory for numeric events. Lifecycle dates are intentionally
    untouched; this function reports only physical quantity and validation.
    """
    basis = str(_value(baseline, "measurement_basis", "quantity_ratio"))
    conflicts: list[str] = []
    warnings: list[str] = []
    if basis != "quantity_ratio":
        return ProgressResult(None, None, [f"measurement basis {basis} does not calculate quantity ratio"])
    planned = _decimal(_value(baseline, "planned_quantity"))
    base = _decimal(_value(baseline, "baseline_quantity", 0))
    unit = _value(baseline, "unit")
    bdate = _value(baseline, "baseline_date")
    if planned is None or planned <= 0:
        conflicts.append("planned quantity must be greater than zero")
    if base is None:
        conflicts.append("baseline quantity is not numeric")
        base = Decimal("0")
    if base < 0 or (planned is not None and base > planned):
        conflicts.append("baseline quantity is outside planned bounds")

    raw = list(events)
    superseded = {
        superseded_id
        for e in raw
        if _value(e, "active", True)
        for superseded_id in (_value(e, "supersedes_event_id"), _value(e, "correction_of"))
        if superseded_id
    }
    # A correction can supersede an event before its duplicate source is
    # encountered in input order. Reserve the superseded source first so that
    # its duplicate cannot become the effective event.
    seen_sources: set[str] = {
        str(_value(e, "source_id"))
        for e in raw
        if str(_value(e, "event_id", "")) in superseded and _value(e, "source_id")
    }
    active: list[Any] = []
    for e in raw:
        eid = str(_value(e, "event_id", ""))
        if not _value(e, "active", True) or eid in superseded:
            continue
        source = _value(e, "source_id")
        if source and source in seen_sources:
            warnings.append(f"duplicate source {source} ignored")
            continue
        if source:
            seen_sources.add(source)
        active.append(e)
    active.sort(key=lambda e: (_value(e, "effective_date") or date.min, str(_value(e, "event_id", ""))))

    cumulative_dates: dict[date, list[Any]] = {}
    for e in active:
        sem = str(_value(e, "quantity_semantics", "unknown"))
        typ = str(_value(e, "event_type", "work")).lower()
        edate = _value(e, "effective_date")
        if typ in _NON_PROGRESS or typ in {"milestone", "inspection"}:
            if typ in _NON_PROGRESS:
                warnings.append(f"{typ} does not add installed quantity")
            continue
        if basis == "quantity_ratio" and sem in {"delta", "cumulative"} and edate is None:
            conflicts.append(f"event {_value(e, 'event_id')} has no effective date")
            continue
        if sem == "cumulative" and edate is not None:
            cumulative_dates.setdefault(edate, []).append(e)
        elif sem not in {"delta", "cumulative"}:
            conflicts.append(f"event {_value(e, 'event_id')} has unknown quantity semantics")

    for d, same in cumulative_dates.items():
        values = {_decimal(_value(e, "quantity")) for e in same}
        if len(values) > 1 and not any(_value(e, "correction_of") or _value(e, "supersedes_event_id") for e in same):
            conflicts.append(f"conflicting cumulative totals on {d.isoformat()} require reconciliation")

    current = base
    anchor_date = bdate
    applied: list[str] = []
    # Chronological application makes late records deterministic and allows a
    # later cumulative measurement to become the new anchor.
    for e in active:
        sem = str(_value(e, "quantity_semantics", "unknown"))
        typ = str(_value(e, "event_type", "work")).lower()
        if typ in _NON_PROGRESS or sem not in {"delta", "cumulative"}:
            continue
        d = _value(e, "effective_date")
        if d is None:
            continue
        if bdate is not None and d < bdate:
            warnings.append(f"event {_value(e, 'event_id')} predates baseline and is historical only")
            continue
        q = _decimal(_value(e, "quantity"))
        if q is None:
            conflicts.append(f"event {_value(e, 'event_id')} quantity is not numeric")
            continue
        eu = _value(e, "unit")
        try:
            if eu != unit:
                q = q * _CONVERSIONS[(str(eu).lower(), str(unit).lower())]
        except KeyError:
            conflicts.append(f"unsupported unit for event {_value(e, 'event_id')}: {eu} -> {unit}")
            continue
        if sem == "cumulative":
            if d in cumulative_dates and len({_decimal(_value(x, 'quantity')) for x in cumulative_dates[d]}) > 1:
                continue
            if q < current and not (_value(e, "correction_of") or _value(e, "supersedes_event_id")):
                conflicts.append(f"cumulative event {_value(e, 'event_id')} is lower than supported total")
            current, anchor_date = q, d
        elif anchor_date is None or d > anchor_date:
            current += q
        applied.append(str(_value(e, "event_id")))
    if current < 0 or (planned is not None and current > planned):
        conflicts.append("completed quantity is outside planned bounds (overrun is not clamped)")
    percent = None
    if not conflicts and planned is not None:
        try:
            percent = quantity_ratio(current, planned)
        except ValueError as exc:
            conflicts.append(str(exc))
    return ProgressResult(current, percent, conflicts, warnings, applied)
