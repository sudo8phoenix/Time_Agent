"""T02 HTTP recovery and review gate on an isolated migrated PostgreSQL database."""
import re
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.db.models import (Activity, ActivityState, Project, ProjectMembership,
                           ScheduleVersion, User)
from app.db.passwords import hash_password
from app.db.session import session_factory


def test_two_events_stay_pending_until_reviewer_accepts(monkeypatch):
    suffix = uuid4().hex[:10]
    password = "Conversation-test-passphrase!"
    with session_factory.begin() as db:
        supervisor = User(username=f"t02super-{suffix}", password_hash=hash_password(password), role="viewer")
        reviewer = User(username=f"t02review-{suffix}", password_hash=hash_password(password), role="reviewer")
        project = Project(name=f"T02 HTTP {suffix}", timezone="Asia/Kolkata")
        schedule = ScheduleVersion(project=project, version_number=1, content_sha256=uuid4().hex, state="active")
        db.add_all([supervisor, reviewer, project, schedule])
        db.flush()
        project.active_schedule_version_id = schedule.id
        db.add_all([ProjectMembership(project_id=project.id, user_id=supervisor.id),
                    ProjectMembership(project_id=project.id, user_id=reviewer.id)])
        for site in ("F-01", "F-02"):
            activity = Activity(schedule_version=schedule, external_id=f"EX-{site}", name=f"Excavation {site}",
                                wbs=site, discipline="civil", work_type="excavation", area=site,
                                asset_tags=site, is_leaf=True, measurement_basis="unsupported",
                                planned_quantity=None, unit=None)
            db.add(activity)
            db.flush()
            db.add(ActivityState(activity=activity, revision=0, completed_quantity=Decimal(0)))
        project_id = project.id
        activity_ids = {row.area: row.id for row in db.scalars(select(Activity).where(Activity.schedule_version_id == schedule.id))}

    observed_ids = []

    def model_call(**kwargs):
        system = kwargs["system"]
        if "Extract" in system or "atomic" in system.lower():
            fragment_id = re.search(r"\[([a-f0-9-]{36}) \|", kwargs["user"]).group(1)
            observed_ids.append(fragment_id)
            observations = []
            for site, kind, clock in (("F-01", "actual_start", "08:30:00"), ("F-02", "actual_finish", "16:15:00")):
                quote = ("Started excavation at F-01 at 08:30" if site == "F-01"
                         else "finished part of excavation at F-02 at 16:15")
                observations.append({
                    "discipline": "civil", "work_type": "excavation", "event_type": kind,
                    "observed_status": "in_progress" if kind == "actual_start" else "completed",
                    "area": site, "asset_tags": [site], "explicit_activity_id": None,
                    "work_date": "2026-10-09", "date_basis": "report_context",
                    "quantity": None, "quantity_kind": "none", "unit": None, "raw_unit": None,
                    "reported_percent": None, "actual_start": None, "actual_finish": None,
                    "blocker": None, "summary": quote,
                    "evidence": [{"fields": ["event_type"], "fragment_id": fragment_id, "quote": quote}],
                    "warnings": [], "lifecycle_effects": [{"kind": kind, "scope": "whole_activity",
                        "endpoint": {"local_date": "2026-10-09", "local_time": clock,
                                     "precision": "minute", "basis": "report_context", "raw_expression": clock},
                        "evidence": [{"fields": ["endpoint"], "fragment_id": fragment_id, "quote": quote}]}],
                })
            return {"observations": observations}
        if "Choose plausible schedule activities" in system:
            site = kwargs["user"]["observation"]["area"]
            return {"candidate_ids": [str(activity_ids[site])]}
        site = kwargs["user"]["observation"]["area"]
        return {"candidate_id": str(activity_ids[site]), "mapping_state": "suggested",
                "evidence_fragment_ids": observed_ids, "reason_codes": ["ASSET_MATCH"],
                "explanation": f"{site} matches", "missing_information": []}

    monkeypatch.setattr("app.conversation.service._model_call", lambda: model_call)
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": f"t02super-{suffix}", "password": password})
        assert login.status_code == 200
        csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
        base = f"/api/v1/projects/{project_id}/conversations"
        created = client.post(base, headers=csrf).json()
        response = client.post(f"{base}/{created['id']}/messages", headers=csrf,
                               json={"text": "Started excavation at F-01 at 08:30 and finished part of excavation at F-02 at 16:15.",
                                     "report_date": "2026-10-09", "expected_revision": 0})
        assert response.status_code == 200, response.text
        draft = response.json()
        assert len(draft["events"]) == 2, draft
        assert draft["pending_question"] == "scope"
        edited = client.post(f"{base}/{created['id']}/edit", headers=csrf,
                             json={"event_index": 1, "expected_revision": draft["revision"],
                                   "scope": "subactivity", "subactivity_key": "east bay"})
        assert edited.status_code == 200, edited.text
        draft = edited.json()
        assert draft["pending_question"] is None
        assert draft["events"][1]["effect"]["scope"] == "subactivity"
        assert draft["events"][1]["effect"]["evidence"][-1]["quote"].startswith("Correction to event 2")
        confirmed = client.post(f"{base}/{created['id']}/confirm", headers=csrf,
                                json={"expected_revision": draft["revision"]})
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "pending_review"
        assert len(confirmed.json()["proposal_ids"]) == 2
        stale = client.post(f"{base}/{created['id']}/confirm", headers=csrf,
                            json={"expected_revision": draft["revision"]})
        assert stale.status_code == 409
        client.cookies.clear()
        login = client.post("/api/v1/auth/login", json={"username": f"t02super-{suffix}", "password": password})
        assert login.status_code == 200
        refreshed = client.get(f"{base}/{created['id']}").json()
        assert refreshed["status"] == "pending_review"
        assert len(refreshed["proposal_ids"]) == 2
        for activity_id in activity_ids.values():
            with session_factory() as db:
                assert db.get(ActivityState, activity_id).actual_start is None
                assert db.get(ActivityState, activity_id).actual_finish is None
        client.cookies.clear()
        reviewer_login = client.post("/api/v1/auth/login", json={"username": f"t02review-{suffix}", "password": password})
        reviewer_csrf = {"X-CSRF-Token": reviewer_login.json()["csrf_token"]}
        first_id = refreshed["proposal_ids"][0]
        first = client.get(f"/api/v1/proposals/{first_id}").json()
        revision = client.post(f"/api/v1/proposals/{first_id}/revise", headers=reviewer_csrf,
                               json={"expected_proposal_revision": first["revision"],
                                     "chosen_activity_id": first["chosen_activity_id"],
                                     "field_changes": {}, "reason": "Verified the source evidence."})
        assert revision.status_code == 200, revision.text
        current = client.get(f"{base}/{created['id']}")
        assert current.status_code == 404  # reviewer cannot read a supervisor-owned conversation
        client.cookies.clear()
        client.post("/api/v1/auth/login", json={"username": f"t02super-{suffix}", "password": password})
        refreshed = client.get(f"{base}/{created['id']}").json()
        assert refreshed["status"] == "pending_review"
        assert revision.json()["id"] in refreshed["proposal_ids"]
        client.cookies.clear()
        reviewer_login = client.post("/api/v1/auth/login", json={"username": f"t02review-{suffix}", "password": password})
        reviewer_csrf = {"X-CSRF-Token": reviewer_login.json()["csrf_token"]}
        for index, proposal_id in enumerate(refreshed["proposal_ids"]):
            detail = client.get(f"/api/v1/proposals/{proposal_id}").json()
            assert detail["review_state"] == "pending"
            approved = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=reviewer_csrf,
                                   json={"expected_proposal_revision": detail["revision"],
                                         "expected_activity_revision": 0, "idempotency_key": str(uuid4())})
            assert approved.status_code == 200, approved.text
            if index == 0:
                from app.conversation.service import payload
                from app.db.models import Conversation
                with session_factory() as db:
                    assert payload(db, db.get(Conversation, created["id"]))["status"] == "pending_review"
        client.cookies.clear()
        client.post("/api/v1/auth/login", json={"username": f"t02super-{suffix}", "password": password})
        assert client.get(f"{base}/{created['id']}").json()["status"] == "accepted"
        from app.llm.ollama import OllamaError
        def unavailable(**_):
            raise OllamaError("temporary outage")
        monkeypatch.setattr("app.conversation.service._model_call", lambda: unavailable)
        csrf = {"X-CSRF-Token": client.get("/api/v1/auth/me").json()["csrf_token"]}
        failed = client.post(base, headers=csrf).json()
        message = client.post(f"{base}/{failed['id']}/messages", headers=csrf,
                              json={"text": "Started excavation at F-01 at 08:30.",
                                    "report_date": "2026-10-09", "expected_revision": 0})
        assert message.status_code == 200
        assert message.json()["pending_question"] == "retry"
        assert message.json()["turns"][0]["text"] == "Started excavation at F-01 at 08:30."
        retried = client.post(f"{base}/{failed['id']}/retry", headers=csrf,
                              json={"expected_revision": message.json()["revision"]})
        assert retried.status_code == 200
        assert retried.json()["pending_question"] == "retry"
        assert retried.json()["turns"][0]["text"] == "Started excavation at F-01 at 08:30."
