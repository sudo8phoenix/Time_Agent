from copy import deepcopy
import json
from types import SimpleNamespace

from pydantic import SecretStr

from app.llm.extract import extraction_schema
from app.llm.openrouter import _matches_schema
from evaluation.paired_pilot import MODELS, run
from evaluation.strict_schema import build_wire_schema
from evaluation.score_paired_pilot import fields_exact


def test_wire_schema_closes_objects_requires_all_fields_and_preserves_original():
    original = extraction_schema()
    saved = deepcopy(original)
    wire, changes = build_wire_schema(original)
    assert original == saved
    assert wire["$defs"]["Observation"]["required"] == list(wire["$defs"]["Observation"]["properties"])
    assert "lifecycle_effects" in wire["$defs"]["Observation"]["required"]
    assert wire["$defs"]["LifecycleEffect"]["additionalProperties"] is False
    assert any(c["keyword"] == "format" for c in changes)
    assert any(c["keyword"] == "maxItems" for c in changes)
    assert any(c["keyword"] == "required" for c in changes)
    assert wire["$defs"]["EventType"] == {"type": "string", "enum": original["$defs"]["EventType"]["enum"]}
    assert not _matches_schema({"observations": [{"lifecycle_effects[]": []}]}, wire)


def test_strict_comparison_changes_only_flag_for_each_pair_and_keeps_labels_out_of_messages(tmp_path, monkeypatch):
    import app.settings
    import evaluation.paired_pilot as pilot
    monkeypatch.setattr(app.settings, "Settings", lambda: SimpleNamespace(groq_api_key_2=SecretStr("private-key")))
    seen = []

    def transport(provider, method, url, payload, timeout, headers):
        seen.append(deepcopy(payload))
        return 200, {"model": MODELS[0], "choices": [{"finish_reason": "stop", "message": {
            "content": '{"observations":[]}'}}]}

    monkeypatch.setattr(pilot, "request", transport)
    summary = run(tmp_path / "strict", execute=True, comparison="strict-schema")
    assert summary["reserved_calls"] == 4
    assert [p["response_format"]["json_schema"]["strict"] for p in seen] == [False, True, True, False]
    for left, right in [(seen[0], seen[1]), (seen[2], seen[3])]:
        left["response_format"]["json_schema"].pop("strict")
        right["response_format"]["json_schema"].pop("strict")
        assert left == right
        assert "expected_" not in json.dumps(left["messages"])
    assert all("private-key" not in p.read_text() for p in (tmp_path / "strict").iterdir())


def test_asset_tag_scoring_preserves_identity_and_multiplicity_without_order_bias():
    expected = [{"event_type": "actual_progress", "work_date": "2026-10-20", "area": "Zone Elm",
                 "quantity": "4", "unit": "m3", "quantity_kind": "delta", "asset_tags": ["TR-017", "P-02"]}]
    assert fields_exact(expected, [{**expected[0], "asset_tags": ["P-02", "TR-017"]}])
    for tags in [["TR-017"], ["TR-017", "TR-017", "P-02"], ["tr-017", "P-02"]]:
        assert not fields_exact(expected, [{**expected[0], "asset_tags": tags}])
    literal = [{**expected[0], "asset_tags": ["missing"]}]
    assert not fields_exact(literal, [{k: v for k, v in literal[0].items() if k != "asset_tags"}])


def test_refusal_is_not_credited_as_completion_even_with_schema_valid_content(tmp_path, monkeypatch):
    import app.settings
    import evaluation.paired_pilot as pilot
    monkeypatch.setattr(app.settings, "Settings", lambda: SimpleNamespace(groq_api_key_2=SecretStr("private-key")))
    monkeypatch.setattr(pilot, "request", lambda *args: (200, {
        "model": MODELS[0], "choices": [{"finish_reason": "stop", "message": {
            "content": '{"observations":[]}', "refusal": "declined"}}]}))
    output = tmp_path / "refusal"
    summary = run(output, execute=True, comparison="strict-schema")
    assert summary["attempted"] == 1 and summary["completed"] == 0
    row = json.loads((output / "predictions.jsonl").read_text())
    assert row["response_checks"]["wire_schema_valid"] is True
    assert row["response_checks"]["refusal_present"] is True
    assert row["state"] == "failed"


def test_nullable_enum_and_decimal_unions_preserve_accepted_values():
    original = extraction_schema()
    wire, changes = build_wire_schema(original)
    original_unit = {**original["$defs"]["Observation"]["properties"]["unit"], "$defs": original["$defs"]}
    unit = wire["$defs"]["Observation"]["properties"]["unit"]
    assert unit["type"] == ["string", "null"]
    assert None in unit["enum"]
    for value in [None, "m3", "spool", "invalid-unit", 3]:
        assert _matches_schema(value, unit) == _matches_schema(value, original_unit)
    quantity = wire["$defs"]["Observation"]["properties"]["quantity"]
    assert set(quantity["type"]) == {"number", "string", "null"}
    assert any(c["keyword"] == "anyOf" for c in changes)
