import json

from evaluation.capture_inventory import inventory


def test_inventory_keeps_failed_repeated_cases_and_exports_only_identity(tmp_path):
    capture = tmp_path / "run"
    capture.mkdir()
    (capture / "predictions.jsonl").write_text(
        '\n'.join(json.dumps(row) for row in [
            {"case_id": "a", "group_id": "family", "failure": "private error"},
            {"case_id": "a", "source": "private report", "expected_quantity": 123},
            {"case_id": "b", "state": "failed"},
        ]) + '\nnull\n{"source": "private source"}\n')
    # Labels are deliberately invalid JSON: inventory must never parse them.
    (capture / "labels.jsonl").write_text("unopened labels")
    got = inventory(tmp_path)
    assert got["capture_count"] == 1
    assert got["unique_case_id_count"] == 2
    row = got["captures"][0]
    assert row["attempt_rows"] == 3
    assert row["case_identities"] == [
        {"case_id": "a", "group_id": "family"}, {"case_id": "a"}, {"case_id": "b"}]
    assert len(row["errors"]) == 2
    assert "private" not in json.dumps(got)
    assert len(row["sha256"]) == 64


def test_inventory_covers_derived_predictions_and_model_outputs_without_opening_labels(tmp_path):
    from evaluation.capture_inventory import CAPTURE_NAMES
    for index, name in enumerate(sorted(CAPTURE_NAMES)):
        (tmp_path / name).write_text(json.dumps({"case_id": str(index), "family": "f"}) + '\n')
    (tmp_path / "calibration-labels.jsonl").write_text("must not parse")
    (tmp_path / "inputs.jsonl").write_text("must not parse")
    got = inventory(tmp_path)
    assert got["capture_count"] == got["unique_case_id_count"] == len(CAPTURE_NAMES)
    assert not any(row["errors"] for row in got["captures"])


def test_reports_and_calls_keep_injected_execution_distinct_from_live(tmp_path):
    for mode in ['live_groq', 'injected_transport']:
        root = tmp_path/mode
        root.mkdir()
        (root/'config.json').write_text(json.dumps({'execution_mode':mode,'prompts':'private prompts'}))
        for name in ['reports.jsonl', 'calls.jsonl', 'usage.jsonl']:
            (root/name).write_text(json.dumps({'case_id':'same-id','output':'private report'})+'\n')
    got = inventory(tmp_path)
    assert got['capture_count'] == 6 and got['unique_case_id_count'] == 1
    assert {r['execution_mode'] for r in got['captures']} == {'live_groq', 'injected_transport'}
    assert 'private' not in json.dumps(got)
