"""Order-independent reduction of accepted, immutable lifecycle events."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Sequence
from app.schemas.events import Endpoint, LifecycleKind, LifecycleScope


@dataclass(frozen=True)
class LifecycleEvent:
    event_id: str
    kind: LifecycleKind
    endpoint: Endpoint
    scope: LifecycleScope = LifecycleScope.whole_activity
    source_key: str | None = None
    active: bool = True
    supersedes_event_id: str | None = None
    subactivity_key: str | None = None


@dataclass
class LifecycleResult:
    actual_start: Endpoint | None
    actual_finish: Endpoint | None
    status: str
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    applied_event_ids: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.conflicts


def _bounds(endpoint: Endpoint):
    """Inclusive lower and exclusive upper bound at the reported precision."""
    from datetime import datetime, timedelta
    from datetime import time as clock_time
    start = datetime.combine(endpoint.local_date, endpoint.local_time or clock_time.min)
    if endpoint.local_time is None:
        return start, start + timedelta(days=1)
    return start, start + timedelta(seconds=1 if endpoint.precision.value == "second" else 60)


def recompute_lifecycle(
    baseline_start: Endpoint | None,
    baseline_finish: Endpoint | None,
    events: Sequence[LifecycleEvent],
) -> LifecycleResult:
    by_id = {event.event_id: event for event in events}
    conflicts: list[str] = []
    warnings: list[str] = []
    ambiguous_ids: set[str] = set()
    if len(by_id) != len(events):
        for event_id in sorted({e.event_id for e in events}):
            copies = [e for e in events if e.event_id == event_id]
            if len(copies) > 1:
                if any(copy != copies[0] for copy in copies[1:]):
                    conflicts.append(f"event ID {event_id} has disagreeing content")
                    ambiguous_ids.add(event_id)
                else:
                    warnings.append(f"exact retry {event_id} ignored")
    superseded = {e.supersedes_event_id for e in events if e.active and e.supersedes_event_id}
    for prior in sorted(superseded):
        if prior not in by_id:
            conflicts.append(f"superseded event {prior} is missing")
    superseded_sources = {by_id[event_id].source_key for event_id in superseded
                          if event_id in by_id and by_id[event_id].source_key}
    active = sorted((e for e in by_id.values() if e.active and e.event_id not in superseded and e.event_id not in ambiguous_ids),
                    key=lambda e: e.event_id)
    whole = {LifecycleKind.actual_start: [], LifecycleKind.actual_finish: []}
    seen_sources: dict[str, LifecycleEvent] = {}
    for event in active:
        if event.scope == LifecycleScope.subactivity:
            warnings.append(f"subactivity event {event.event_id} does not set whole-activity state")
            continue
        if event.source_key:
            if event.source_key in superseded_sources and not event.supersedes_event_id:
                warnings.append(f"superseded source retry {event.event_id} ignored")
                continue
            prior = seen_sources.get(event.source_key)
            if prior:
                if prior.kind != event.kind or prior.endpoint != event.endpoint:
                    conflicts.append(f"source {event.source_key} has disagreeing events")
                else:
                    warnings.append(f"exact retry {event.event_id} ignored")
                continue
            seen_sources[event.source_key] = event
        whole[event.kind].append(event)
    chosen: dict[LifecycleKind, Endpoint | None] = {}
    applied: list[str] = []
    for kind, baseline in ((LifecycleKind.actual_start, baseline_start), (LifecycleKind.actual_finish, baseline_finish)):
        candidates = whole[kind]
        distinct = {e.endpoint.model_dump_json() for e in candidates}
        if len(distinct) > 1:
            conflicts.append(f"disagreeing {kind.value} endpoints require review")
            chosen[kind] = baseline
        elif candidates:
            if len(candidates) > 1:
                warnings.append(f"suspected duplicate {kind.value} endpoints")
            endpoint = candidates[0].endpoint
            if baseline and endpoint != baseline and not any(e.supersedes_event_id for e in candidates):
                conflicts.append(f"{kind.value} disagrees with imported baseline")
            chosen[kind] = endpoint
            applied.extend(e.event_id for e in candidates)
        else:
            chosen[kind] = baseline
    start, finish = chosen[LifecycleKind.actual_start], chosen[LifecycleKind.actual_finish]
    if start and finish:
        if start.normalized_instant and finish.normalized_instant:
            if finish.normalized_instant < start.normalized_instant:
                conflicts.append("finish is known to precede start")
        elif start.timezone and finish.timezone and start.timezone != finish.timezone:
            warnings.append("different endpoint timezones leave chronology unresolved")
        else:
            start_min, _ = _bounds(start)
            _, finish_max = _bounds(finish)
            if finish_max <= start_min:
                conflicts.append("finish is known to precede start")
            elif start.local_date == finish.local_date and (start.local_time is None or finish.local_time is None):
                warnings.append("same-day date-only endpoint leaves elapsed hours unknown")
    status = "completed" if finish else "in_progress" if start else "not_started"
    return LifecycleResult(start, finish, status, sorted(set(conflicts)), sorted(set(warnings)), sorted(applied))
