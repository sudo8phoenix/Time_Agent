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


@pytest.mark.parametrize("labels,predictions,error", [
    ([{"case_id": "a"}, {"case_id": "a"}], [], "labels contain duplicate"),
    ([{"case_id": "a"}], [{"case_id": "a"}, {"case_id": "a"}], "predictions contain duplicate"),
    ([{"case_id": "a"}], [{"case_id": "a", "candidate_ids": "A"}], "candidate_ids must be a list"),
])
def test_selection_scorer_rejects_ambiguous_case_or_candidate_inventory(labels, predictions, error):
    with pytest.raises(ValueError, match=error):
        selection_metrics(labels, predictions)


def test_failed_diagnostic_selections_cannot_earn_recall_precision_or_coverage_credit():
    labels = [
        {"case_id": "good", "expected_mapping_state": "suggested", "expected_activity_ids": ["A"]},
        {"case_id": "wrong", "expected_mapping_state": "suggested", "expected_activity_ids": ["B"]},
        {"case_id": "failed", "expected_mapping_state": "suggested", "expected_activity_ids": ["F"]},
        {"case_id": "unmatched", "expected_mapping_state": "unmatched", "expected_activity_ids": []},
    ]
    got = selection_metrics(labels, [
        {"case_id": "good", "selected_activity_id": "A", "candidate_ids": ["A"]},
        {"case_id": "wrong", "selected_activity_id": "X", "candidate_ids": ["B"]},
        {"case_id": "failed", "status": "failed", "selected_activity_id": "F", "candidate_ids": ["F"]},
        {"case_id": "unmatched", "selected_activity_id": "INVENTED"},
    ])
    assert got["recall_at_8_numerator"] == 2
    assert got["recall_at_8_denominator"] == 3
    assert got["exact_choice_numerator"] == 1
    assert got["selected"] == 3
    assert got["successful_selected"] == 2
    assert got["selected_precision"] == pytest.approx(1 / 3)
    assert got["overall_selected"] == 4
    assert got["overall_selected_precision"] == pytest.approx(1 / 4)
    assert got["coverage"] == pytest.approx(2 / 3)


@pytest.mark.parametrize("bad_row", [
    {}, {"case_id": None}, {"case_id": ""}, {"case_id": "   "},
])
def test_selection_scorer_rejects_missing_or_blank_case_identity(bad_row):
    with pytest.raises(ValueError, match="missing or blank case ID"):
        selection_metrics([{"case_id": "gold", "expected_mapping_state": "unmatched"}], [bad_row])


def test_unlabeled_prediction_rows_do_not_add_selection_credit_or_denominators():
    labels = [{"case_id": "gold", "expected_mapping_state": "suggested", "expected_activity_ids": ["A"]}]
    expected = selection_metrics(labels, [{"case_id": "gold", "selected_activity_id": "A", "candidate_ids": ["A"]}])
    with_extra = selection_metrics(labels, [
        {"case_id": "gold", "selected_activity_id": "A", "candidate_ids": ["A"]},
        {"case_id": "orphan", "selected_activity_id": "INVENTED", "candidate_ids": ["A"]},
    ])
    assert with_extra == expected


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
    assert got["case_outcomes"]["abstained"] == 0
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
    with pytest.raises(ValueError):
        validate_split([{"event_family_id":"f1"}], split, "held_out")
    with pytest.raises(ValueError):
        validate_split([{"event_family_id":"f3"}], split, "held_out")


def test_split_allows_multiple_atomic_labels_from_one_event_family():
    split = {"splits": {"held_out": ["f2"]}}
    validate_split([{"event_family_id": "f2"}, {"event_family_id": "f2"}], split, "held_out")


@pytest.mark.parametrize("prediction", [
    None,
    {"status": "failed"},
    {"status": "error"},
    {"status": "timeout"},
    {"failure": "quota exhausted"},
])
def test_missing_or_failed_output_is_not_verified_safe_abstention(prediction):
    labels = [{"case_id": "u", "expected_mapping_state": "unmatched",
               "expected_activity_ids": []}]
    predictions = [] if prediction is None else [{"case_id": "u", **prediction}]
    got = selection_metrics(labels, predictions)
    assert got["safe_abstention"] == 0
    assert got["safe_abstention_denominator"] == 1


