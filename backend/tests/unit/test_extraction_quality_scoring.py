"""Diagnostic checks must reject lost clauses and unsafe non-actual effects."""
from types import SimpleNamespace as NS
from decimal import Decimal
from evaluation.extraction_quality import score


def observation(event, quantity=None, unit=None):
    return NS(event_type=NS(value=event), quantity=quantity, unit=unit,
              work_date=None, warnings=[], lifecycle_effects=[], actual_start=None,
              actual_finish=None)


def test_merged_blocker_fails_even_when_quantity_is_right():
    case = {"expected_events": ["actual_progress", "blocker"], "expected_quantity": {
        "event": "actual_progress", "quantity": "8", "unit": "m"}}
    measured = observation("actual_progress", Decimal(8), NS(value="m"))
    assert score(case, [measured])["passed"] is False
    assert score(case, [measured, observation("blocker")])["passed"] is True


def test_missing_unit_fails_without_crashing():
    case = {"expected_events": ["actual_progress"], "expected_quantity": {
        "event": "actual_progress", "quantity": "8", "unit": "m"}}
    assert score(case, [observation("actual_progress", Decimal(8))])["passed"] is False


def test_correct_events_do_not_hide_cross_clause_location_error():
    case = {"expected_events": ["actual_progress", "blocker"], "expected_fields": [
        {"event": "actual_progress", "area": "Bay D"},
        {"event": "blocker", "area": None}]}
    work = observation("actual_progress")
    work.area = "Bay D"
    blocker = observation("blocker")
    blocker.area = "Bay D"
    assert score(case, [work, blocker])["passed"] is False
    blocker.area = None
    assert score(case, [work, blocker])["passed"] is True


def test_delivery_location_must_not_be_an_asset_tag():
    case = {"expected_events": ["material_delivery"], "expected_fields": [
        {"event": "material_delivery", "area": "compound Z", "asset_tags": []}]}
    delivery = observation("material_delivery")
    delivery.area = None
    delivery.asset_tags = ["compound Z"]
    assert score(case, [delivery])["passed"] is False
    delivery.area = "compound Z"
    delivery.asset_tags = []
    assert score(case, [delivery])["passed"] is True
