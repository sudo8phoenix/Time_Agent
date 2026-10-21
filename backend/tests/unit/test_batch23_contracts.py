"""Offline application contracts: schema, immutable audit inputs, retry budgets."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.agent.budgets import BudgetExceeded, BudgetLimits
from app.agent.task_store import TaskStore
from app.confidence.provenance import capture
from app.llm.extract import extraction_schema
from app.llm.openrouter import _matches_schema
from app.schemas.observation import ObservationBatch
from backend.tests.unit.agent.test_hierarchical_contracts import make_store


def batch():
    return {"observations": [{
        "discipline": "civil", "work_type": "excavation", "event_type": "no_work",
        "observed_status": "unknown", "area": None, "asset_tags": [],
        "explicit_activity_id": None, "work_date": None, "date_basis": "unknown",
        "quantity": None, "quantity_kind": "none", "unit": None, "raw_unit": None,
        "reported_percent": None, "actual_start": None, "actual_finish": None,
        "blocker": None, "summary": "No excavation today.", "warnings": [],
        "evidence": [{"fields": ["event_type"], "fragment_id": "f1", "quote": "No excavation today."}],
        "lifecycle_effects": [],
    }]}


@pytest.mark.parametrize("mutation", ["valid", "missing_nullable", "enum", "nested_extra", "array_object", "null_array", "missing_nested"])
def test_actual_schema_and_application_agree_on_representations(mutation):
    value = batch()
    row = value["observations"][0]
    if mutation == "missing_nullable":
        del row["area"]
    elif mutation == "enum":
        row["event_type"] = "invented"
    elif mutation == "nested_extra":
        row["evidence"][0]["approval"] = True
    elif mutation == "array_object":
        row["evidence"] = row["evidence"][0]
    elif mutation == "null_array":
        row["asset_tags"] = None
    elif mutation == "missing_nested":
        del row["evidence"][0]["quote"]
    valid = mutation == "valid"
    assert _matches_schema(value, extraction_schema()) is valid
    if valid:
        assert ObservationBatch.model_validate(value).observations[0].area is None
    else:
        with pytest.raises(ValidationError):
            ObservationBatch.model_validate(value)


def test_audit_snapshot_survives_locator_repairs_and_mutation_of_all_input_layers():
    fields = batch()["observations"][0]
    fields["evidence"][0]["locator"] = {"page": 1, "bbox": [1, 2, 3, 4]}
    selection = {"candidate_id": "A1", "missing_information": ["date"]}
    metadata = {"source": {"raw_sha256": "a" * 64}, "parser": {"version": "fixture-v1"}}
    original = deepcopy((fields, selection, metadata))
    audit = capture(fields, selection, metadata=metadata)
    fields["evidence"][0]["locator"]["bbox"][0] = 999
    fields["summary"] = "Corrected by reviewer"
    selection["missing_information"].clear()
    metadata["parser"]["version"] = "repaired"
    assert audit["original_fields"] == original[0]
    assert audit["evidence"] == original[0]["evidence"]
    assert audit["original_selection"] == original[1]
    assert audit["model_metadata"] == original[2]


@pytest.mark.parametrize("counter", ["model_calls", "tool_calls", "supervisor_transitions"])
def test_reconstructed_retry_store_cannot_reset_any_root_counter(counter):
    engine, sessions, store, ids = make_store()
    limits = BudgetLimits(model_calls=2, tool_calls=2, supervisor_transitions=2)
    try:
        # The first reserved attempt fails downstream; a new store simulates resume.
        assert store.reserve_budget(counter, limits=limits) == 1
        resumed = TaskStore(sessions, ids[0])
        assert resumed.budget_snapshot(limits=limits)["used"][counter] == 1
        assert resumed.reserve_budget(counter, limits=limits) == 2
        exhausted = TaskStore(sessions, ids[0])
        with pytest.raises(BudgetExceeded):
            exhausted.reserve_budget(counter, limits=limits)
        assert exhausted.budget_snapshot(limits=limits)["used"][counter] == 2
    finally:
        engine.dispose()
