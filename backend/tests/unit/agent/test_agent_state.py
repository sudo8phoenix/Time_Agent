from __future__ import annotations

import json
from datetime import date

import pytest

from app.agent.state import (
    AgentWarning,
    AgentStateError,
    create_initial_state,
    decode_agent_state,
    encode_agent_state,
    observation_keys,
    validate_identity_transition,
)

IDS = {
    "run_id": "11111111-1111-4111-8111-111111111111",
    "job_id": "22222222-2222-4222-8222-222222222222",
    "project_id": "33333333-3333-4333-8333-333333333333",
    "report_id": "44444444-4444-4444-8444-444444444444",
    "schedule_version_id": "55555555-5555-4555-8555-555555555555",
}


def initial(**updates):
    payload = {
        **IDS,
        "fragment_ids": ["66666666-6666-4666-8666-666666666666"],
        "activity_ids": ["77777777-7777-4777-8777-777777777777"],
    }
    payload.update(updates)
    return create_initial_state(**payload)


def observation():
    return {
        "discipline": "civil",
        "work_type": "concrete_pour",
        "event_type": "actual_progress",
        "observed_status": "completed",
        "area": None,
        "asset_tags": [],
        "explicit_activity_id": None,
        "work_date": date(2026, 9, 24).isoformat(),
        "date_basis": "explicit",
        "quantity": None,
        "quantity_kind": "none",
        "unit": None,
        "raw_unit": None,
        "reported_percent": None,
        "actual_start": None,
        "actual_finish": None,
        "blocker": None,
        "summary": "Concrete pour completed",
        "evidence": [{"fields": ["summary"], "fragment_id": IDS["report_id"], "quote": "Concrete pour completed"}],
        "warnings": [],
    }


def test_full_json_round_trip_and_initial_only_counter_defaults():
    state = initial(observation_drafts=[observation()])
    assert state.counters.model_dump() == {
        "node_executions": 0,
        "extraction_calls": 0,
        "selection_calls": 0,
        "corrective_retries": 0,
    }
    assert decode_agent_state(encode_agent_state(state)) == state
    resumed = state.model_dump(mode="json")
    del resumed["counters"]
    with pytest.raises(Exception):
        decode_agent_state(json.dumps(resumed))
    with pytest.raises(AgentStateError):
        initial(counters={"node_executions": 0})


@pytest.mark.parametrize("payload", [
    {**IDS, "unknown": True},
    {**IDS, "run_id": "11111111-1111-4111-8111-11111111111A"},
    {**IDS, "run_id": "11111111111141118111111111111111"},
])
def test_unknown_fields_and_noncanonical_identity_are_rejected(payload):
    with pytest.raises(AgentStateError):
        initial(**payload)


def test_duplicate_id_lists_candidate_overflow_and_unmatched_keys_are_rejected():
    duplicate = "66666666-6666-4666-8666-666666666666"
    with pytest.raises(AgentStateError):
        initial(fragment_ids=[duplicate, duplicate])
    candidates = [{
        "candidate_id": f"88888888-8888-4888-8888-{n:012d}",
        "external_id": f"A{n}", "activity_name": f"Activity {n}", "area": None,
        "work_type": "concrete_pour", "is_leaf": True, "retrieval_rank": n + 1,
        "retrieval_score": 0.5,
    } for n in range(9)]
    with pytest.raises(AgentStateError):
        initial(observation_drafts=[observation()], candidate_sets={"obs-0001": candidates})
    with pytest.raises(AgentStateError):
        initial(observation_drafts=[observation()], candidate_sets={"obs-0002": []})


def test_nonempty_candidate_map_must_have_exact_observation_keys_and_schemas():
    with pytest.raises(AgentStateError):
        initial(observation_drafts=[observation(), observation()], candidate_sets={"obs-0001": []})
    with pytest.raises(AgentStateError):
        initial(observation_drafts=[observation()], candidate_sets={"obs-0001": [{"unexpected": True}]})
    with pytest.raises(AgentStateError):
        initial(counters={
            "node_executions": 0, "extraction_calls": 0,
            "selection_calls": 401, "corrective_retries": 0,
        })


def test_observation_key_generation_is_run_local_and_bounded():
    assert observation_keys(3) == ["obs-0001", "obs-0002", "obs-0003"]
    with pytest.raises(AgentStateError) as exc:
        observation_keys(201)
    assert exc.value.code == "AGENT_OBSERVATION_LIMIT"


def test_identity_is_immutable_across_transition():
    previous = initial()
    current_payload = previous.model_dump(mode="python")
    current_payload["job_id"] = IDS["run_id"]
    from app.agent.state import AgentState
    current = AgentState.model_validate(current_payload)
    with pytest.raises(AgentStateError):
        validate_identity_transition(previous, current)


def test_oversize_and_nested_nonfinite_json_are_rejected():
    state = initial()
    too_large = state.model_copy(update={"warnings": [
        AgentWarning(code="X", message="x" * 1000) for _ in range(1100)
    ]})
    with pytest.raises(AgentStateError) as exc:
        encode_agent_state(too_large)
    assert exc.value.code == "AGENT_STATE_TOO_LARGE"
    payload = state.model_dump(mode="json")
    payload["model_metadata"]["settings_hash"] = float("nan")
    from app.agent.state import ModelMetadata
    bad_metadata = ModelMetadata.model_construct(**payload["model_metadata"])
    with pytest.raises(AgentStateError):
        encode_agent_state(state.model_copy(update={"model_metadata": bad_metadata}))
    payload["warnings"] = [{"code": "X", "message": float("inf")}]
    with pytest.raises(AgentStateError):
        decode_agent_state(json.dumps(payload, allow_nan=True))


def test_secret_and_runtime_fields_cannot_enter_state_or_json():
    secret = "lease-sentinel-DO-NOT-SERIALIZE"
    with pytest.raises(AgentStateError):
        initial(lease_token=secret)
    serialized = encode_agent_state(initial()).decode()
    assert secret not in serialized
    for forbidden in ("session_factory", "model_callable", "database_url", "ollama_url", "lease_token"):
        assert forbidden not in serialized
