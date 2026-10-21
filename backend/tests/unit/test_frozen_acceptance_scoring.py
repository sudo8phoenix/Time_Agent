from copy import deepcopy

import pytest

from evaluation.score_frozen_acceptance import score


def fixture():
    fields = {"event_type": "actual_progress", "work_type": "excavation", "area": "Cut Q",
        "quantity": "3", "unit": "m3", "work_date": "2026-11-17", "summary": "Excavated 3 m3 at Cut Q",
        "warnings": [], "evidence": [{"quote": "Excavated 3 m3 at Cut Q", "fields": ["event_type", "quantity"]}]}
    source = [{"case_id": "A", "group_id": "P", "text": fields["summary"],
        "activities": [{"activity_id": "EX", "asset_tags": "CUT-Q"}]}]
    labels = [{"case_id": "A", "group_id": "P", "events": [{"event_type": "actual_progress",
        "link": "EX", "area": "Cut Q", "quantity": "3", "unit": "m3", "work_date": "2026-11-17"}]}]
    predictions = [{"case_id": "A", "group_id": "P", "state": "ready_for_review", "elapsed_seconds": 12,
        "events": [{"fields": fields, "selected_activity": "EX", "candidate_ids": ["EX"]}],
        "activity_external_ids": {"uuid-a": "EX", "uuid-b": "OTHER"}}]
    calls = [{"case_id": "A", "stage": "extraction", "ok": True, "value": {"observations": [fields]}},
        {"case_id": "A", "stage": "retrieval", "ok": True, "observation": fields, "value": {"candidate_ids": ["uuid-a"]}},
        {"case_id": "A", "stage": "selection", "ok": True, "observation": fields, "value": {"candidate_id": "uuid-a"}}]
    return source, labels, predictions, calls


def test_repaired_link_does_not_replace_initial_false_selection():
    source, labels, predictions, calls = fixture()
    repaired = deepcopy(calls[-1])
    calls[-1]["value"]["candidate_id"] = "uuid-b"
    calls.append(repaired)
    result, _, _ = score(source, labels, predictions, calls)
    assert result["initial_selected_link_precision"] == 0
    assert result["counts"]["initial_false_links"] == 1
    assert result["counts"]["selection_repair_calls"] == 1


def test_schema_failed_initial_extraction_stays_missing_after_repair():
    source, labels, predictions, calls = fixture()
    calls.insert(0, {"case_id": "A", "stage": "extraction", "ok": False})
    result, _, _ = score(source, labels, predictions, calls)
    assert result["initial_atomic_event_f1"] == 0
    assert result["normalized_atomic_event_f1"] == 1
    assert result["counts"]["reports_needing_initial_model_correction"] == 1


def test_extra_events_and_links_are_errors_instead_of_free_credit():
    source, labels, predictions, calls = fixture()
    extra = deepcopy(calls[0]["value"]["observations"][0])
    extra["summary"] = "Another excavation claim"
    calls[0]["value"]["observations"].append(extra)
    calls.append({"case_id": "A", "stage": "selection", "ok": True,
        "observation": extra, "value": {"candidate_id": "uuid-a"}})
    result, _, _ = score(source, labels, predictions, calls)
    assert result["counts"]["initial_false_positive"] == 1
    assert result["initial_selected_link_precision"] == .5


def test_failed_missing_case_counts_in_event_and_candidate_denominators():
    source, labels, _, _ = fixture()
    result, _, _ = score(source, labels, [], [])
    assert result["initial_atomic_event_f1"] == 0
    assert result["candidate_recall_at_8"] == 0
    assert result["counts"]["failed_reports"] == 1


def test_duplicate_type_labels_require_explicit_alignment_instead_of_row_order_credit():
    import pytest
    source, labels, predictions, calls = fixture()
    labels[0]["events"].append(deepcopy(labels[0]["events"][0]))
    with pytest.raises(ValueError, match="duplicate-type alignment"):
        score(source, labels, predictions, calls)


def test_recall_at_eight_does_not_credit_ninth_candidate():
    source, labels, predictions, calls = fixture()
    predictions[0]["events"][0]["candidate_ids"] = [f"WRONG-{i}" for i in range(8)] + ["EX"]
    result, _, _ = score(source, labels, predictions, calls)
    assert result["candidate_recall_at_8"] == 0


def test_failed_calls_with_diagnostic_values_never_earn_quality_credit():
    source, labels, predictions, calls = fixture()
    calls[0]["ok"] = False
    calls[-1]["ok"] = False
    result, _, _ = score(source, labels, predictions, calls)
    assert result["initial_atomic_event_f1"] == 0
    assert result["initial_selected_link_precision"] is None
    assert result["initial_selected_link_coverage"] == 0


@pytest.mark.parametrize("defect", ["empty", "duplicate_source", "missing_source", "unknown_call", "wrong_group"])
def test_invalid_score_inventory_fails_closed(defect):
    source, labels, predictions, calls = fixture()
    if defect == "empty":
        labels = []
        predictions = []
        calls = []
    elif defect == "duplicate_source":
        source.append(deepcopy(source[0]))
    elif defect == "missing_source":
        source = []
    elif defect == "unknown_call":
        calls.append({"case_id": "unknown", "stage": "selection", "ok": False})
    else:
        predictions[0]["group_id"] = "OTHER-PROJECT"
    with pytest.raises(ValueError):
        score(source, labels, predictions, calls)
