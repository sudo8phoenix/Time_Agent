from evaluation.confidence_estimator import estimate


def test_support_index_uses_source_and_not_model_claimed_strength():
    row = {"event_type": "actual_progress", "work_type": "equipment_installation",
        "summary": "Installed pump P-805", "evidence": [
            {"quote": "Installed pump P-805", "fields": ["event_type", "work_type"]}],
        "warnings": []}
    activities = [{"activity_id": "PUMP", "asset_tags": "P-805"}]
    result = estimate(row, source="Installed pump P-805", selected_activity="PUMP",
        candidate_ids=["PUMP"], activities=activities)
    assert result["extraction"]["score"] == result["linking"]["score"] == 1
    assert result["extraction"]["validation_status"] == "experimental_not_probability"
    unsupported = estimate(row, source="Installed pump P-806", selected_activity="PUMP",
        candidate_ids=["PUMP"], activities=activities)
    assert unsupported["extraction"]["score"] < result["extraction"]["score"]
    assert unsupported["linking"]["score"] < result["linking"]["score"]


def test_ambiguous_candidates_and_warnings_reduce_support_without_fabricating_probability():
    result = estimate({"summary": "work", "event_type": "actual_progress", "blocker": "testing held",
        "warnings": ["missing clause"], "evidence": []}, source="work",
        selected_activity="A", candidate_ids=["A", "B"], activities=[])
    assert result["extraction"]["score"] == 0
    assert result["linking"]["score"] == .25
