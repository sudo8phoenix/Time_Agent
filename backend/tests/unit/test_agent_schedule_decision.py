from uuid import uuid4
from datetime import date
from decimal import Decimal
import json

import pytest

from app.agent.schedule_decision import (
    MAX_DISCOVERY_REQUEST_BYTES, AgentDecisionError, select_activity,
    shortlist_activities,
)


def activity(name, tag, work_type):
    return {
        "id": str(uuid4()), "external_id": name, "name": name,
        "discipline": "mechanical", "work_type": work_type,
        "area": "AREA-A", "asset_tags": tag, "is_leaf": True,
    }


def test_agent_can_choose_pump_despite_bad_extracted_type_and_tag():
    pump = activity("Install pump P-101", "P-101", "equipment_installation")
    pipe = activity("Erect pipe spool", "24-XX", "pipe_spool_erection")
    report = {
        "summary": "intalled a pump today at p101 about half work is done.",
        "work_type": "pipe_spool_erection", "asset_tags": ["p101"],
        "evidence": [{"fragment_id": "f1", "quote": "intalled a pump today at p101 about half work is done."}],
    }
    calls = []

    def model(**kwargs):
        calls.append(kwargs)
        if "candidate_ids" in kwargs["schema"]["properties"]:
            assert {item["id"] for item in kwargs["user"]["schedule_activities"]} == {pump["id"], pipe["id"]}
            return {"candidate_ids": [pump["id"]]}
        return {"candidate_id": pump["id"], "mapping_state": "suggested",
                "evidence_fragment_ids": ["f1"], "reason_codes": ["PUMP_IDENTITY"],
                "explanation": "The report names pump p101.", "missing_information": []}

    candidates = shortlist_activities(report, "schedule", [pump, pipe], model_call=model)
    proposal = select_activity(report, candidates, {"f1": report["summary"]}, model_call=model)
    assert len(calls) == 2
    assert str(proposal.candidate_id) == pump["id"]
    assert proposal.mapping_state.value == "suggested"


def test_agent_ids_and_evidence_must_stay_in_loaded_scope():
    pump = activity("Install pump P-101", "P-101", "equipment_installation")
    report = {"summary": "pump p101", "evidence": [{"fragment_id": "f1", "quote": "pump p101"}]}
    with pytest.raises(AgentDecisionError, match="unknown schedule activity"):
        shortlist_activities(report, "schedule", [pump], model_call=lambda **_: {"candidate_ids": [str(uuid4())]})
    candidates = shortlist_activities(report, "schedule", [pump], model_call=lambda **_: {"candidate_ids": [pump["id"]]})
    with pytest.raises(AgentDecisionError, match="outside the report"):
        select_activity(report, candidates, {"f1": "pump p101"}, model_call=lambda **_: {
            "candidate_id": pump["id"], "mapping_state": "suggested", "evidence_fragment_ids": ["other"],
            "reason_codes": [], "explanation": "pump", "missing_information": [],
        })


def test_agent_receives_schedule_context_for_selection():
    row = activity("Excavate footing F-01", "F-01", "excavation")
    row.update(wbs="CIV.01", aliases="foundation one", measurement_basis="quantity",
               planned_quantity=Decimal("12.0000"), unit="m3",
               planned_start=date(2026, 10, 1), planned_finish=date(2026, 10, 12))
    report = {"summary": "Excavated footing F-01", "evidence": [{"fragment_id": "f1", "quote": "Excavated footing F-01"}]}

    def model(**kwargs):
        if "schedule_activities" in kwargs["user"]:
            schedule_row = kwargs["user"]["schedule_activities"][0]
            assert schedule_row["wbs"] == "CIV.01"
            assert schedule_row["planned_quantity"] == "12.0000"
            assert schedule_row["planned_finish"] == "2026-10-12"
            return {"candidate_ids": [row["id"]]}
        candidate = kwargs["user"]["candidates"][0]
        assert candidate["aliases"] == "foundation one"
        assert candidate["measurement_basis"] == "quantity"
        assert candidate["unit"] == "m3"
        return {"candidate_id": row["id"], "mapping_state": "suggested",
                "evidence_fragment_ids": ["f1"], "reason_codes": ["ASSET_MATCH"],
                "explanation": "The report identifies the footing.", "missing_information": []}

    candidates = shortlist_activities(report, "schedule", [row], model_call=model)
    proposal = select_activity(report, candidates, {"f1": report["summary"]}, model_call=model)
    assert str(proposal.candidate_id) == row["id"]


def test_gt10_floor_conflict_cannot_silently_select_wrong_floor():
    row = activity("De-shuttering - F9", "", "unknown")
    row["external_id"] = "SUP-F8-06"
    candidates = shortlist_activities({"summary": "Finished de-shuttering F9"}, "schedule", [row],
        model_call=lambda **_: {"candidate_ids": [row["id"]]})
    proposal = select_activity({"summary": "Finished de-shuttering F9"}, candidates, {"f1": "Finished de-shuttering F9"},
        model_call=lambda **_: {"candidate_id": row["id"], "mapping_state": "suggested",
            "evidence_fragment_ids": ["f1"], "reason_codes": [], "explanation": "Floor match", "missing_information": []})
    assert proposal.candidate_id is None
    assert "SCHEDULE_LOCATION_CONFLICT" in proposal.reason_codes