def test_verified_abstention_and_false_match_keep_all_attempt_denominators():
    labels = [
        {"case_id": "ok", "expected_mapping_state": "unmatched"},
        {"case_id": "bad", "expected_mapping_state": "unmatched"},
        {"case_id": "missing", "expected_mapping_state": "unmatched"},
    ]
    got = selection_metrics(labels, [
        {"case_id": "ok", "selected_activity_ids": []},
        {"case_id": "bad", "selected_activity_ids": ["INVENTED"]},
    ])
    assert got["safe_abstention"] == pytest.approx(1 / 3)
    assert got["overall_selected_precision"] == 0
    assert got["overall_selected"] == 1


def test_case_outcomes_separate_missing_and_failed_outputs_from_abstentions():
    labels = [{"case_id": key} for key in ("missing", "failed", "timeout", "safe", "selected")]
    predictions = [
        {"case_id": "failed", "failure": "quota"},
        {"case_id": "timeout", "status": "TIMEOUT"},
        {"case_id": "safe", "selected_activity_ids": []},
        {"case_id": "selected", "selected_activity_id": "A"},
    ]
    got = evaluate(labels, predictions)["case_outcomes"]
    assert got["failed"] == 3
    assert got["failure_cases"] == ["missing", "failed", "timeout"]
    assert got["failure_rate"] == 3 / 5
    assert got["abstained"] == 1
    assert got["abstention_rate"] == 1 / 5


@pytest.mark.parametrize("field", ["quantity", "unit", "work_date", "start_time"])
@pytest.mark.parametrize("prediction,correct", [
    ({}, 0),
    ({"VALUE": None}, 1),
    ({"VALUE": "None"}, 0),
    ({"VALUE": "null"}, 0),
    ({"VALUE": ""}, 0),
    ({"VALUE": 0}, 0),
    ({"VALUE": None, "status": "failed"}, 0),
])
def test_critical_fields_distinguish_explicit_null_missing_and_string_null(field, prediction, correct):
    from evaluation.metrics import critical_fields
    label = {"case_id": "a", f"expected_{field}": None}
    pred = {field if key == "VALUE" else key: value for key, value in prediction.items()}
    got = critical_fields([label], [{"case_id": "a", **pred}])[field]
    assert got == {"correct": correct, "applicable": 1, "accuracy": float(correct)}


def test_critical_fields_skip_unlabelled_fields_and_accept_legacy_aliases_and_iterables():
    from evaluation.metrics import critical_fields
    labels = [{"case_id": "a", "expected_quantity": None, "expected_unit": "m3"}]
    predictions = [{"case_id": "a", "predicted_quantity": None, "predicted_unit": "m3"}]
    got = critical_fields(iter(labels), predictions)
    assert got["quantity"]["correct"] == got["unit"]["correct"] == 1
    assert got["work_date"]["applicable"] == 0
    assert critical_fields(labels, [])["quantity"]["correct"] == 0


def test_atomic_alignment_is_order_independent_for_repeated_event_types_and_counts_duplicates():
    from evaluation.metrics import atomic_extraction
    labels = [{"case_id": "a", "atomic_events": [
        {"expected_event_type": "progress", "expected_quantity": "3", "expected_unit": "m3"},
        {"expected_event_type": "progress", "expected_quantity": "7", "expected_unit": "m3"},
    ]}]
    events = [
        {"event_type": "progress", "quantity": "7", "unit": "m3"},
        {"event_type": "progress", "quantity": "3", "unit": "m3"},
    ]
    assert atomic_extraction(labels, [{"case_id": "a", "atomic_events": events}])["f1"] == 1
    got = atomic_extraction(labels, [{"case_id": "a", "atomic_events": events + [events[0]]}])
    assert got["true_positive"] == 2
    assert got["false_positive"] == 1
    assert got["false_negative"] == 0
