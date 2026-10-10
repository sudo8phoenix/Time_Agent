"""Honest duration calculations for supported lifecycle endpoints.

Working time is calculated only from a caller-supplied, reviewed calendar. This
module deliberately does not discover or infer calendars from schedule imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.schemas.events import Endpoint, EndpointPrecision


@dataclass(frozen=True)
class DurationResult:
    status: Literal["available", "unavailable"]
    basis: str
    reason: str | None = None
    elapsed_seconds: float | None = None
    elapsed_min_seconds: float | None = None
    elapsed_max_seconds: float | None = None
    date_span_days: int | None = None
    calendar_working_seconds: float | None = None
    calendar_working_min_seconds: float | None = None
    calendar_working_max_seconds: float | None = None
    calendar_version: str | None = None
    uncertainty: str | None = None


@dataclass(frozen=True)
class Shift:
    """A local-time working shift; breaks are excluded from its interval."""

    start: time
    finish: time
    breaks: tuple[tuple[time, time], ...] = ()


@dataclass(frozen=True)
class ReviewedCalendar:
    """Explicit reviewed calendar definition, versioned by its owner."""

    version: str
    timezone: str
    shifts_by_weekday: dict[int, tuple[Shift, ...]]
    holidays: frozenset[date] = frozenset()
    reviewed: bool = False


def _unavailable(basis: str, reason: str, **kwargs) -> DurationResult:
    return DurationResult(status="unavailable", basis=basis, reason=reason, **kwargs)


def _localize_unambiguous(local: datetime, zone: ZoneInfo) -> datetime | None:
    """Resolve an ordinary wall time; reject gaps and folds without a disambiguator."""
    candidates = []
    for fold in (0, 1):
        candidate = local.replace(tzinfo=zone, fold=fold)
        roundtrip = candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
        if roundtrip == local:
            candidates.append(candidate)
    if not candidates:
        return None
    if len(candidates) == 2 and candidates[0].utcoffset() != candidates[1].utcoffset():
        return None
    return candidates[0]


def _endpoint_bounds(endpoint: Endpoint) -> tuple[datetime, datetime] | None:
    """Return a UTC precision interval or None when wall time is unresolved."""
    if endpoint.precision == EndpointPrecision.date:
        return None
    zone_name = endpoint.timezone
    instant = endpoint.normalized_instant
    if instant is not None:
        if instant.tzinfo is None:
            return None
        lower = instant.astimezone(timezone.utc)
        if zone_name:
            try:
                local = lower.astimezone(ZoneInfo(zone_name)).replace(tzinfo=None)
            except ZoneInfoNotFoundError:
                return None
            if local != datetime.combine(endpoint.local_date, endpoint.local_time):
                return None
    elif zone_name:
        try:
            zone = ZoneInfo(zone_name)
        except ZoneInfoNotFoundError:
            return None
        localized = _localize_unambiguous(datetime.combine(endpoint.local_date, endpoint.local_time), zone)
        if localized is None:
            return None
        lower = localized.astimezone(timezone.utc)
    else:
        return None
    resolution = timedelta(minutes=1) if endpoint.precision == EndpointPrecision.minute else timedelta(seconds=1)
    return lower, lower + resolution


def _working_intersection(start: datetime, finish: datetime, calendar: ReviewedCalendar) -> float | None:
    zone = ZoneInfo(calendar.timezone)
    total = 0.0
    first = start.astimezone(zone).date()
    last = finish.astimezone(zone).date()
    day = first
    while day <= last:
        if day not in calendar.holidays:
            for shift in calendar.shifts_by_weekday.get(day.weekday(), ()):
                shift_start_local = _localize_unambiguous(datetime.combine(day, shift.start), zone)
                shift_finish_local = _localize_unambiguous(datetime.combine(day, shift.finish), zone)
                if shift_start_local is None or shift_finish_local is None:
                    return None
                shift_start = shift_start_local.astimezone(timezone.utc)
                shift_finish = shift_finish_local.astimezone(timezone.utc)
                # Intersect the shift with the requested interval, then remove breaks.
                left, right = max(start, shift_start), min(finish, shift_finish)
                if right <= left:
                    continue
                worked = (right - left).total_seconds()
                for break_start, break_finish in shift.breaks:
                    bstart_local = _localize_unambiguous(datetime.combine(day, break_start), zone)
                    bfinish_local = _localize_unambiguous(datetime.combine(day, break_finish), zone)
                    if bstart_local is None or bfinish_local is None:
                        return None
                    bstart = bstart_local.astimezone(timezone.utc)
                    bfinish = bfinish_local.astimezone(timezone.utc)
                    worked -= max(0.0, (min(right, bfinish) - max(left, bstart)).total_seconds())
                total += max(0.0, worked)
        day += timedelta(days=1)
    return total


def _calendar_shape_supported(calendar: ReviewedCalendar) -> bool:
    if any(day < 0 or day > 6 for day in calendar.shifts_by_weekday):
        return False
    for shifts in calendar.shifts_by_weekday.values():
        shift_intervals: list[tuple[int, int]] = []
        for shift in shifts:
            if shift.start.tzinfo or shift.finish.tzinfo or shift.finish <= shift.start:
                return False
            start_minute = shift.start.hour * 60 + shift.start.minute
            finish_minute = shift.finish.hour * 60 + shift.finish.minute
            if shift.start.second or shift.start.microsecond or shift.finish.second or shift.finish.microsecond:
                return False
            breaks: list[tuple[int, int]] = []
            for break_start, break_finish in shift.breaks:
                if break_start.tzinfo or break_finish.tzinfo or break_finish <= break_start:
                    return False
                bstart = break_start.hour * 60 + break_start.minute
                bfinish = break_finish.hour * 60 + break_finish.minute
                if break_start.second or break_start.microsecond or break_finish.second or break_finish.microsecond:
                    return False
                if bstart < start_minute or bfinish > finish_minute:
                    return False
                breaks.append((bstart, bfinish))
            breaks.sort()
            if any(current[0] < prior[1] for prior, current in zip(breaks, breaks[1:])):
                return False
            shift_intervals.append((start_minute, finish_minute))
        shift_intervals.sort()
        if any(current[0] < prior[1] for prior, current in zip(shift_intervals, shift_intervals[1:])):
            return False
    return True


def calculate_duration(
    start: Endpoint | None,
    finish: Endpoint | None,
    *,
    calendar: ReviewedCalendar | None = None,
) -> DurationResult:
    """Calculate elapsed duration/date span and optionally reviewed working time.

    Date-only or mixed date/timed endpoints never produce precise elapsed hours.
    Timed precision is represented as a lower/upper range; ``elapsed_seconds``
    is its midpoint. No labour-hour or productivity estimate is made here.
    """
    if start is None or finish is None:
        return _unavailable("elapsed", "missing_start_or_finish")
    date_span = (finish.local_date - start.local_date).days
    if start.precision == EndpointPrecision.date or finish.precision == EndpointPrecision.date:
        if finish.local_date < start.local_date:
            return _unavailable("elapsed", "finish_before_start_requires_review")
        return DurationResult(
            status="available", basis="date_span", date_span_days=date_span,
            uncertainty="date_precision_does_not_establish_elapsed_hours",
        )
    start_bounds = _endpoint_bounds(start)
    finish_bounds = _endpoint_bounds(finish)
    if start_bounds is None or finish_bounds is None:
        return _unavailable("elapsed", "timed_endpoint_timezone_or_instant_unavailable", date_span_days=date_span)
    start_lo, start_hi = start_bounds
    finish_lo, finish_hi = finish_bounds
    minimum = (finish_lo - start_hi).total_seconds()
    maximum = (finish_hi - start_lo).total_seconds()
    if maximum < 0:
        return _unavailable("elapsed", "finish_before_start_requires_review", date_span_days=date_span)
    minimum = max(0.0, minimum)
    midpoint = (minimum + maximum) / 2
    if calendar is None:
        return DurationResult(
            status="available", basis="elapsed_clock_time", elapsed_seconds=midpoint,
            elapsed_min_seconds=minimum, elapsed_max_seconds=maximum, date_span_days=date_span,
            uncertainty="endpoint_precision_range; timezone-normalized elapsed time",
        )
    if not calendar.reviewed:
        return _unavailable("calendar_working", "calendar_unreviewed", date_span_days=date_span)
    if not calendar.version:
        return _unavailable("calendar_working", "calendar_version_missing", date_span_days=date_span)
    if start.timezone != calendar.timezone or finish.timezone != calendar.timezone:
        return _unavailable("calendar_working", "endpoint_calendar_timezone_mismatch", date_span_days=date_span)
    try:
        ZoneInfo(calendar.timezone)
    except ZoneInfoNotFoundError:
        return _unavailable("calendar_working", "calendar_timezone_unsupported", date_span_days=date_span)
    if not _calendar_shape_supported(calendar):
        return _unavailable("calendar_working", "calendar_shift_definition_unsupported", date_span_days=date_span)
    working_min = _working_intersection(start_hi, finish_lo, calendar)
    working_max = _working_intersection(start_lo, finish_hi, calendar)
    if working_min is None or working_max is None:
        return _unavailable("calendar_working", "calendar_wall_time_ambiguous_or_nonexistent", date_span_days=date_span)
    working_min = min(working_min, working_max)
    working = (working_min + working_max) / 2
    return DurationResult(
        status="available", basis="elapsed_clock_time_and_reviewed_calendar",
        elapsed_seconds=midpoint, elapsed_min_seconds=minimum, elapsed_max_seconds=maximum,
        date_span_days=date_span, calendar_working_seconds=working,
        calendar_working_min_seconds=working_min,
        calendar_working_max_seconds=working_max,
        calendar_version=calendar.version,
        uncertainty="endpoint_precision_range; calendar working time is not crew labour",
    )


def labour_productivity(*, quantity: float | None = None, crew_hours: float | None = None) -> DurationResult:
    """Return unavailable until measured compatible quantity and labour exist."""
    return _unavailable("quantity_per_crew_hour", "measured_compatible_labour_data_unavailable")
