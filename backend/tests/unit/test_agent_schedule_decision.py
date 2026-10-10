from uuid import uuid4
from datetime import date
from decimal import Decimal

import pytest

from app.agent.schedule_decision import AgentDecisionError, select_activity, shortlist_activities


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
