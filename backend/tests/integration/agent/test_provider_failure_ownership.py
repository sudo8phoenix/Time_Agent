"""Transport faults must not be mislabeled as ownership loss."""
import pytest
import test_agent_runtime as runtime_tests
from evaluation.lease_investigation import scenario


@pytest.mark.parametrize("hierarchical", [False, True])
@pytest.mark.parametrize("kind", ["capacity", "response"])
def test_private_trace_distinguishes_provider_failure_without_raw_messages(hierarchical, kind, monkeypatch):
    import json
    from sqlalchemy import select
    from app.db.models import AgentRun, AgentStep, AgentToolCall
    from app.db.session import session_factory
    from app.llm.hosted import HostedCapacityError
    from app.llm.ollama import OllamaResponseError
    from app.settings import get_settings
    monkeypatch.setattr(get_settings(), "agent_hierarchy_enabled", hierarchical)
    fixture = runtime_tests.RuntimeFixture()
    original = fixture.model
    def model(**kwargs):
        if "candidate_ids" in kwargs["schema"].get("properties", {}):
            error_type = HostedCapacityError if kind == "capacity" else OllamaResponseError
            raise error_type("PRIVATE_PROVIDER_BODY_AND_SOURCE")
        return original(**kwargs)
    fixture.model = model
    try:
        assert fixture.run()["state"] == "failed"
        with session_factory() as db:
            run = db.scalar(select(AgentRun).where(AgentRun.job_id == fixture.job_id))
            call = db.scalar(select(AgentToolCall).join(AgentStep).where(
                AgentStep.run_id == run.id, AgentToolCall.tool_name == "retrieve_candidates"))
            assert call.error_code == "AGENT_TOOL_FAILED"
            assert call.sanitized_output_summary == {"failure_category":
                "MODEL_CAPACITY_TIMEOUT" if kind == "capacity" else "MODEL_RESPONSE_INVALID"}
            assert "PRIVATE_PROVIDER_BODY_AND_SOURCE" not in json.dumps({
                "summary": call.sanitized_output_summary, "message": call.error_message})
    finally:
        fixture.cleanup()


@pytest.mark.parametrize("hierarchical", [False, True])
@pytest.mark.parametrize("worker", [False, True])
@pytest.mark.parametrize("replace_lease", [False, True])
def test_transport_and_lease_failures_are_distinguished(hierarchical, worker, replace_lease):
    fixture = runtime_tests.RuntimeFixture()
    try:
        row = scenario(fixture, hierarchical=hierarchical, worker=worker, replace_lease=replace_lease)
        assert row["proposals"] == row["ledger_writes"] == 0
    finally:
        fixture.cleanup()


@pytest.mark.parametrize("hierarchical", [False, True])
@pytest.mark.parametrize("gap", ["date", "missing_blocker", "reversed_blocker", "partial_evidence", "decorated_id"])
def test_quality_gaps_reach_review_with_a_blocking_warning(hierarchical, monkeypatch, gap):
    from uuid import uuid4
    from fastapi import HTTPException
    from sqlalchemy import delete, func, select
    from app.api.endpoints.review import ApprovalRequest, approve
    from app.db.models import Fragment, Observation, ProgressEvent, ProjectMembership, Proposal, User
    from app.db.session import session_factory
    from app.settings import get_settings
    monkeypatch.setattr(get_settings(), "agent_hierarchy_enabled", hierarchical)
    fixture = runtime_tests.RuntimeFixture()
    reviewer_id = None
    try:
        with session_factory.begin() as db:
            fragment = db.get(Fragment, fixture.fragment_id)
            fragment.original_text = fragment.normalised_text = (
                "Source header 2026-09-24; body says today is 2026-09-26; Installed 2 m of cable."
                if gap == "date" else "Installed 2 m of cable; testing suspended because the permit expired.")
            user = User(username=f"date-review-{uuid4().hex}", password_hash="unused", role="reviewer")
            db.add(user)
            db.flush()
            reviewer_id = user.id
            db.add(ProjectMembership(project_id=fixture.project_id, user_id=user.id))
        if gap == "reversed_blocker":
            with session_factory.begin() as db:
                fragment = db.get(Fragment, fixture.fragment_id)
                fragment.original_text = fragment.normalised_text = "Permit expired, so testing was suspended; Installed 2 m of cable."
        if gap in {"partial_evidence", "decorated_id"}:
            from copy import deepcopy
            original = fixture.model
            def model(**kwargs):
                result = original(**kwargs)
                if "observations" in result.value:
                    item = result.value["observations"][0]
                    if gap == "decorated_id":
                        item["evidence"][0]["fragment_id"] += " | paragraph:1"
                    else:
                        invalid = deepcopy(item)
                        invalid["evidence"][0]["quote"] = "An invented second event."
                        result.value["observations"].append(invalid)
                return result
            fixture.model = model
        assert fixture.run()["state"] == "ready_for_review"
        with session_factory.begin() as db:
            proposal = db.scalar(select(Proposal).join(Observation).where(Observation.job_id == fixture.job_id))
            assert proposal.warnings
            if gap == "date":
                assert "effective_date" not in proposal.proposed_effects
            elif gap in {"missing_blocker", "reversed_blocker"}:
                assert any("no separate blocker" in warning for warning in proposal.warnings)
                assert db.scalar(select(func.count()).select_from(Observation).where(
                    Observation.job_id == fixture.job_id)) == 1
            elif gap == "partial_evidence":
                assert any("completeness check" in warning for warning in proposal.warnings)
            else:
                assert any("identifier restored" in warning for warning in proposal.warnings)
            with pytest.raises(HTTPException) as error:
                approve(proposal.id, ApprovalRequest(expected_proposal_revision=proposal.revision,
                    expected_activity_revision=0, idempotency_key=str(uuid4())), db.get(User, reviewer_id), db)
            assert error.value.detail["code"] == "UNRESOLVED_WARNINGS"
            assert db.scalar(select(func.count()).select_from(ProgressEvent).where(
                ProgressEvent.activity_id == fixture.activity_id)) == 0
    finally:
        fixture.cleanup()
        if reviewer_id:
            with session_factory.begin() as db:
                db.execute(delete(User).where(User.id == reviewer_id))
