"""PostgreSQL-backed checks for the authenticated intake workflow.

The test joins one outer transaction and rolls it back afterwards, so it leaves
the developer database unchanged while still exercising PostgreSQL constraints.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db.models import Activity, Fragment, Job, Observation, Proposal, User
from app.db.passwords import hash_password
from app.db.session import engine, get_session
from app.main import app
from app.settings import get_settings


ROOT = Path(__file__).resolve().parents[3]
SCHEDULE = ROOT / "data/synthetic/schedules/demo-utility-01.csv"


@pytest.fixture
def client(tmp_path, monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    def database_session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    app.dependency_overrides[get_session] = database_session
    try:
        yield TestClient(app), factory
    finally:
        app.dependency_overrides.clear()
        transaction.rollback()
        connection.close()


def _login(client: TestClient, factory) -> tuple[dict[str, str], str]:
    username = f"integration-reviewer-{uuid4().hex}"
    session = factory()
    session.add(User(username=username, password_hash=hash_password("test-password"), role="reviewer"))
    session.commit()
    session.close()
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "test-password"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}, username


def test_postgres_authenticated_schedule_and_report_idempotency(client):
    browser, factory = client
    headers, _ = _login(browser, factory)

    project_response = browser.post(
        "/api/v1/projects", json={"name": f"Integration {uuid4().hex}", "timezone": "Asia/Kolkata"}, headers=headers
    )
    assert project_response.status_code == 201
    project = project_response.json()
    project_id = project["id"]

    projects = browser.get("/api/v1/projects")
    assert projects.status_code == 200
    assert [item["id"] for item in projects.json()["items"]] == [project_id]

    schedule_response = browser.post(
        f"/api/v1/projects/{project_id}/schedules",
        files={"upload": ("demo-utility-01.csv", SCHEDULE.read_bytes(), "text/csv")},
        headers=headers,
    )
    assert schedule_response.status_code == 200
    assert schedule_response.json()["activity_count"] == 12

    activation = browser.post(
        f"/api/v1/projects/{project_id}/schedules/1/activate",
        json={"expected_active_version": None},
        headers=headers,
    )
    assert activation.status_code == 200

    payload = {"text": "Area A: erected 3 spools on line 24-XX.", "report_date": "2026-09-21"}
    first = browser.post(f"/api/v1/projects/{project_id}/reports", json=payload, headers=headers)
    assert first.status_code == 202
    assert first.json()["existing"] is False
    job_id = first.json()["job_id"]

    retry = browser.post(f"/api/v1/projects/{project_id}/reports", json=payload, headers=headers)
    assert retry.status_code == 202
    assert retry.json()["existing"] is True
    assert retry.json()["job_id"] == job_id

    job = browser.get(f"/api/v1/jobs/{job_id}")
    assert job.status_code == 200
    assert job.json()["state"] == "queued"

    session = factory()
    queued_job = session.get(Job, job_id)
    fragment = session.query(Fragment).filter(Fragment.report_id == queued_job.report_id).one()
    activity = session.query(Activity).filter(
        Activity.schedule_version_id == queued_job.schedule_version_id,
        Activity.work_type == "pipe_spool_erection",
    ).first()
    assert activity is not None
    observation = Observation(
        job_id=queued_job.id,
        fragment_id=fragment.id,
        ordinal=1,
        fields={
            "summary": "Three spools erected on line 24-XX.",
            "quantity": "3",
            "unit": "spool",
            "work_type": "pipe_spool_erection",
            "area": "AREA-A",
            "asset_tags": ["24-XX"],
            "event_type": "actual_progress",
            "evidence": [{"fragment_id": str(fragment.id), "quote": "Area A: erected 3 spools on line 24-XX."}],
        },
        field_evidence={},
    )
    session.add(observation)
    session.flush()
    proposal = Proposal(
        observation_id=observation.id,
        revision=1,
        project_id=queued_job.project_id,
        chosen_activity_id=activity.id,
        candidates=[{"candidate_id": str(activity.id), "activity_name": activity.name, "area": activity.area, "work_type": activity.work_type, "is_leaf": True, "retrieval_rank": 1}],
        mapping_state="suggested",
        match_strength="review",
        review_state="pending",
        warnings=[],
        proposed_effects={"quantity": "3", "unit": "spool", "quantity_semantics": "delta", "event_type": "actual_progress", "effective_date": "2026-09-21"},
    )
    session.add(proposal)
    session.commit()
    session.close()

    review = browser.get(f"/api/v1/proposals/{proposal.id}", headers=headers)
    assert review.status_code == 200
    assert review.json()["evidence"][0]["locator"] == "paragraph:1"
    assert review.json()["current_activity_revision"] == 0
    approval = {"expected_proposal_revision": 1, "expected_activity_revision": 0, "idempotency_key": f"approve-{uuid4().hex}", "resolution_notes": "Evidence checked."}
    approved = browser.post(f"/api/v1/proposals/{proposal.id}/approve", json=approval, headers=headers)
    assert approved.status_code == 200, approved.json()
    assert approved.json()["state_revision"] == 1
    repeated = browser.post(f"/api/v1/proposals/{proposal.id}/approve", json=approval, headers=headers)
    assert repeated.status_code == 200
    assert repeated.json() == approved.json()

    progress = browser.get(f"/api/v1/projects/{project_id}/progress")
    assert progress.status_code == 200
    assert progress.json()["counts"] == {"activities": 12, "approved_events": 1, "pending_review": 0}
    approved_activity = next(item for item in progress.json()["items"] if item["external_id"] == activity.external_id)
    assert approved_activity["completed_quantity"] == "3.0000"
    assert approved_activity["history"][0]["source_locator"] == "paragraph:1"

    exported = browser.get(f"/api/v1/projects/{project_id}/exports/approved.csv")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert activity.external_id in exported.text
    assert "project_name,project_id,schedule_version" in exported.text


def test_postgres_rejects_unauthenticated_mutation_and_viewer_mutation(client):
    browser, factory = client
    assert browser.post("/api/v1/projects", json={"name": "No session"}).status_code == 401

    username = f"integration-viewer-{uuid4().hex}"
    session = factory()
    session.add(User(username=username, password_hash=hash_password("test-password"), role="viewer"))
    session.commit()
    session.close()
    login = browser.post("/api/v1/auth/login", json={"username": username, "password": "test-password"})
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    assert browser.post("/api/v1/projects", json={"name": "Viewer cannot create"}, headers={"X-CSRF-Token": csrf}).status_code == 403
