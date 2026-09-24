from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db.models import Activity, ActivityState, Project, ScheduleVersion, User
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
    factory = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")

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


def _auth(client, factory):
    username = f"schedule-reviewer-{uuid4().hex}"
    db = factory()
    db.add(User(username=username, password_hash=hash_password("test-password"), role="reviewer"))
    db.commit()
    db.close()
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "test-password"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _project(client, headers):
    response = client.post("/api/v1/projects", json={"name": f"Safety {uuid4().hex}", "timezone": "Asia/Kolkata"}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def _upload(client, project_id, headers, raw):
    return client.post(f"/api/v1/projects/{project_id}/schedules", files={"upload": ("schedule.csv", raw, "text/csv")}, headers=headers)


def test_invalid_schedule_reports_all_errors_and_creates_no_stage(client):
    browser, factory = client
    headers = _auth(browser, factory)
    project_id = _project(browser, headers)
    raw = SCHEDULE.read_bytes().replace(b"PIP-A-ERECT-024", b"PIP-A-WELD-024", 1).replace(b"2026-09-19", b"not-a-date", 1)
    response = _upload(browser, project_id, headers, raw)
    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert any(error["field"] == "activity_id" and "duplicate" in error["message"] for error in errors)
    assert any(error["field"] == "planned_start" for error in errors)
    db = factory()
    project = db.get(Project, project_id)
    assert project.schedule_versions == []
    assert db.query(ScheduleVersion).filter(ScheduleVersion.project_id == project_id).count() == 0
    db.close()


def test_exact_duplicate_bytes_reuse_stage_and_preserve_leading_zero_id(client):
    browser, factory = client
    headers = _auth(browser, factory)
    project_id = _project(browser, headers)
    raw = SCHEDULE.read_bytes().replace(b"PIP-A-ERECT-024", b"000024", 1)
    first = _upload(browser, project_id, headers, raw)
    second = _upload(browser, project_id, headers, raw)
    assert first.status_code == second.status_code == 200
    assert first.json()["existing"] is False
    assert second.json()["existing"] is True
    assert first.json()["id"] == second.json()["id"]
    db = factory()
    version = db.get(ScheduleVersion, first.json()["id"])
    assert db.query(ScheduleVersion).filter(ScheduleVersion.project_id == project_id).count() == 1
    assert db.query(Activity).filter(Activity.schedule_version_id == version.id, Activity.external_id == "000024").count() == 1
    db.close()


def test_activation_rejects_wrong_expected_version_and_rebase_after_approval(client):
    browser, factory = client
    headers = _auth(browser, factory)
    project_id = _project(browser, headers)
    first = _upload(browser, project_id, headers, SCHEDULE.read_bytes())
    second = _upload(browser, project_id, headers, SCHEDULE.read_bytes().replace(b"PIP-A-ERECT-024", b"PIP-A-ERECT-999", 1))
    assert first.status_code == second.status_code == 200
    assert browser.post(f"/api/v1/projects/{project_id}/schedules/1/activate", json={"expected_active_version": 99}, headers=headers).json()["detail"]["code"] == "SCHEDULE_VERSION_CONFLICT"
    active = browser.post(f"/api/v1/projects/{project_id}/schedules/1/activate", json={"expected_active_version": None}, headers=headers)
    assert active.status_code == 200
    db = factory()
    version = db.query(ScheduleVersion).filter(ScheduleVersion.project_id == project_id, ScheduleVersion.version_number == 1).one()
    activity = db.query(Activity).filter(Activity.schedule_version_id == version.id).first()
    db.add(ActivityState(activity_id=activity.id, revision=1, observed_status="in_progress"))
    db.commit()
    db.close()
    rebase = browser.post(f"/api/v1/projects/{project_id}/schedules/2/activate", json={"expected_active_version": 1}, headers=headers)
    assert rebase.status_code == 409
    assert rebase.json()["detail"]["code"] == "SCHEDULE_REBASE_REQUIRED"
    db = factory()
    project = db.get(Project, project_id)
    assert project.active_schedule_version_id == version.id
    assert db.get(ActivityState, activity.id).revision == 1
    db.close()
