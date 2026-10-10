"""H01/H02 history, blocker acceptance and honest duration on isolated PostgreSQL."""

import csv
from datetime import date
from io import StringIO
from uuid import UUID

import pytest
from fastapi import HTTPException
from app.api.endpoints.progress import (
    execution_history,
    approved_export,
    recurring_blockers,
    actual_durations,
)
from app.api.endpoints.review import (
    approve,
    ApprovalRequest,
    LifecycleCorrectionRequest,
    LifecycleRetractionRequest,
    propose_lifecycle_correction,
    retract_lifecycle,
    BlockerCorrectionRequest,
    propose_blocker_correction,
)
from app.db.models import ActivityState, Observation, Proposal, Project, User
from backend.tests.integration.test_lifecycle_acceptance import (
    _lifecycle,
    db_pair as lifecycle_db_pair,
)
from backend.tests.integration.test_security_acceptance import (
    secured_client as security_client_fixture,
)


db_pair = lifecycle_db_pair
secured_client = security_client_fixture


def history(db, project, user, **filters):
    return execution_history(project=project, _user=user, db=db, limit=25, offset=0, **filters)


def request(revision=0, key="history"):
    return ApprovalRequest(
        expected_proposal_revision=1, expected_activity_revision=revision, idempotency_key=key
    )


def test_event_history_survives_correction_retraction_and_filters(db_pair):
    uid, pid, aid, project_id = _lifecycle(db_pair, "actual_start", "2026-01-02", time="08:30:00")
    with db_pair() as db:
        user, project = db.get(User, uid), db.get(Project, project_id)
        first = approve(pid, request(), user, db)
        proposal = db.get(Proposal, pid)
        endpoint = {**proposal.proposed_effects["endpoint"], "local_date": "2026-01-03"}
        correction = propose_lifecycle_correction(
            UUID(first["event_id"]),
            LifecycleCorrectionRequest(
                expected_activity_revision=1,
                endpoint=endpoint,
                evidence=proposal.proposed_effects["evidence"],
                reason="Reviewed date correction",
            ),
            user,
            db,
        )
        second = approve(correction["id"], request(1, "correct"), user, db)
        db.flush()
        data = history(db, project, user)
        assert data["total"] == 2
        original = next(row for row in data["items"] if row["event_id"] == first["event_id"])
        assert original["accepted_values"]["endpoint"]["local_date"] == "2026-01-02"
        assert original["latest_activity_state"]["actual_start"] == date(2026, 1, 3)
        assert original["status"] == "superseded" and original["active"] is False
        assert history(db, project, user, active_only=True)["total"] == 1
        assert history(db, project, user, correction_status="correction")["total"] == 1
        assert history(db, project, user, date_from=date(2026, 1, 3))["total"] == 1
        assert history(db, project, user, discipline="civil")["total"] == 0
        assert history(db, project, user, work_type="absent")["total"] == 0
        assert history(db, project, user, activity_id=aid)["total"] == 2
        page = execution_history(project=project, _user=user, db=db, limit=1, offset=0)
        assert page["next_offset"] == 1 and len(page["items"]) == 1
        with pytest.raises(HTTPException):
            history(db, project, user, date_from=date(2026, 2, 1), date_to=date(2026, 1, 1))
        retract_lifecycle(
            UUID(second["event_id"]),
            LifecycleRetractionRequest(
                expected_activity_revision=2,
                idempotency_key="retract",
                reason="Withdraw correction chain",
            ),
            user,
            db,
        )
        db.flush()
        assert history(db, project, user, active_only=True)["total"] == 0
        assert history(db, project, user, status="retracted")["total"] == 2
        assert history(db, project, user, correction_status="retraction")["total"] == 1
        exported = list(
            csv.DictReader(
                StringIO(approved_export(project=project, _user=user, db=db).body.decode())
            )
        )
        assert len(exported) == 3
        assert {row["status"] for row in exported} == {"retracted", "retraction"}
        assert "latest_actual_start" in exported[0] and "accepted_values" in exported[0]
        for field in (
            "activity_id",
            "activity_external_id",
            "discipline",
            "work_type",
            "wbs",
            "evidence",
            "confidence",
            "provenance",
            "model_version",
            "source_schedule_version_id",
            "decisions",
        ):
            assert field in exported[0]


