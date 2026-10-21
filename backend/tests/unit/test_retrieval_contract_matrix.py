"""Deterministic contract matrix for schedule discovery and selection boundaries.

Adapters are controlled functions. These tests exercise validation and routing;
they do not estimate model retrieval or selection quality.
"""
from uuid import uuid4

import pytest

from app.agent.schedule_decision import (
    AgentDecisionError,
    candidate_for_activity,
    select_activity,
    shortlist_activities,
)


def row(name: str, *, identifier=None, leaf=True, **updates):
    result = {
        "id": str(identifier or uuid4()),
        "external_id": name,
        "name": name,
        "discipline": "mechanical",
        "work_type": "equipment_installation",
        "area": "A",
        "is_leaf": leaf,
        "asset_tags": [],
    }
    result.update(updates)
    return result


@pytest.mark.parametrize("size", [1, 8, 9, 49])
def test_discovery_size_matrix_sends_only_leaf_rows_and_caps_output(size):
    rows = [row(f"Activity {index}") for index in range(size)]
    summary = row("Summary row", leaf=False)
    seen = []

    def adapter(**request):
        pool = request["user"]["schedule_activities"]
        seen.extend(item["id"] for item in pool)
        limit = request["schema"]["properties"]["candidate_ids"]["maxItems"]
        return {"candidate_ids": [item["id"] for item in pool[:limit]]}

    candidates = shortlist_activities({}, "pinned", [summary, *rows], model_call=adapter)
    assert set(seen) == {item["id"] for item in rows}
    assert summary["id"] not in seen
    assert len(candidates) <= 8
    assert len({str(item.candidate_id) for item in candidates}) == len(candidates)


def test_discovery_uses_candidate_id_fallback_for_uuid_identity():
    identity = uuid4()
    schedule_row = row("Candidate fallback")
    schedule_row["id"] = None
    schedule_row["candidate_id"] = identity

    def adapter(**request):
        supplied = request["user"]["schedule_activities"][0]["id"]
        assert supplied == str(identity)
        return {"candidate_ids": [supplied]}

    result = shortlist_activities({}, "pinned", [schedule_row], model_call=adapter)
    assert str(result[0].candidate_id) == str(identity)


def test_similar_ids_round_trip_to_the_exact_supplied_row():
    rows = [row("A dash", identifier="A-01"), row("A underscore", identifier="A_01"),
            row("A leading zero", identifier="A-001")]
    captured = []

    def adapter(**request):
        ids = request["schema"]["properties"]["candidate_ids"]["items"]["enum"]
        assert ids == ["row1", "row2", "row3"]
        captured.extend(request["user"]["schedule_activities"])
        return {"candidate_ids": ["row2"]}

    result = shortlist_activities({}, "pinned", rows, model_call=adapter, short_ids=True)
    assert len(captured) == 3
    assert str(result[0].candidate_id) == "A_01"
    assert result[0].activity_name == "A underscore"


@pytest.mark.parametrize("count", [0, 1, 8, 9])
def test_selection_candidate_count_boundary_is_zero_or_at_most_eight(count):
    candidates = [candidate_for_activity(row(f"Candidate {index}")) for index in range(count)]
    calls = []

    def adapter(**request):
        calls.append(request)
        first_id = request["user"]["candidates"][0]["candidate_id"]
        return {"candidate_id": first_id, "mapping_state": "suggested",
                "evidence_fragment_ids": ["f1"], "reason_codes": [],
                "explanation": "Supported", "missing_information": []}

    if count == 9:
        with pytest.raises(AgentDecisionError, match="invalid supplied candidates"):
            select_activity({}, candidates, {"f1": "work happened"}, model_call=adapter)
        assert calls == []
    elif count == 0:
        result = select_activity({}, candidates, {"f1": "work happened"}, model_call=adapter)
        assert result.candidate_id is None and result.mapping_state.value == "unmatched"
        assert calls == []
    else:
        result = select_activity({}, candidates, {"f1": "work happened"}, model_call=adapter)
        assert str(result.candidate_id) == str(candidates[0].candidate_id)
        assert len(calls) == 1


@pytest.mark.parametrize("outcome", ["ambiguous", "unmatched"])
def test_selection_safe_nonmatch_outcomes_require_null_candidate(outcome):
    candidates = [candidate_for_activity(row("Possibly related"))]
    if outcome == "ambiguous":
        candidates.append(candidate_for_activity(row("Another plausible activity")))

    def adapter(**_):
        return {"candidate_id": None, "mapping_state": outcome,
                "evidence_fragment_ids": [], "reason_codes": ["UNCERTAIN"],
                "explanation": "The decisive identity is missing.", "missing_information": ["asset"]}

    result = select_activity({}, candidates, {"f1": "pump work"}, model_call=adapter)
    assert result.candidate_id is None
    assert result.mapping_state.value == outcome


@pytest.mark.parametrize("field,value,error", [
    ("candidate_id", "unlisted-id", "unknown schedule activity"),
    ("evidence_fragment_ids", ["outside-fragment"], "evidence outside the report"),
])
def test_selection_rejects_adapter_outputs_outside_candidate_or_evidence_scope(field, value, error):
    candidate = candidate_for_activity(row("Pump installation"))
    calls = []

    def adapter(**_):
        calls.append(True)
        return {"candidate_id": str(candidate.candidate_id), "mapping_state": "suggested",
                "evidence_fragment_ids": ["f1"], "reason_codes": [],
                "explanation": "Pump", "missing_information": [], field: value}

    with pytest.raises(AgentDecisionError, match=error):
        select_activity({}, [candidate], {"f1": "pump installation"}, model_call=adapter)
    assert calls
