from evaluation.report_planner_eval import load_cases, score_case, summarize


def test_fixture_selection_separates_labels_and_covers_risk_families():
    cases = load_cases()
    assert len(cases) == 6
    assert len({case["family"] for case in cases}) == 6
    for case in cases:
        assert "expected_activity_ids" not in case["text"]
        assert case["label"]["case_id"] == case["case_id"]
        assert case["text"].strip()


def test_failed_run_is_not_credited_as_safe_abstention():
    case = next(case for case in load_cases() if case["family"] == "unmatched")
    failed = score_case(case, {"state": "failed", "selected_activity_ids": [], "observations": []})
    assert not failed["safe_abstention"] and not failed["mapping_correct"]
    ready = score_case(case, {"state": "ready_for_review", "selected_activity_ids": [], "observations": []})
    assert ready["safe_abstention"] and ready["mapping_correct"]


def test_ambiguous_fixture_requires_abstention_even_for_a_labeled_candidate():
    case = next(case for case in load_cases() if case["family"] == "ambiguous_match")
    score = score_case(case, {"state": "ready_for_review",
        "selected_activity_ids": case["label"]["expected_activity_ids"][:1], "observations": []})
    assert not score["mapping_correct"]
    assert not score["safe_abstention"]


def test_summary_counts_failed_calls_and_includes_no_missing_results_as_success():
    case = next(case for case in load_cases() if case["family"] == "unmatched")
    row = {"arm": "v2_super_vl", "state": "failed", "error_code": "AGENT_PLANNER_FAILED",
        "elapsed_ms": 500, "ledger_writes": 0, "calls": [{"stage": "planner", "ok": False}]}
    row["scores"] = score_case(case, row)
    summary = summarize([row])
    assert summary["v2_super_vl"]["ready"] == 0
    assert summary["v2_super_vl"]["safe_abstentions"] == 0
    assert summary["v2_super_vl"]["failed_model_calls"] == 1
    assert summary["v1_groq"]["cases"] == 0


def test_failed_runtime_capture_checks_ledger_through_observation_scope(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.base import Base
    from app.settings import Settings
    from evaluation.report_planner_eval import Recorder, seed, run_case, runtime
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    cases = load_cases()[:1]
    project, schedule = seed(sessions, cases)
    monkeypatch.setattr(runtime, "process_job_with_graph", lambda *a, **k: {
        "state": "failed", "error_code": "AGENT_TOOL_FAILED"})
    monkeypatch.setattr(runtime, "get_settings", runtime.get_settings)
    recorder = Recorder()
    recorder.arm = "v1_groq"
    _, row = run_case(sessions, project, schedule, cases[0], Settings(_env_file=None), recorder)
    assert row["ledger_writes"] == 0
    assert row["state"] == "failed"
    assert not row["scores"]["mapping_correct"]


def test_planned_quantity_normalization_is_scored_separately_from_source_recall():
    case = next(c for c in load_cases(dataset="seed") if c["case_id"] == "C03")
    row = {"state": "ready_for_review", "selected_activity_ids": case["label"]["expected_activity_ids"],
        "observations": [{"event_type": "planned_work", "quantity": None, "quantity_kind": "none",
                          "unit": None, "reported_percent": None}], "effects": [{}]}
    scores = score_case(case, row)
    assert scores["quantity_correct"] is False  # historical raw label score stays visible
    assert scores["normalized_quantity_correct"] is True
    assert scores["normalized_quantity_policy"] == "non_actual_quantity_cleared"
    row["effects"] = [{"quantity": "3"}]
    assert score_case(case, row)["normalized_quantity_correct"] is False
    row["effects"] = []
    row["observations"] = []
    assert score_case(case, row)["normalized_quantity_correct"] is False


def test_normalized_quantity_requires_kind_unit_and_event_on_the_same_observation():
    case = next(c for c in load_cases(dataset="seed") if c["case_id"] == "C01")
    row = {"state": "ready_for_review", "observations": [
        {"event_type": "actual_progress", "quantity": "3", "quantity_kind": "cumulative", "unit": "kg"}]}
    assert score_case(case, row)["quantity_correct"] is True
    assert score_case(case, row)["normalized_quantity_correct"] is False
    row["observations"][0].update(quantity_kind="delta", unit="spool")
    assert score_case(case, row)["normalized_quantity_correct"] is True
    row["state"] = "failed"
    assert score_case(case, row)["normalized_quantity_correct"] is False


def test_exact_mapping_and_atomic_metrics_do_not_credit_partial_multi_event_output():
    case = load_cases(["C05"], dataset="seed")[0]
    row = {"state": "ready_for_review", "selected_activity_ids": case["label"]["expected_activity_ids"][:1],
           "observations": [{"event_type": "actual_progress"}]}
    scores = score_case(case, row)
    assert scores["mapping_correct"] is True
    assert scores["exact_mapping_correct"] is False
    assert scores["atomic_events_correct"] is False


def test_reviewed_dates_do_not_imply_human_adjudication_or_semantic_evidence_correctness():
    case = load_cases(["C18"], dataset="seed")[0]
    case["technical_review"] = {"expected_work_date": None, "status": "technical_review_not_human"}
    row = {"state": "ready_for_review", "observations": [{"event_type": "actual_progress", "work_date": "2026-09-23"}]}
    scores = score_case(case, row)
    assert scores["reviewed_work_date_correct"] is False
    assert scores["semantic_evidence_correct"] is None
    assert scores["review_status"] == "technical_review_not_human"


def test_normalized_mass_quantity_uses_production_conversion_without_changing_raw_score():
    case = load_cases(["C12"], dataset="seed")[0]
    row = {"state": "ready_for_review", "observations": [{"event_type": "actual_progress",
        "quantity": "0.5", "quantity_kind": "delta", "unit": "t"}]}
    scores = score_case(case, row)
    assert scores["quantity_correct"] is False
    assert scores["normalized_quantity_correct"] is True
    assert scores["scoring_version"] == "report-scoring-v3"
    row["observations"][0]["unit"] = "m3"
    assert score_case(case, row)["normalized_quantity_correct"] is False