def test_empty_shortlist_gets_one_reconsideration_and_validated_selection():
    row = activity("Column Reinforcement - GF", "", "rebar_installation")
    row.update(external_id="SUP-GF-01", area="GF", discipline="civil")
    report = {"summary": "200kg column reinforcement completed on ground floor"}
    calls = []
    def model(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {"candidate_ids": []}
        assert "reconsideration" in kwargs["user"]
        return {"candidate_ids": [row["id"]]}
    candidates = shortlist_activities(report, "schedule", [row], model_call=model)
    assert len(calls) == 2
    assert candidates[0].external_id == "SUP-GF-01"


def test_reconsideration_is_bounded_and_cannot_invent_ids():
    row = activity("Excavation", "", "excavation")
    calls = []
    def empty(**kwargs):
        calls.append(kwargs)
        return {"candidate_ids": []}
    assert shortlist_activities({}, "schedule", [row], model_call=empty) == []
    assert len(calls) == 2
    responses = iter([{"candidate_ids": []}, {"candidate_ids": [str(uuid4())]}])
    with pytest.raises(AgentDecisionError, match="unknown schedule activity"):
        shortlist_activities({}, "schedule", [row], model_call=lambda **_: next(responses))


def test_discovery_batches_bound_utf8_payload_and_visit_every_schedule_row():
    rows = []
    for index in range(180):
        row = activity(f"Pump {index} — installation", f"P-{index}", "equipment_installation")
        row.update(wbs=f"WBS-{index}", aliases=f"alias {index} — pump",
                   measurement_basis="installed quantity", planned_quantity="12.5000",
                   unit="m³", planned_start=date(2026, 10, 1),
                   planned_finish=date(2026, 10, 31))
        rows.append(row)

    calls = []
    def model(**kwargs):
        calls.append(kwargs)
        ids = [row["id"] for row in kwargs["user"]["schedule_activities"]]
        if len(calls) == 1:
            first = kwargs["user"]["schedule_activities"][0]
            assert first["planned_quantity"] == "12.5000"
            assert first["unit"] == "m³"
            assert first["planned_finish"] == "2026-10-31"
            return {"candidate_ids": ids[:kwargs["schema"]["properties"]["candidate_ids"]["maxItems"]]}
        return {"candidate_ids": ids[:kwargs["schema"]["properties"]["candidate_ids"]["maxItems"]]}

    result = shortlist_activities({"summary": "Pump installation reported"}, "schedule", rows, model_call=model)
    assert result
    expected = [row["id"] for row in rows]
    visited = [row["id"] for call in calls for row in call["user"]["schedule_activities"]]
    assert set(visited) == set(expected)
    for call in calls:
        payload = {"system": call["system"], "user": call["user"], "schema": call["schema"]}
        assert len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= MAX_DISCOVERY_REQUEST_BYTES


def test_oversized_single_activity_fails_before_model_call():
    row = activity("Long activity", "", "unknown")
    row["aliases"] = "á" * 9000
    calls = []
    with pytest.raises(AgentDecisionError, match="exceeds discovery byte limit"):
        shortlist_activities({}, "schedule", [row], model_call=lambda **kwargs: calls.append(kwargs))
    assert calls == []


def test_adversarial_merge_responses_still_make_progress():
    rows = [activity(f"Activity {index}", "", "unknown") for index in range(180)]
    calls = []
    def model(**kwargs):
        calls.append(kwargs)
        ids = [row["id"] for row in kwargs["user"]["schedule_activities"]]
        limit = kwargs["schema"]["properties"]["candidate_ids"]["maxItems"]
        # Return the maximum permitted number on every call, including merges.
        return {"candidate_ids": ids[:limit]}

    result = shortlist_activities({}, "schedule", rows, model_call=model)
    assert len(result) <= 8
    assert len(calls) < 30


@pytest.mark.parametrize("enabled", [False, True])
def test_delivery_identity_policy_is_explicit_and_creates_no_effects(enabled):
    row = activity("Erect spools on line L-77", "L-77", "pipe_spool_erection")
    report = {"event_type": "material_delivery", "summary": "Line L-77: spools delivered.",
        "evidence": [{"fragment_id": "f1", "quote": "Line L-77: spools delivered."}]}
    calls = []
    def model(**kwargs):
        calls.append(kwargs)
        assert ("receiving those materials" in kwargs["system"]) == enabled
        if "candidate_ids" in kwargs["schema"]["properties"]:
            return {"candidate_ids": [row["id"]]}
        return {"candidate_id": row["id"], "mapping_state": "suggested",
            "evidence_fragment_ids": ["f1"], "reason_codes": ["RECEIVING_ASSET"],
            "explanation": "The source identifies the receiving asset.", "missing_information": []}
    candidates = shortlist_activities(report, "schedule", [row], model_call=model, associate_delivery=enabled)
    proposal = select_activity(report, candidates, {"f1": report["summary"]}, model_call=model, associate_delivery=enabled)
    assert len(calls) == 2 and str(proposal.candidate_id) == row["id"]
    assert proposal.proposed_effects == {}
    assert proposal.review_state.value == "pending"
