from datetime import date, time
from itertools import permutations
from pydantic import ValidationError
import pytest
from app.schemas.events import Endpoint, LifecycleKind, LifecycleScope
from app.progress.lifecycle import LifecycleEvent, recompute_lifecycle


def endpoint(day=1, hour=None):
    return Endpoint(local_date=date(2026, 10, day), local_time=time(hour, 30) if hour is not None else None,
                    precision="minute" if hour is not None else "date", basis="explicit",
                    raw_expression="reported")


def event(key, kind, value, **kwargs):
    return LifecycleEvent(key, LifecycleKind(kind), value, **kwargs)


def test_date_precision_rejects_invented_time_or_instant():
    with pytest.raises(ValidationError):
        Endpoint(local_date=date(2026, 10, 1), local_time=time(0), precision="date", basis="explicit", raw_expression="1 Oct")
    with pytest.raises(ValidationError):
        Endpoint(local_date=date(2026, 10, 1), precision="date", normalized_instant="2026-10-01T00:00:00Z", basis="explicit", raw_expression="1 Oct")


def test_permutations_and_exact_retry():
    events = [event("a", "actual_start", endpoint(1, 8), source_key="s"),
              event("retry", "actual_start", endpoint(1, 8), source_key="s"),
              event("f", "actual_finish", endpoint(2))]
    for order in permutations(events):
        result = recompute_lifecycle(None, None, order)
        assert result.valid and result.status == "completed"
        assert result.actual_start == endpoint(1, 8)
        assert result.actual_finish == endpoint(2)


def test_correction_and_disagreement():
    first = event("a", "actual_start", endpoint(1))
    corrected = event("b", "actual_start", endpoint(2), supersedes_event_id="a")
    assert recompute_lifecycle(None, None, [first, corrected]).actual_start == endpoint(2)
    result = recompute_lifecycle(None, None, [first, event("c", "actual_start", endpoint(2))])
    assert not result.valid


def test_finish_without_start_and_subactivity():
    result = recompute_lifecycle(None, None, [event("f", "actual_finish", endpoint(3))])
    assert result.valid and result.status == "completed" and result.actual_start is None
    sub = event("sub", "actual_finish", endpoint(3), scope=LifecycleScope.subactivity, subactivity_key="bay-1")
    assert recompute_lifecycle(None, None, [sub]).status == "not_started"


def test_temporal_uncertainty_and_known_inversion():
    same_day = recompute_lifecycle(None, None, [event("s", "actual_start", endpoint(1)), event("f", "actual_finish", endpoint(1, 18))])
    assert same_day.valid and same_day.warnings
    inverted = recompute_lifecycle(None, None, [event("s", "actual_start", endpoint(2, 8)), event("f", "actual_finish", endpoint(1, 18))])
    assert not inverted.valid


def test_same_id_retry_and_superseded_source_retry():
    original = event("a", "actual_start", endpoint(1), source_key="report-1")
    correction = event("b", "actual_start", endpoint(2), supersedes_event_id="a", source_key="correction")
    late_retry = event("a-retry", "actual_start", endpoint(1), source_key="report-1")
    result = recompute_lifecycle(None, None, [late_retry, correction, original, original])
    assert result.valid and result.actual_start == endpoint(2)
    assert result.warnings


def test_distinct_sources_same_endpoint_flag_suspected_duplicate():
    result = recompute_lifecycle(None, None, [event("a", "actual_start", endpoint(1)),
                                                  event("b", "actual_start", endpoint(1))])
    assert result.valid and any("suspected duplicate" in warning for warning in result.warnings)


def test_conflicting_same_id_is_order_independent():
    left = event("same", "actual_start", endpoint(1))
    right = event("same", "actual_start", endpoint(2))
    for order in permutations([left, right]):
        result = recompute_lifecycle(None, None, order)
        assert not result.valid and result.actual_start is None


def test_different_timezone_without_instants_does_not_assert_inversion():
    start = endpoint(2, 8).model_copy(update={"timezone": "Asia/Kolkata"})
    finish = endpoint(1, 18).model_copy(update={"timezone": "America/Los_Angeles"})
    result = recompute_lifecycle(None, None, [event("s", "actual_start", start),
                                               event("f", "actual_finish", finish)])
    assert result.valid and any("timezones" in warning for warning in result.warnings)


def test_local_clock_rejects_unreported_utc_suffix():
    with pytest.raises(ValidationError):
        Endpoint(local_date=date(2026, 10, 1), local_time="08:30:00Z",
                 precision="minute", basis="explicit", raw_expression="08:30")
