from datetime import date
from decimal import Decimal

from app.progress.ledger import ActivityBaseline, ProgressEvent, recompute_progress, quantity_ratio


BASE = ActivityBaseline(Decimal("12"), "spool", Decimal("0"), date(2026, 9, 1))


def event(i, d, q, sem="delta", **kw):
    return ProgressEvent(i, d, q, "spool", sem, **kw)


def test_delta_and_cumulative_sequence_is_three_five_seven():
    result = recompute_progress(BASE, [event("a", date(2026, 9, 2), 3), event("b", date(2026, 9, 3), 5, "cumulative"), event("c", date(2026, 9, 4), 2)])
    assert result.completed_quantity == Decimal("7")
    assert result.physical_percent == Decimal("58.33333333333333333333333333")


def test_duplicate_source_and_correction_are_filtered():
    result = recompute_progress(BASE, [event("a", date(2026, 9, 2), 3, source_id="report-1"), event("dup", date(2026, 9, 2), 3, source_id="report-1"), event("fix", date(2026, 9, 2), 4, supersedes_event_id="a")])
    assert result.completed_quantity == Decimal("4")
    assert any("duplicate" in warning for warning in result.warnings)


def test_unsupported_units_and_overrun_are_conflicts():
    bad_unit = recompute_progress(BASE, [ProgressEvent("a", date(2026, 9, 2), 1, "each", "delta")])
    assert bad_unit.conflicts
    over = recompute_progress(BASE, [event("a", date(2026, 9, 2), 13)])
    assert over.completed_quantity == Decimal("13")
    assert over.conflicts


def test_non_progress_event_types_do_not_add_quantity():
    result = recompute_progress(BASE, [event("p", date(2026, 9, 2), 10, event_type="planned_work"), event("d", date(2026, 9, 2), 10, event_type="delivery"), event("b", date(2026, 9, 2), 10, event_type="blocker")])
    assert result.completed_quantity == Decimal("0")


def test_same_day_cumulative_conflict_and_missing_date():
    conflict = recompute_progress(BASE, [event("a", date(2026, 9, 2), 3, "cumulative"), event("b", date(2026, 9, 2), 4, "cumulative")])
    assert conflict.conflicts
    missing = recompute_progress(BASE, [event("a", None, 3)])
    assert missing.conflicts


def test_historical_event_is_not_applied_and_ratio_uses_decimal():
    result = recompute_progress(BASE, [event("old", date(2026, 8, 31), 3)])
    assert result.completed_quantity == Decimal("0")
    assert result.warnings
    assert quantity_ratio("3", "12") == Decimal("25")
