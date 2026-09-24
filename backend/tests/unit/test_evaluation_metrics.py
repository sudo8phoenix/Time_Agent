import pytest
from evaluation.metrics import evaluate, selection_metrics
from evaluation.run import validate_split

def test_selection_denominators_and_safe_abstention():
    labels = [
        {"case_id":"a", "expected_mapping_state":"suggested", "expected_activity_ids":["A"]},
        {"case_id":"b", "expected_mapping_state":"ambiguous", "expected_activity_ids":["A","B"]},
        {"case_id":"c", "expected_mapping_state":"unmatched", "expected_activity_ids":[]},
    ]
    predictions = [{"case_id":"a", "selected_activity_id":"A", "candidate_ids":["A"]}, {"case_id":"b", "candidate_ids":["A","B"]}, {"case_id":"c"}]
    got = selection_metrics(labels, predictions)
    assert got["recall_at_8"] == got["exact_choice"] == got["selected_precision"] == got["coverage"] == 1
    assert got["safe_abstention"] == 1 and got["matchable"] == 1

def test_metrics_count_atomic_events_and_latency():
    labels = [{"case_id":"a", "expected_activity_ids":["A"], "expected_mapping_state":"suggested", "expected_atomic_count":2, "expected_event_type":"actual_progress", "expected_quantity":"3"}]
    predictions = [{"case_id":"a", "selected_activity_id":"A", "candidate_ids":["A"], "predicted_atomic_count":2, "correct_atomic_count":1, "event_type":"blocker", "quantity":"2", "latency_ms":10}, {"case_id":"x", "latency_ms":30}]
    got = evaluate(labels, predictions)
    assert got["extraction"]["recall"] == .5
    assert got["latency"]["median_ms"] == 20
    assert any(row["category"] == "event_type" for row in got["errors"])

def test_split_rejects_overlap_and_missing_family():
    split = {"splits":{"development":["f1"], "held_out":["f2"]}}
    validate_split([{"event_family_id":"f2"}], split, "held_out")
    with pytest.raises(ValueError): validate_split([{"event_family_id":"f1"}], split, "held_out")
    with pytest.raises(ValueError): validate_split([{"event_family_id":"f3"}], split, "held_out")


def test_split_allows_multiple_atomic_labels_from_one_event_family():
    split = {"splits": {"held_out": ["f2"]}}
    validate_split([{"event_family_id": "f2"}, {"event_family_id": "f2"}], split, "held_out")
