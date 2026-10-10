import pytest
from evaluation.metrics import evaluate, selection_metrics
from evaluation.run import validate_case_ids, validate_split
from evaluation.capture_live import prediction_rows, save_capture, validate_capture

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
    assert got["extraction"]["status"] == "unavailable"
    assert got["extraction"]["recall"] is None
    assert got["latency"]["median_ms"] == 20
    assert any(row["category"] == "event_type" for row in got["errors"])


def test_live_capture_rejects_nested_expected_labels_and_preserves_existing_file(tmp_path):
    capture = {"schema_version": 1, "mode": "live_ui_to_export",
               "run": {"commit": "abc", "model_digest": "sha256:x", "prompt_config_sha256": "sha256:y"},
               "cases": [{"case_id": "c1", "atomic_events": [{"event_key": "e1"}],
                          "candidate_ids": ["a"], "initial_state": {"event_type": "progress"}}]}
    validate_capture(capture)
    path = tmp_path / "capture.json"
    save_capture(capture, path)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        save_capture(capture, path)
    assert path.read_bytes() == original
    capture["cases"][0]["initial_state"]["expected_quantity"] = 4
    with pytest.raises(ValueError, match="label/self-reported"):
        validate_capture(capture)


def test_capture_conversion_emits_scorable_observed_event_attributes():
    capture = {"schema_version": 1, "mode": "live_ui_to_export",
               "run": {"commit": "abc", "model_digest": "sha256:x", "prompt_config_sha256": "sha256:y"},
               "cases": [{"case_id": "c1", "atomic_events": [{"event_type": "progress", "quantity": "3"}],
                          "candidate_ids": ["a"]}]}
    rows = prediction_rows(capture)
    assert rows[0]["atomic_events"] == [{"event_type": "progress", "quantity": "3"}]
    assert "atomic_event_keys" not in rows[0]


def test_atomic_event_alignment_and_lifecycle_metrics():
    labels = [{"case_id": "x", "atomic_events": [{"expected_event_type": "progress", "expected_quantity": "3"},
                                                    {"expected_event_type": "blocker", "expected_quantity": "2"}],
               "expected_mapping_state": "suggested", "expected_activity_ids": ["A"],
               "expected_start_time": "08:30", "expected_time_precision": "minute"}]
    predictions = [{"case_id": "x", "atomic_events": [{"event_type": "progress", "quantity": "3"},
                                                          {"event_type": "blocker", "quantity": "9"}],
                    "candidate_ids": ["A", "B"], "selected_activity_ids": ["A"],
                    "start_time": "08:30", "time_precision": "minute",
                    "submitted_at": "2026-01-01T00:00:00+00:00",
                    "internal_update_at": "2026-01-01T00:00:02+00:00",
                    "accepted_at": "2026-01-01T00:00:01+00:00",
                    "external_acknowledged_at": "2026-01-01T00:00:04+00:00",
                    "initial_state": {"event_type": "progress"},
                    "reviewer_corrected_state": {"event_type": "progress"}}]
    got = evaluate(labels, predictions)
    assert got["extraction"] == {"status": "scored", "true_positive": 1, "false_positive": 1, "false_negative": 1,
                                 "unmatched_gold_count": 0, "unmatched_prediction_count": 0,
                                 "precision": .5, "recall": .5, "f1": .5}
    assert got["selection"]["candidate_recall"] == 1
    assert got["critical_fields"]["time_precision"]["accuracy"] == 1
    assert got["lifecycle_latency"]["submission_to_update"]["p50_ms"] == 2000
    assert got["lifecycle_latency"]["external_delivery"]["max_ms"] == 3000


def test_events_are_case_scoped_and_keyless_scores_are_unavailable():
    labels = [{"case_id": "a", "atomic_events": [{"expected_event_type": "progress", "expected_quantity": "3"}]},
              {"case_id": "b", "atomic_events": [{"expected_event_type": "progress", "expected_quantity": "3"}]}]
    predictions = [{"case_id": "a", "atomic_events": [{"event_type": "progress", "quantity": "3"}]},
                   {"case_id": "b", "atomic_events": []}]
    got = evaluate(labels, predictions)["extraction"]
    assert got["true_positive"] == 1 and got["false_negative"] == 1
    unavailable = evaluate([{"case_id": "z", "expected_atomic_count": 2}], [{"case_id": "z"}])["extraction"]
    assert unavailable["status"] == "unavailable" and unavailable["f1"] is None


def test_selection_precision_counts_unsafe_selections_and_recall_at_8_truncates():
    labels = [{"case_id": "a", "expected_mapping_state": "suggested", "expected_activity_ids": ["A"]},
              {"case_id": "b", "expected_mapping_state": "ambiguous", "expected_activity_ids": ["B", "C"]}]
    predictions = [{"case_id": "a", "selected_activity_ids": ["A", "WRONG"],
                    "candidate_ids": ["x"] * 8 + ["A"]},
                   {"case_id": "b", "selected_activity_id": "B", "candidate_ids": ["B", "C"]}]
    got = selection_metrics(labels, predictions)
    assert got["exact_choice"] == 0 and got["overall_selected_precision"] == 0
    assert got["recall_at_8"] == 0


