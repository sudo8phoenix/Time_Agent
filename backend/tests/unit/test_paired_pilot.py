import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from evaluation.paired_pilot import Budget, BudgetStop, MODELS, run


def payload(**kwargs):
    return {"model": MODELS[0], "max_completion_tokens": 1536, "messages": [], **kwargs}


def test_budget_counts_attempts_before_transport_and_preserves_failed_call_reservations():
    budget = Budget(clock=lambda: 0)
    for _ in range(4):
        assert budget.reserve(payload()) == 60
    with pytest.raises(BudgetStop):
        budget.reserve(payload())
    assert budget.calls == 4
    assert budget.tokens > 4 * 1536
    assert budget.reserved_usd > 0


def test_budget_stops_on_time_and_tokens_before_any_request():
    now = [0]
    budget = Budget(clock=lambda: now[0])
    now[0] = 360
    with pytest.raises(BudgetStop):
        budget.reserve(payload())
    assert budget.calls == 0
    budget = Budget(clock=lambda: 0)
    with pytest.raises(BudgetStop):
        budget.reserve(payload(messages=["a" * 160000]))
    assert budget.calls == 0


def test_prepare_is_offline_and_preserves_existing_output(tmp_path):
    output = tmp_path / "prepared"
    config = run(output)
    assert config["executed"] is False
    assert len(config["schedule"]) == 4
    assert [r["model"] for r in config["schedule"]] == [*MODELS, *reversed(MODELS)]
    with pytest.raises(FileExistsError):
        run(output)
    assert not (output / "predictions.jsonl").exists()


def test_provider_failure_stops_pilot_retains_attempt_and_never_exports_key(tmp_path, monkeypatch):
    import app.settings
    import evaluation.paired_pilot as pilot
    monkeypatch.setattr(app.settings, "Settings", lambda: SimpleNamespace(groq_api_key_2=SecretStr("private-key")))
    calls = []

    def failed(*args):
        calls.append(args)
        return 429, {}

    monkeypatch.setattr(pilot, "request", failed)
    output = tmp_path / "capture"
    summary = run(output, execute=True)
    assert len(calls) == 1
    assert summary["attempted"] == summary["reserved_calls"] == 1
    assert summary["completed"] == 0
    assert json.loads((output / "predictions.jsonl").read_text())["state"] == "failed"
    assert (output / "capture-manifest.json").exists()
    assert all("private-key" not in path.read_text() for path in output.iterdir())


def test_prompt_comparison_holds_model_fixed_and_freezes_effective_prompts(tmp_path):
    config = run(tmp_path / "prompt", comparison="clause-coverage")
    assert {row["model"] for row in config["schedule"]} == {MODELS[0]}
    assert [row["arm"] for row in config["schedule"]] == [
        "baseline", "clause-coverage", "clause-coverage", "baseline"]
    hashes = {row["arm"]: row["effective_system_sha256"] for row in config["schedule"]}
    assert hashes["baseline"] != hashes["clause-coverage"]
    assert len(config["label_sha256"]) == 64
    assert "no_work" in config["candidate_suffix"]


def test_regression_scores_detect_omissions_extras_wrong_dates_and_order():
    from evaluation.score_paired_pilot import event_scores
    expected = [{"event_type": "planned_work", "work_date": "2026-10-21", "area": "A"},
                {"event_type": "no_work", "work_date": "2026-10-20", "area": "A"}]
    assert event_scores(expected, list(reversed(expected)))["complete"]
    assert event_scores(expected, expected[:1])["false_negative"] == 1
    assert event_scores(expected, expected + expected[:1])["false_positive"] == 1
    wrong = [{**expected[0], "work_date": "2026-10-20"}, expected[1]]
    assert not event_scores(expected, wrong)["complete"]


def test_paired_scoring_keeps_failed_and_unattempted_rows_and_checks_label_and_capture_hashes(tmp_path):
    from hashlib import sha256
    from evaluation.score_paired_pilot import score
    output = tmp_path / "failed"
    config = run(output)
    config["executed"] = True
    (output / "config.json").write_text(json.dumps(config))
    first = config["schedule"][0]
    (output / "predictions.jsonl").write_text(json.dumps({
        "case_id": first["case_id"], "arm": first["arm"], "state": "failed"}) + '\n')
    (output / "summary.json").write_text('{"completed":0}')
    (output / "capture-manifest.json").write_text(json.dumps({
        p.name: sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}))
    got = score(output)
    assert got["scheduled"] == 4
    assert got["completed"] == 0
    assert sum(r["raw"]["false_negative"] for r in got["cases"]) == 6
    assert not any(r["normalized_fields_exact"] for r in got["cases"])
    labels = tmp_path / "wrong-labels.json"
    labels.write_text('{"cases":{}}')
    with pytest.raises(ValueError, match="Labels changed"):
        score(output, labels)
    (output / "predictions.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="integrity"):
        score(output)


def test_quantity_ablation_changes_only_suffix_and_keeps_coverage_and_model(tmp_path):
    from evaluation.paired_pilot import CLAUSE_COVERAGE_SUFFIX, QUANTITY_SUFFIX
    config = run(tmp_path / "quantity", comparison="nonactual-quantity")
    assert config["arm_suffixes"] == {
        "clause-coverage": CLAUSE_COVERAGE_SUFFIX,
        "coverage-and-quantity": CLAUSE_COVERAGE_SUFFIX + QUANTITY_SUFFIX}
    assert {row["model"] for row in config["schedule"]} == {MODELS[0]}
    broad = run(tmp_path / "broad", comparison="broad-candidate")
    assert len({row["case_id"] for row in broad["schedule"]}) == 4
    assert {row["arm"] for row in broad["schedule"]} == {"coverage-and-quantity"}
    assert broad["budget"]["calls"] == 4


def test_field_scoring_compares_numeric_quantities_and_rejects_missing_null_strings_and_bools():
    from evaluation.score_paired_pilot import fields_exact
    expected = [{"event_type": "actual_progress", "work_date": "2026-10-20", "area": "A",
                 "quantity": "6", "unit": "m3", "quantity_kind": "delta"}]
    assert fields_exact(expected, [{**expected[0], "quantity": 6.0}])
    assert not fields_exact(expected, [{**expected[0], "quantity": True}])
    empty = [{**expected[0], "quantity": None}]
    for bad in ["null", "None", "", 0]:
        assert not fields_exact(empty, [{**expected[0], "quantity": bad}])
    missing = {k: v for k, v in empty[0].items() if k != "quantity"}
    assert not fields_exact(empty, [missing])


def test_schema_failure_preserves_original_parsed_output_before_adapter_validation(tmp_path, monkeypatch):
    import app.settings
    import evaluation.paired_pilot as pilot
    monkeypatch.setattr(app.settings, "Settings", lambda: SimpleNamespace(groq_api_key_2=SecretStr("private-key")))
    invalid = {"observations": [{"lifecycle_effects[]": []}]}
    monkeypatch.setattr(pilot, "request", lambda *args: (200, {
        "model": MODELS[0], "choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(invalid)}}]}))
    output = tmp_path / "invalid"
    summary = run(output, execute=True)
    assert summary["attempted"] == 1 and summary["completed"] == 0
    assert json.loads((output / "model-outputs.jsonl").read_text())["value"] == invalid
    assert json.loads((output / "predictions.jsonl").read_text())["error_code"] == "MODEL_RESPONSE_INVALID"
