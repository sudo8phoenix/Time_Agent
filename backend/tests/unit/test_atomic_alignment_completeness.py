"""Incomplete event alignment cannot establish full-population quality rates."""
import pytest

from evaluation.metrics import atomic_extraction, evaluate


@pytest.mark.parametrize("side", ["gold", "prediction", "both"])
def test_unalignable_events_do_not_leave_perfect_quality_scores(side):
    labels = [{"case_id": "a", "atomic_events": [
        {"expected_event_type": "progress", "expected_quantity": "3"}]}]
    predictions = [{"case_id": "a", "atomic_events": [
        {"event_type": "progress", "quantity": "3"}]}]
    if side in {"gold", "both"}:
        labels[0]["atomic_events"].append({"expected_event_type": "blocker"})
    if side in {"prediction", "both"}:
        predictions[0]["atomic_events"].append({"event_type": "invented"})
    result = evaluate(labels, predictions)["extraction"]
    assert result["status"] == "scored_with_unaligned_events"
    assert result["true_positive"] == 1
    assert result["unmatched_gold_count"] == int(side in {"gold", "both"})
    assert result["unmatched_prediction_count"] == int(side in {"prediction", "both"})
    assert all(result[key] is None for key in ("precision", "recall", "f1"))


def test_count_only_case_cannot_disappear_from_mixed_dataset_denominator():
    labels = [
        {"case_id": "a", "atomic_events": [
            {"expected_event_type": "progress", "expected_quantity": "3"}]},
        {"case_id": "b", "expected_atomic_count": 2},
    ]
    predictions = [{"case_id": "a", "atomic_events": [
        {"event_type": "progress", "quantity": "3"}]}]
    result = atomic_extraction(labels, predictions)
    assert result["unmatched_gold_count"] == 2
    assert result["f1"] is None


def test_fully_annotated_omission_still_receives_numeric_failure():
    result = atomic_extraction([{"case_id": "a", "atomic_events": [
        {"expected_event_type": "progress", "expected_quantity": "3"}]}], [])
    assert result["status"] == "scored"
    assert result["false_negative"] == 1
    assert result["recall"] == result["f1"] == 0