def test_latency_uses_nearest_rank_and_rejects_invalid_lifecycle_intervals():
    from evaluation.metrics import latency_summary, lifecycle_latency_summary
    assert latency_summary([{"latency_ms": 1}, {"latency_ms": 2}, {"latency_ms": 3}])["p95_ms"] == 3
    got = lifecycle_latency_summary([{"submitted_at": "2026-01-01T00:00:02+00:00",
                                      "internal_update_at": "2026-01-01T00:00:01+00:00"},
                                     {"submitted_at": "2026-01-01T00:00:00",
                                      "internal_update_at": "2026-01-01T00:00:01"}])
    assert got["submission_to_update"]["count"] == 0
    assert got["submission_to_update"]["p95_ms"] is None


def test_latency_rejects_nonfinite_and_negative_values_and_separates_wait_and_retry():
    from evaluation.metrics import latency_summary, lifecycle_latency_summary
    assert latency_summary([{"latency_ms": float("nan")}, {"latency_ms": float("inf")},
                           {"latency_ms": -1}])["count"] == 0
    row = {"submitted_at": "2026-01-01T00:00:00+00:00",
           "review_started_at": "2026-01-01T00:00:02+00:00",
           "review_completed_at": "2026-01-01T00:00:07+00:00",
           "internal_update_at": "2026-01-01T00:00:10+00:00",
           "retry_count": 2, "retry_duration_ms": 1200}
    got = lifecycle_latency_summary([row])
    assert got["review_wait"]["p50_ms"] == 5000
    assert got["submission_to_update"]["p50_ms"] == 10000
    assert got["system_submission_to_update_excluding_review"]["p50_ms"] == 5000
    assert got["retries"] == {"case_count": 1, "total": 2.0, "cases_with_retry": 1}
    assert got["retry_duration"]["p50_ms"] == 1200


def test_case_failure_abstention_scope_review_strata_and_project_weighting():
    labels = [
        {"case_id": "a", "expected_mapping_state": "suggested", "expected_activity_ids": ["A"],
         "expected_scope": "activity", "project_id": "p1", "report_format": "pdf", "discipline": "civil"},
        {"case_id": "b", "expected_mapping_state": "ambiguous", "expected_activity_ids": ["B", "C"],
         "expected_scope": "whole_activity", "project_id": "p2", "report_format": "xlsx", "discipline": "civil"},
        {"case_id": "c", "expected_mapping_state": "suggested", "expected_activity_ids": ["C"],
         "expected_scope": "activity", "project_id": "p2"},
    ]
    preds = [
        {"case_id": "a", "status": "ready", "selected_activity_id": "A", "scope": "activity",
         "review_required": False},
        {"case_id": "b", "status": "ready", "selected_activity_id": "WRONG", "scope": "wrong",
         "review_required": True, "reviewer_corrected_state": {"event_type": "progress"}},
        {"case_id": "c", "status": "failed", "failure": "model error", "review_required": True},
    ]
    got = evaluate(labels, preds)
    assert got["case_outcomes"]["failed"] == 1
    assert got["case_outcomes"]["abstained"] == 1
    assert got["scope"] == {"correct": 1, "applicable": 3, "missing": 1, "accuracy": 1 / 3}
    assert got["review_burden"]["review_required"] == 2
    assert got["review_burden"]["review_completed"] == 1
    assert got["strata"]["format"]["groups"]["pdf"]["exact_choice_micro"] == 1
    assert got["strata"]["discipline"]["groups"]["civil"]["cases"] == 2
    assert got["project_weighted"]["project_count"] == 2
    assert got["project_weighted"]["macro_project_exact_choice"] == .5
    assert got["project_weighted"]["micro_case"]["exact_choice_micro"] == .5


def test_case_id_validation_rejects_missing_duplicate_and_mismatched_ids():
    with pytest.raises(ValueError, match="nonempty"):
        validate_case_ids([{}], [{}])
    with pytest.raises(ValueError, match="duplicate"):
        validate_case_ids([{"case_id": "a"}, {"case_id": "a"}], [{"case_id": "a"}])
    with pytest.raises(ValueError, match="identical"):
        validate_case_ids([{"case_id": "a"}], [{"case_id": "b"}])

def test_split_rejects_overlap_and_missing_family():
    split = {"splits":{"development":["f1"], "held_out":["f2"]}}
    validate_split([{"event_family_id":"f2"}], split, "held_out")
    with pytest.raises(ValueError): validate_split([{"event_family_id":"f1"}], split, "held_out")
    with pytest.raises(ValueError): validate_split([{"event_family_id":"f3"}], split, "held_out")


def test_split_allows_multiple_atomic_labels_from_one_event_family():
    split = {"splits": {"held_out": ["f2"]}}
    validate_split([{"event_family_id": "f2"}, {"event_family_id": "f2"}], split, "held_out")
