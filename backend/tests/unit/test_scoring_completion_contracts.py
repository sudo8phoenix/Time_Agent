"""Completion and unmatched-output regressions for deterministic saved scoring."""
from copy import deepcopy

import pytest

from evaluation.calibrate import assess
from evaluation.metrics import evaluate, error_categories
from evaluation.score_frozen_acceptance import score


@pytest.mark.parametrize("state,status", [("failed", "completed"), ("completed", "failed")])
def test_conflicting_completion_markers_never_earn_credit(state, status):
    labels = [{"case_id": "a", "expected_mapping_state": "suggested", "expected_activity_ids": ["A"]}]
    result = evaluate(labels, [{"case_id": "a", "state": state, "status": status, "selected_id": "A"}])
    assert result["selection"]["exact_choice"] == 0
    assert result["case_outcomes"]["failed"] == 1
    assert result["errors"] == [{"category": "failed_output", "count": 1}]


def test_nullable_labels_and_missing_annotations_are_distinct_in_error_categories():
    labels = [{"case_id": "a", "expected_quantity": None, "expected_event_type": None}]
    assert error_categories(labels, []) == [{"category": "missing_output", "count": 1}]
    assert error_categories(labels, [{"case_id": "a"}]) == [
        {"category": "event_type", "count": 1}, {"category": "quantity", "count": 1}]
    assert error_categories(labels, [{"case_id": "a", "quantity": None, "event_type": None}]) == [
        {"category": "correct", "count": 1}]
    assert error_categories([{"case_id": "a"}], [{"case_id": "a", "event_type": "progress"}]) == [
        {"category": "correct", "count": 1}]


def test_calibration_failure_marker_cannot_supply_threshold_support():
    result = assess([{"case_id": "a", "targets": {"event": "progress"}}],
                    [{"case_id": "a", "state": "completed", "failure": "provider_error",
                      "targets": {"event": "progress"}, "confidence": {"extraction": {
                          "score": 1, "method": "test", "version": "v1"}}}], min_support=1)
    event = result["metrics"]["event"]
    assert event["review_priority_threshold"] is None
    assert event["unavailable_score_count"] == 1
    assert not event["tradeoffs"]


def frozen_fixture():
    fields = {"event_type": "actual_progress", "work_date": "2026-10-21", "area": "Area A",
              "quantity": "3", "unit": "m"}
    confidence = {"extraction": {"score": 1, "method": "test", "version": "v1"}}
    source = [{"case_id": "a", "group_id": "P", "text": "3 m", "activities": []}]
    labels = [{"case_id": "a", "group_id": "P", "events": [{**fields, "link": None}]}]
    prediction = {"case_id": "a", "group_id": "P", "state": "ready_for_review", "elapsed_seconds": 1,
                  "events": [{"fields": fields, "selected_activity": None, "candidate_ids": [],
                              "confidence": confidence}]}
    calls = [{"case_id": "a", "stage": "extraction", "ok": True,
              "value": {"observations": [fields]}}]
    return source, labels, [prediction], calls


@pytest.mark.parametrize("failure", [{"state": "failed"}, {"status": "failed"}, {"failure": "provider_error"}])
def test_failed_frozen_diagnostic_events_are_not_normalized_outputs(failure):
    args = frozen_fixture()
    args[2][0].update(failure)
    result, calibration_labels, calibration_predictions = score(*args)
    assert result["initial_atomic_event_f1"] == 1  # successful first extraction remains evidence
    assert result["normalized_atomic_event_f1"] == 0
    assert result["normalized_field_accuracy"] == 0
    assert result["counts"]["failed_reports"] == 1
    assert result["proposal_readiness_seconds"]["count"] == 0
    assert len(calibration_labels) == 1
    assert calibration_predictions == []


@pytest.mark.parametrize("duration", [None, -1, float("nan"), float("inf"), True, "1"])
def test_frozen_latency_excludes_invalid_observations(duration):
    args = deepcopy(frozen_fixture())
    args[2][0]["elapsed_seconds"] = duration
    result, _, _ = score(*args)
    assert result["counts"]["ready_reports"] == 1
    assert result["proposal_readiness_seconds"]["count"] == 0
