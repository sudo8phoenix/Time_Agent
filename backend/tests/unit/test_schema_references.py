import json

import pytest

from app.llm.groq import GroqChatAdapter
from app.llm.openrouter import OpenRouterChatAdapter, _matches_schema
from app.llm.ollama import OllamaResponseError


def schema():
    return {"type": "object", "properties": {
        "observations": {"type": "array", "items": {"$ref": "#/$defs/Observation"}}},
        "required": ["observations"], "additionalProperties": False,
        "$defs": {"Observation": {"type": "object", "additionalProperties": False,
            "required": ["event_type"], "properties": {
                "event_type": {"$ref": "#/$defs/Event"},
                "lifecycle_effects": {"type": "array"}}},
            "Event": {"type": "string", "enum": ["no_work"]}}}


@pytest.mark.parametrize("adapter_type", [GroqChatAdapter, OpenRouterChatAdapter])
@pytest.mark.parametrize("value,valid", [
    ({"event_type": "no_work", "lifecycle_effects": []}, True),
    ({"event_type": "no_work", "lifecycle_effects[]": []}, False),
    ({"lifecycle_effects": []}, False),
    ({"event_type": "invented"}, False),
])
def test_adapters_validate_referenced_nested_contracts(adapter_type, value, valid):
    body = {"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"observations": [value]})}}]}
    adapter = adapter_type("model", bearer_token="test-key", transport=lambda *args: (200, body))
    if valid:
        assert adapter.chat(system="extract", user="source", schema=schema()).value["observations"] == [value]
    else:
        with pytest.raises(OllamaResponseError, match="did not match"):
            adapter.chat(system="extract", user="source", schema=schema())


def test_local_reference_pointer_escaping_and_ref_siblings():
    contract = {"$ref": "#/$defs/a~1b~0c", "$defs": {"a/b~c": {"type": "string"}},
                "enum": ["yes"]}
    assert _matches_schema("yes", contract)
    assert not _matches_schema("no", contract)
    assert not _matches_schema(3, contract)


@pytest.mark.parametrize("contract", [
    {"$ref": "https://example.com/schema"},
    {"$ref": "#/$defs/missing"},
    {"$ref": "#/$defs/cycle", "$defs": {"cycle": {"$ref": "#/$defs/cycle"}}},
])
def test_unresolvable_external_or_circular_references_fail_closed(contract):
    assert not _matches_schema({}, contract)


@pytest.mark.parametrize("adapter_type", [GroqChatAdapter, OpenRouterChatAdapter])
@pytest.mark.parametrize("misspelled", [False, True])
def test_real_observation_schema_rejects_misspelled_lifecycle_field(adapter_type, misspelled):
    from app.llm.extract import extraction_schema
    from app.schemas.observation import Observation
    observation = Observation.model_validate({
        "discipline": "civil", "work_type": "excavation", "event_type": "no_work",
        "observed_status": "unknown", "area": "Zone Oak", "asset_tags": [],
        "explicit_activity_id": None, "work_date": "2026-10-20", "date_basis": "report_context",
        "quantity": None, "quantity_kind": "none", "unit": None, "raw_unit": None,
        "reported_percent": None, "actual_start": None, "actual_finish": None, "blocker": None,
        "summary": "No excavation today.", "warnings": [],
        "evidence": [{"fields": ["event_type"], "fragment_id": "f1", "quote": "No excavation today."}],
    }).model_dump(mode="json")
    if misspelled:
        observation["lifecycle_effects[]"] = observation.pop("lifecycle_effects")
    value = {"observations": [observation]}
    adapter = adapter_type("model", bearer_token="test-key", transport=lambda *args: (200, {
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}]}))
    if misspelled:
        with pytest.raises(OllamaResponseError, match="did not match"):
            adapter.chat(system="extract", user="source", schema=extraction_schema())
    else:
        assert adapter.chat(system="extract", user="source", schema=extraction_schema()).value == value