def make_blocker(db, pid):
    proposal = db.get(Proposal, pid)
    old = proposal.proposed_effects
    proposal.proposed_effects = {
        "event_type": "blocker",
        "effective_date": "2026-01-02",
        "blocker": "Waiting for access",
        "blocker_category": "access",
        "evidence": old["evidence"],
    }
    return proposal


def test_quantity_free_blocker_is_evidenced_idempotent_and_corrections_count_once(db_pair):
    uid, pid, aid, project_id = _lifecycle(db_pair, "actual_start", "2026-01-02")
    with db_pair() as db:
        proposal = make_blocker(db, pid)
        user, project = db.get(User, uid), db.get(Project, project_id)
        state = db.get(ActivityState, aid)
        first = approve(pid, request(), user, db)
        assert approve(pid, request(), user, db) == first
        assert state.actual_start is None and state.completed_quantity == 0
        correction = propose_blocker_correction(
            UUID(first["event_id"]),
            BlockerCorrectionRequest(
                expected_activity_revision=1,
                blocker="Awaiting design clarification",
                blocker_category="design",
                effective_date=date(2026, 1, 2),
                evidence=proposal.proposed_effects["evidence"],
                reason="Planner recategorization",
            ),
            user,
            db,
        )
        approve(correction["id"], request(1, "correct-blocker"), user, db)
        db.flush()
        groups = recurring_blockers(project=project, _user=user, db=db)
        assert len(groups["items"]) == 1
        assert groups["items"][0]["category"] == "design" and groups["items"][0]["count"] == 1
        assert groups["items"][0]["evidence_links"][0]["evidence"]
        assert history(db, project, user, blocker="access", active_only=True)["total"] == 0
        assert history(db, project, user, blocker="design", active_only=True)["total"] == 1
        with pytest.raises(HTTPException):
            propose_blocker_correction(
                UUID(first["event_id"]),
                BlockerCorrectionRequest(
                    expected_activity_revision=2,
                    blocker="Duplicate",
                    blocker_category="other",
                    effective_date=date(2026, 1, 2),
                    evidence=proposal.proposed_effects["evidence"],
                    reason="Duplicate",
                ),
                user,
                db,
            )


@pytest.mark.parametrize("bad", ["evidence", "category", "quantity", "date"])
def test_invalid_blockers_cannot_be_accepted(db_pair, bad):
    uid, pid, aid, _ = _lifecycle(db_pair, "actual_start", "2026-01-02")
    with db_pair() as db:
        proposal = make_blocker(db, pid)
        effects = dict(proposal.proposed_effects)
        if bad == "evidence":
            effects["evidence"] = [
                {"fragment_id": effects["evidence"][0]["fragment_id"], "quote": "invented"}
            ]
        elif bad == "category":
            effects["blocker_category"] = "unreviewed arbitrary label"
        elif bad == "quantity":
            effects["quantity"] = "3"
        else:
            effects["effective_date"] = None
        proposal.proposed_effects = effects
        with pytest.raises(HTTPException):
            approve(pid, request(), db.get(User, uid), db)
        assert db.get(Proposal, pid).review_state == "pending"
        assert db.get(ActivityState, aid).revision == 0


def test_history_csv_protects_formula_cells(db_pair):
    uid, pid, _, project_id = _lifecycle(db_pair, "actual_start", "2026-01-02")
    with db_pair() as db:
        proposal = make_blocker(db, pid)
        proposal.proposed_effects = {**proposal.proposed_effects, "blocker": " =HYPERLINK(1)"}
        user, project = db.get(User, uid), db.get(Project, project_id)
        approve(pid, request(), user, db)
        db.flush()
        row = next(
            csv.DictReader(
                StringIO(approved_export(project=project, _user=user, db=db).body.decode())
            )
        )
        assert row["blocker"].startswith("' =")


