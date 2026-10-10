from datetime import date, datetime, time, timezone
import pytest

from app.progress.duration import (
    ReviewedCalendar,
    Shift,
    calculate_duration,
    labour_productivity,
)
from app.schemas.events import Endpoint, EndpointPrecision


def endpoint(day, clock, precision=EndpointPrecision.minute, timezone="Asia/Kolkata"):
    return Endpoint(
        local_date=date.fromisoformat(day), local_time=clock, precision=precision,
        timezone=timezone, basis="explicit", raw_expression=f"{day} {clock}",
    )


def test_timed_endpoints_return_precision_bounded_elapsed_time():
    result = calculate_duration(endpoint("2026-01-01", time(9, 0)), endpoint("2026-01-01", time(10, 0)))
    assert result.status == "available"
    assert result.basis == "elapsed_clock_time"
    assert result.elapsed_seconds == 3600
    assert result.elapsed_min_seconds == 3540
    assert result.elapsed_max_seconds == 3660


def test_date_only_endpoint_reports_span_without_hours():
    start = Endpoint(local_date=date(2026, 1, 1), precision=EndpointPrecision.date,
                     basis="explicit", raw_expression="2026-01-01")
    finish = Endpoint(local_date=date(2026, 1, 4), precision=EndpointPrecision.date,
                      basis="explicit", raw_expression="2026-01-04")
    result = calculate_duration(start, finish)
    assert result.basis == "date_span"
    assert result.date_span_days == 3
    assert result.elapsed_seconds is None


def test_timed_endpoint_without_timezone_or_instant_is_unavailable():
    result = calculate_duration(endpoint("2026-01-01", time(9, 0), timezone=None),
                                endpoint("2026-01-01", time(10, 0), timezone=None))
    assert result.status == "unavailable"
    assert result.reason == "timed_endpoint_timezone_or_instant_unavailable"


def test_timed_cross_timezone_local_date_reversal_uses_instants():
    start = endpoint("2026-01-02", time(1), timezone="Asia/Tokyo")
    finish = endpoint("2026-01-01", time(12), timezone="America/Los_Angeles")
    result = calculate_duration(start, finish)
    assert result.status == "available"
    assert result.elapsed_seconds == 14400
    assert result.elapsed_min_seconds == 14340
    assert result.elapsed_max_seconds == 14460


def test_reviewed_calendar_intersects_shifts_breaks_and_holiday():
    monday = date(2026, 1, 5)  # Monday
    calendar = ReviewedCalendar(
        version="calendar-v3", timezone="Asia/Kolkata",
        shifts_by_weekday={0: (Shift(time(9), time(17), ((time(12), time(13)),)),)},
        holidays=frozenset({monday}), reviewed=True,
    )
    result = calculate_duration(endpoint("2026-01-05", time(8)), endpoint("2026-01-05", time(18)), calendar=calendar)
    assert result.status == "available"
    assert result.calendar_working_seconds == 0
    assert result.calendar_version == "calendar-v3"


def test_reviewed_calendar_nonholiday_intersects_shift_and_break_with_bounds():
    calendar = ReviewedCalendar(
        version="calendar-v3", timezone="Asia/Kolkata",
        shifts_by_weekday={0: (Shift(time(9), time(17), ((time(12), time(13)),)),)},
        reviewed=True,
    )
    result = calculate_duration(endpoint("2026-01-05", time(11, 30)),
                                endpoint("2026-01-05", time(13, 30)), calendar=calendar)
    assert result.status == "available"
    assert result.calendar_working_seconds == 3600
    assert result.calendar_working_min_seconds == 3540
    assert result.calendar_working_max_seconds == 3660


def test_empty_weekday_shift_list_is_an_explicit_day_off():
    calendar = ReviewedCalendar("v1", "Asia/Kolkata", {0: ()}, reviewed=True)
    result = calculate_duration(endpoint("2026-01-05", time(9)), endpoint("2026-01-05", time(17)), calendar=calendar)
    assert result.status == "available"
    assert result.calendar_working_seconds == 0


@pytest.mark.parametrize("shifts", [
    (Shift(time(9), time(17), ((time(12), time(13)), (time(12, 30), time(13, 30)))),),
    (Shift(time(9), time(13)), Shift(time(12), time(17))),
    (Shift(time(9), time(17), ((time(8), time(9)),)),),
])
def test_malformed_calendar_intervals_make_working_duration_unavailable(shifts):
    calendar = ReviewedCalendar("v1", "Asia/Kolkata", {0: shifts}, reviewed=True)
    result = calculate_duration(endpoint("2026-01-05", time(9)), endpoint("2026-01-05", time(17)), calendar=calendar)
    assert result.status == "unavailable"
    assert result.reason == "calendar_shift_definition_unsupported"


def test_ambiguous_or_nonexistent_endpoint_wall_time_requires_normalized_instant():
    ambiguous = calculate_duration(endpoint("2026-11-01", time(1, 30), timezone="America/New_York"),
                                   endpoint("2026-11-01", time(3), timezone="America/New_York"))
    assert ambiguous.status == "unavailable"
    assert ambiguous.reason == "timed_endpoint_timezone_or_instant_unavailable"

    normalized_start = endpoint("2026-11-01", time(1, 30), timezone="America/New_York").model_copy(
        update={"normalized_instant": datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)}
    )
    disambiguated = calculate_duration(normalized_start,
                                       endpoint("2026-11-01", time(3), timezone="America/New_York"))
    assert disambiguated.status == "available"
    assert disambiguated.elapsed_seconds == 9000

    nonexistent = calculate_duration(endpoint("2026-03-08", time(2, 30), timezone="America/New_York"),
                                     endpoint("2026-03-08", time(3, 30), timezone="America/New_York"))
    assert nonexistent.status == "unavailable"


def test_calendar_wall_time_in_dst_gap_is_unavailable():
    calendar = ReviewedCalendar(
        "v1", "America/New_York", {6: (Shift(time(2, 30), time(4)),)}, reviewed=True
    )
    result = calculate_duration(endpoint("2026-03-08", time(1), timezone="America/New_York"),
                                 endpoint("2026-03-08", time(5), timezone="America/New_York"),
                                 calendar=calendar)
    assert result.status == "unavailable"
    assert result.reason == "calendar_wall_time_ambiguous_or_nonexistent"


def test_unreviewed_calendar_and_productivity_remain_unavailable():
    calendar = ReviewedCalendar("v1", "Asia/Kolkata", {0: (Shift(time(9), time(17)),)}, reviewed=False)
    result = calculate_duration(endpoint("2026-01-05", time(9)), endpoint("2026-01-05", time(17)), calendar=calendar)
    assert result.status == "unavailable"
    assert result.reason == "calendar_unreviewed"
    productivity = labour_productivity(quantity=40, crew_hours=8)
    assert productivity.status == "unavailable"
    assert productivity.reason == "measured_compatible_labour_data_unavailable"


def test_missing_lifecycle_endpoint_is_unavailable():
    result = calculate_duration(None, endpoint("2026-01-01", time(10)))
    assert result.status == "unavailable"
    assert result.reason == "missing_start_or_finish"
