"""Versioned report scoring aligned to normalized domain outputs.

Legacy fields stay unchanged so old captures remain comparable. Normalized metrics keep
source quantity recall separate from progress quantity/effect safety. This does
not adjudicate the synthetic labels or claim semantic evidence correctness.
"""
from decimal import Decimal, InvalidOperation

from app.progress.ledger import quantity_ratio

SCORING_VERSION = "report-scoring-v3"
CLEARED_QUANTITY_EVENTS = {"planned_work", "no_work", "material_delivery"}


def _equal_number(left, right):
    try:
        a, b = Decimal(str(left)), Decimal(str(right))
        return a.is_finite() and b.is_finite() and a == b
    except (InvalidOperation, ValueError, TypeError):
        return False


def _equal_quantity(observation, expected_quantity, expected_unit):
    try:
        # Planned=1 gives a canonical amount via the exact conversion rules
        # already used by the production reducer; no density/unit guessing.
        converted = quantity_ratio(observation.get("quantity"), "1",
            completed_unit=observation.get("unit"), planned_unit=expected_unit) / Decimal(100)
        return _equal_number(converted, expected_quantity)
    except (ValueError, InvalidOperation, TypeError):
        return False


def normalized_scores(case, row):
    label = case["label"]
    ready = row.get("state") == "ready_for_review"
    observations = row.get("observations", [])
    selected = set(row.get("selected_activity_ids", []))
    expected = set(label["expected_activity_ids"])
    abstention = label["expected_mapping_state"] in {"unmatched", "ambiguous"}
    event = label["expected_event_type"]
    matching = [o for o in observations if o.get("event_type") == event]
    expected_quantity = label.get("expected_quantity")
    quantity = None
    policy = "not_scored"
    if event in CLEARED_QUANTITY_EVENTS:
        policy = "non_actual_quantity_cleared"
        # No missing-event credit and no credit for clearing the quantity while
        # leaking an actual-work observation or effect from the same fragment.
        quantity = ready and bool(matching) and all(
            o.get("event_type") in CLEARED_QUANTITY_EVENTS and
            o.get("quantity") is None and o.get("quantity_kind") == "none" and
            o.get("unit") is None and o.get("reported_percent") is None
            for o in observations) and not any(row.get("effects", []))
    elif expected_quantity is not None:
        policy = "actual_quantity_kind_and_unit"
        quantity = ready and any(
            _equal_quantity(o, expected_quantity, label.get("expected_unit")) and
            o.get("quantity_kind") == label.get("expected_quantity_kind") for o in matching)
    expected_events = sorted(label.get("expected_event_types") or [event])
    atomic_count = label.get("expected_atomic_count", len(expected_events))
    review = case.get("technical_review", {})
    date_correct = None
    if "expected_work_date" in review:
        date_correct = ready and bool(matching) and all(
            o.get("work_date") == review["expected_work_date"] for o in matching)
    return {
        "scoring_version": SCORING_VERSION,
        "normalized_quantity_policy": policy,
        "normalized_quantity_correct": quantity,
        "exact_mapping_correct": ready and (not selected if abstention else selected == expected),
        "atomic_events_correct": ready and len(observations) == atomic_count and
            sorted(o.get("event_type", "") for o in observations) == expected_events,
        "reviewed_work_date_correct": date_correct,
        "review_status": review.get("status", "not_reviewed"),
        "semantic_evidence_correct": None,
    }