def test_duration_query_uses_current_accepted_endpoint_pair_and_work_type(db_pair):
    uid, pid, aid, project_id = _lifecycle(db_pair, "actual_start", "2026-01-02")
    with db_pair() as db:
        user, project = db.get(User, uid), db.get(Project, project_id)
        approve(pid, request(), user, db)
        original = db.get(Proposal, pid)
        obs = db.get(Observation, original.observation_id)
        finish_obs = Observation(
            job_id=obs.job_id, fragment_id=obs.fragment_id, ordinal=2, fields={}, field_evidence={}
        )
        db.add(finish_obs)
        db.flush()
        values = {
            **original.proposed_effects,
            "event_type": "actual_finish",
            "observation_id": str(finish_obs.id),
            "effective_date": "2026-01-05",
            "endpoint": {**original.proposed_effects["endpoint"], "local_date": "2026-01-05"},
        }
        finish = Proposal(
            observation_id=finish_obs.id,
            revision=1,
            project_id=project_id,
            chosen_activity_id=aid,
            candidates=[],
            mapping_state="suggested",
            warnings=[],
            proposed_effects=values,
        )
        db.add(finish)
        db.flush()
        approve(finish.id, request(1, "finish"), user, db)
        data = actual_durations(project=project, _user=user, db=db, limit=25, offset=0)
        assert data["items"][0]["elapsed"]["basis"] == "date_span"
        assert data["items"][0]["elapsed"]["date_span_days"] == 3
        assert data["items"][0]["elapsed"]["elapsed_seconds"] is None
        assert data["items"][0]["calendar_working"]["status"] == "unavailable"
        assert data["items"][0]["labour_productivity"]["status"] == "unavailable"
        assert (
            actual_durations(
                project=project, _user=user, db=db, limit=25, offset=0, work_type="absent"
            )["total"]
            == 0
        )


def test_new_read_endpoints_require_session_and_project_membership(secured_client):
    client, factory, (uid, owned, foreign) = secured_client
    for path in (
        "history",
        "blockers",
        "durations",
        "exports/approved.json",
        "exports/approved.csv",
    ):
        assert client.get(f"/api/v1/projects/{foreign}/{path}").status_code == 401
    with factory() as db:
        username = db.get(User, uid).username
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": username, "password": "acceptance-password"}
        ).status_code
        == 200
    )
    for path in (
        "history",
        "blockers",
        "durations",
        "exports/approved.json",
        "exports/approved.csv",
    ):
        assert client.get(f"/api/v1/projects/{foreign}/{path}").status_code == 403
    assert client.get(f"/api/v1/projects/{owned}/history?limit=201").status_code == 422


def test_blocker_flows_through_fixture_pipeline_to_history_without_quantity(db_pair):
    from uuid import uuid4
    from sqlalchemy import select
    from app.db.models import ProjectMembership
    from app.jobs.pipeline import process_job
    from app.schemas.observation import Observation as Extracted
    from backend.tests.integration.test_worker_pipeline import _job, _obs

    with db_pair() as db:
        job, fragment, activity = _job(db)
        fragment.original_text = "Pipe installation delayed on 2026-01-02 awaiting access."
        fragment.normalised_text = fragment.original_text
        fields = _obs(fragment).model_dump(mode="json")
        fields.update(
            event_type="blocker",
            observed_status="blocked",
            quantity=None,
            quantity_kind="none",
            unit=None,
            work_date="2026-01-02",
            date_basis="explicit",
            blocker="Awaiting access",
            summary=fragment.original_text,
            evidence=[
                {
                    "fields": ["blocker", "work_date"],
                    "fragment_id": str(fragment.id),
                    "quote": fragment.original_text,
                }
            ],
        )
        extracted = Extracted.model_validate(fields)
        result = process_job(
            db,
            job,
            extraction_call=lambda _: [extracted],
            retrieve_call=lambda *_: [activity],
            selection_call=lambda *_: {
                "candidate_id": str(activity.id),
                "mapping_state": "suggested",
                "match_strength": "review",
                "explanation": "Developer fixture",
                "candidates": [],
                "missing_information": [],
            },
        )
        assert result["proposal_count"] == 1
        proposal = db.scalar(select(Proposal).join(Observation).where(Observation.job_id == job.id))
        assert proposal.proposed_effects["event_type"] == "blocker"
        assert "quantity" not in proposal.proposed_effects
        user = User(username=f"blocker-{uuid4().hex}", password_hash="unused", role="reviewer")
        db.add(user)
        db.flush()
        db.add(ProjectMembership(project_id=job.project_id, user_id=user.id))
        db.flush()
        approve(proposal.id, request(), user, db)
        db.flush()
        state = db.get(ActivityState, activity.id)
        assert (
            state.actual_start is None
            and state.actual_finish is None
            and state.completed_quantity == 0
        )
        rows = history(db, db.get(Project, job.project_id), user, blocker="other")
        assert rows["total"] == 1
        assert rows["items"][0]["evidence"][0]["locator"] == "paragraph:1"
        assert rows["items"][0]["confidence"]["extraction"]["validation_status"] == "unavailable"
