"""M01–M02 pinned planner resolution and scope transaction checks."""
import pytest
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from app.db.models import Activity, ActivityState, AuditEvent, Proposal, User, ProgressEvent
from app.api.endpoints.review import (ReviewChange, ApprovalRequest, revise, approve,
    search_activities, AliasApproval, approve_aliases, ResolutionRequest, resolve_unmatched)
from app.agent.project_aliases import with_project_aliases
from backend.tests.integration.test_lifecycle_acceptance import db_pair as lifecycle_db_pair, _lifecycle


db_pair = lifecycle_db_pair

def test_outside_shortlist_selection_retains_candidates_and_rejects_summary(db_pair):
    uid, pid, aid, _ = _lifecycle(db_pair, "actual_start", "2026-01-02")
    with db_pair() as db:
        original = db.get(Activity, aid)
        other = Activity(schedule_version_id=original.schedule_version_id, external_id="NEW-F8", name="Excavate floor F8",
                         wbs="Site.F8", discipline="civil", work_type="excavation", is_leaf=True,
                         measurement_basis="unsupported")
        db.add(other)
        db.flush()
        user = db.get(User, uid)
        search = search_activities(pid, "F8", 0, user, db)
        assert search["items"][0]["id"] == str(other.id)
        old_candidates = db.get(Proposal, pid).candidates
        revised = revise(pid, ReviewChange(expected_proposal_revision=1, chosen_activity_id=other.id,
                         reason="Source evidence establishes floor F8"), user, db)
        assert revised["chosen_activity_id"] == str(other.id)
        assert db.get(Proposal, revised["id"]).candidates == old_candidates
        assert any(c["id"] == str(other.id) for c in revised["candidates"])
        other.is_leaf = False
        with pytest.raises(HTTPException) as exc:
            approve(revised["id"], ApprovalRequest(expected_proposal_revision=2,
                expected_activity_revision=0, idempotency_key="summary"), user, db)
        assert exc.value.detail["code"] == "SUMMARY_ACTIVITY_INELIGIBLE"


def test_aliases_versioned_and_project_local(db_pair):
    uid, pid, aid, project_id = _lifecycle(db_pair, "actual_start", "2026-01-02")
    with db_pair() as db:
        user = db.get(User, uid)
        result = approve_aliases(pid, aid, AliasApproval(expected_revision=0, aliases=["Dig pad alpha"], reason="Reviewed report terminology"), user, db)
        db.flush()
        assert result["revision"] == 1
        assert "Dig pad alpha" in with_project_aliases(db, project_id, [db.get(Activity, aid)])[0].aliases
        assert "Dig pad alpha" not in (with_project_aliases(db, uuid4(), [db.get(Activity, aid)])[0].aliases or "")
        with pytest.raises(HTTPException):
            approve_aliases(pid, aid, AliasApproval(expected_revision=0, aliases=[], reason="stale"), user, db)
        assert search_activities(pid, "pad alpha", 0, user, db)["total"] == 1


def test_subactivity_finish_is_persisted_without_parent_finish(db_pair):
    from app.api.endpoints.progress import approved_export, _event
    from app.db.models import Project
    uid, pid, aid, project_id = _lifecycle(db_pair, "actual_finish", "2026-01-02")
    with db_pair() as db:
        proposal = db.get(Proposal, pid)
        effects = dict(proposal.proposed_effects)
        effects.update(scope="subactivity", subactivity_key="east trench", scheduled_parent_id=str(aid))
        from app.db.models import Fragment
        fragment = db.get(Fragment, effects["evidence"][0]["fragment_id"])
        fragment.original_text = "Finished east trench on 2026-01-02."
        effects["evidence"] = [{**effects["evidence"][0], "quote": fragment.original_text, "fields": ["endpoint", "scope", "subactivity_key"]}]
        proposal.proposed_effects = effects
        user = db.get(User, uid)
        result = approve(pid, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0, idempotency_key="child"), user, db)
        db.flush()
        state = db.get(ActivityState, aid)
        assert state.actual_finish is None and state.lifecycle_status == "not_started"
        assert state.lifecycle_finish_event_id is None
        event = db.get(ProgressEvent, result["event_id"])
        assert _event(event, None)["subactivity_key"] == "east trench"
        assert _event(event, None)["scheduled_parent_id"] == str(aid)
        exported = approved_export(project=db.get(Project, project_id), _user=user, db=db).body.decode()
        assert "east trench" in exported and str(aid) in exported


def test_resolution_audited_without_creating_schedule_rows(db_pair):
    uid, pid, aid, _ = _lifecycle(db_pair, "actual_start", "2026-01-02")
    with db_pair() as db:
        result = resolve_unmatched(pid, ResolutionRequest(expected_proposal_revision=1,
            reason="Planner needs missing scope supplied", outcome="missing_schedule_scope"), db.get(User, uid), db)
        db.flush()
        assert result["review_state"] == "missing_schedule_scope"
        assert db.scalar(select(AuditEvent).where(AuditEvent.target_id == pid)).action == "missing_schedule_scope"


@pytest.mark.parametrize("invalid", ["parent", "identity", "scope"])
def test_invalid_subactivity_mapping_rejected(db_pair, invalid):
    uid, pid, aid, _ = _lifecycle(db_pair, "actual_finish", "2026-01-02")
    with db_pair() as db:
        proposal = db.get(Proposal, pid)
        effects = dict(proposal.proposed_effects)
        effects.update(scope="subactivity", subactivity_key="unreported child", scheduled_parent_id=str(aid))
        effects["evidence"] = [{**effects["evidence"][0], "fields": ["endpoint", "scope"]}]
        if invalid == "parent":
            effects["scheduled_parent_id"] = str(uuid4())
        elif invalid == "scope":
            effects["scope"] = "whole_activity"
        proposal.proposed_effects = effects
        with pytest.raises(HTTPException) as exc:
            approve(pid, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0,
                                         idempotency_key="invalid-scope"), db.get(User, uid), db)
        assert exc.value.status_code == 422
        assert db.get(ActivityState, aid).actual_finish is None
        assert db.get(Proposal, pid).review_state == "pending"
