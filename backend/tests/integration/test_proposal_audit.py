"""Authorization and immutable proposal/decision lineage on the isolated test DB."""
import pytest
from fastapi import HTTPException
from app.api.endpoints.review import (
    ApprovalRequest, ReviewChange, LifecycleCorrectionRequest, LifecycleRetractionRequest,
    approve, revise, reject, get_proposal, propose_lifecycle_correction, retract_lifecycle,
)
from app.confidence.provenance import capture
from app.db.models import Observation, Proposal, Project, User
from backend.tests.integration.test_lifecycle_acceptance import _lifecycle
from backend.tests.integration.test_review_concurrency import _pending
from sqlalchemy.orm import sessionmaker
from app.db.session import engine


@pytest.fixture
def db_pair():
    connection = engine.connect()
    outer = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        yield factory
    finally:
        outer.rollback()
        connection.close()


def test_original_survives_revision_rejection_and_access_is_scoped(db_pair):
    user_id, proposal_id, activity_id, _ = _pending(db_pair)
    outsider_id, _, _, _ = _pending(db_pair)
    with db_pair() as db:
        proposal = db.get(Proposal, proposal_id)
        observation = db.get(Observation, proposal.observation_id)
        original = dict(observation.fields)
        observation.field_evidence = {"provenance": capture(original, {"candidate_id": str(activity_id)})}
        db.flush()
        user = db.get(User, user_id)
        updated = revise(proposal_id, ReviewChange(expected_proposal_revision=1,
                         chosen_activity_id=activity_id, field_changes={"proposed_effects": {"quantity": "3"}},
                         reason="Source correction"), user, db)
        reject(updated["id"], ReviewChange(expected_proposal_revision=2, reason="Invalid amount"), user, db)
        db.flush()
        payload = get_proposal(proposal_id, user, db)
        assert payload["provenance"]["original_fields"] == original
        assert payload["provenance"]["confidence"]["linking"]["score"] is None
        assert [row["action"] for row in payload["decision_history"]["decisions"]] == ["revise", "reject"]
        assert len(payload["decision_history"]["proposals"]) == 2
        assert payload["decision_history"]["decisions"][0]["before"]["effects"]["quantity"] == "2"
        assert payload["decision_history"]["decisions"][0]["after"]["effects"]["quantity"] == "3"
        with pytest.raises(HTTPException) as exc:
            get_proposal(proposal_id, db.get(User, outsider_id), db)
        assert exc.value.status_code == 403
        db.get(Project, proposal.project_id).active_schedule_version_id = None
        assert get_proposal(proposal_id, user, db)["decision_history"]["decisions"]
        with pytest.raises(HTTPException) as stale:
            revise(proposal_id, ReviewChange(expected_proposal_revision=1, reason="stale"), user, db)
        assert stale.value.status_code == 409


def test_accept_correct_retract_lineage_keeps_evidence_and_actor(db_pair):
    user_id, proposal_id, activity_id, _ = _lifecycle(db_pair, "actual_start", "2026-01-02", time="08:30:00")
    with db_pair() as db:
        user = db.get(User, user_id)
        accepted = approve(proposal_id, ApprovalRequest(expected_proposal_revision=1,
                           expected_activity_revision=0, idempotency_key="audit-start"), user, db)
        proposal = db.get(Proposal, proposal_id)
        corrected = propose_lifecycle_correction(accepted["event_id"], LifecycleCorrectionRequest(
            expected_activity_revision=1, endpoint=proposal.proposed_effects["endpoint"],
            evidence=proposal.proposed_effects["evidence"], reason="Confirmed original endpoint"), user, db)
        correction = approve(corrected["id"], ApprovalRequest(expected_proposal_revision=1,
                             expected_activity_revision=1, idempotency_key="audit-correct"), user, db)
        retract_lifecycle(correction["event_id"], LifecycleRetractionRequest(
            expected_activity_revision=2, idempotency_key="audit-retract", reason="Withdraw report"), user, db)
        db.flush()
        payload = get_proposal(proposal_id, user, db)
        history = payload["decision_history"]
        assert {row["action"] for row in history["decisions"]} == {"approve", "propose_correction", "retract"}
        assert len(history["events"]) == 3
        assert all(row["actor_id"] == str(user_id) and row["timestamp"] for row in history["decisions"])
        assert get_proposal(corrected["id"], user, db)["provenance"]["parent_event_id"] == accepted["event_id"]
        assert payload["provenance"]["capture_status"] == "legacy_metadata_unavailable"
