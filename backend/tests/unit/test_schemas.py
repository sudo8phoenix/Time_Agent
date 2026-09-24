"""Contract tests for W-02 (run with Python 3.12 and project dependencies)."""
from datetime import date
from decimal import Decimal
import pytest
from pydantic import ValidationError
from app.schemas.observation import Observation
from app.schemas.matching import Candidate, Proposal, ApprovalRequest, proposal_model

def payload(**overrides):
    value = dict(discipline="piping", work_type="pipe_spool_erection", event_type="actual_progress",
        observed_status="in_progress", area="AREA-A", asset_tags=["24-XX"], explicit_activity_id=None,
        work_date="2026-09-21", date_basis="explicit", quantity="3", quantity_kind="delta", unit="spool",
        raw_unit="spools", reported_percent=None, actual_start=None, actual_finish=None, blocker=None,
        summary="Three spools erected.", evidence=[{"fields":["quantity"],"fragment_id":"f1","quote":"erected 3 spools"}], warnings=[])
    value.update(overrides); return value

def test_canonical_observation():
    assert Observation.model_validate(payload()).quantity == Decimal("3")

def test_observation_forbids_extra_and_negative_nonfinite():
    with pytest.raises(ValidationError): Observation.model_validate(payload(extra="x"))
    with pytest.raises(ValidationError): Observation.model_validate(payload(quantity="-1"))
    with pytest.raises(ValidationError): Observation.model_validate(payload(quantity="NaN"))
    without_nullable_key = payload()
    del without_nullable_key["actual_start"]
    with pytest.raises(ValidationError): Observation.model_validate(without_nullable_key)

def test_dynamic_candidate_membership_and_ambiguity():
    c = Candidate(candidate_id="a", external_id="A", activity_name="Pipe", work_type="welding", area=None, is_leaf=True, retrieval_rank=None, retrieval_score=None)
    model = proposal_model(["a"])
    base = dict(candidate_id="b", mapping_state="suggested", match_strength="review", explanation="x", candidates=[c], evidence_fragment_ids=[], reason_codes=[], missing_information=[], review_state="pending", proposed_effects={})
    with pytest.raises(ValidationError): model.model_validate(base)
    base.update(candidate_id="a", mapping_state="ambiguous")
    with pytest.raises(ValidationError): Proposal.model_validate(base)

def test_approval_request_requires_revisions_and_key():
    assert ApprovalRequest.model_validate({"expected_proposal_revision":1,"expected_activity_revision":2,"idempotency_key":"k","resolution_notes":None})
