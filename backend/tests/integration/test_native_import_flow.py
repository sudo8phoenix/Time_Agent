"""W-30: real-parser/PostgreSQL native-import acceptance coverage.

These tests deliberately use the checked-in source bytes.  They exercise the
application routes and persistence layer; parser outage checks below are only
bounded dependency injection, not evidence of a native format.
"""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.models import Activity, ActivityState, ScheduleSourceMetadata, User
from app.db.passwords import hash_password
from app.db.session import engine, get_session
from app.ingest.native_schedule.runner import ParserRuntimeError
from app.main import app
from app.agent.schedule_decision import shortlist_activities
from app.settings import get_settings


ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT.parent
FIXTURES = ROOT / "backend/tests/fixtures/native_schedule"


@pytest.fixture
def client(tmp_path, monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))

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

    app.dependency_overrides[get_session] = database_session
    try:
        yield TestClient(app), factory
    finally:
        app.dependency_overrides.clear()
        transaction.rollback()
        connection.close()


def _login(browser, factory, role="reviewer"):
    username = f"w30-{uuid4().hex}"
    db = factory()
    db.add(User(username=username, password_hash=hash_password("test-password"), role=role))
    db.commit()
    db.close()
    response = browser.post("/api/v1/auth/login", json={"username": username, "password": "test-password"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _project(browser, headers):
    response = browser.post("/api/v1/projects", json={"name": f"W30 {uuid4().hex}", "timezone": "Asia/Kolkata"}, headers=headers)
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def _upload(browser, project_id, headers, path):
    return browser.post(
        f"/api/v1/projects/{project_id}/schedule-imports",
        files={"upload": (path.name, path.read_bytes(), "application/octet-stream")},
        headers=headers,
    )


@pytest.mark.parametrize(
    ("path", "format_name", "expected_external_id", "expected_source_id"),
    [
        (WORKSPACE / "PROJECT.xer", "p6_xer", "1.1", "101717"),
        (FIXTURES / "tiny_p6.xml", "p6_xml", "00024", "24"),
        (FIXTURES / "tiny_mspdi.xml", "msp_xml", "24", "24"),
        (FIXTURES / "public_sample.mpp", "msp_mpp", "86", "86"),
    ],
)
def test_each_native_format_real_parser_maps_stages_activates_and_retrieves(
    client, path, format_name, expected_external_id, expected_source_id
):
    browser, factory = client
    headers = _login(browser, factory)
    project_id = _project(browser, headers)
    created = _upload(browser, project_id, headers, path)
    assert created.status_code == 201, created.json()
    record = created.json()
    assert record["source_format"] == format_name
    assert record["state"] == "needs_mapping"
    preview = record["preview"]
    task = next(task for task in preview["tasks"] if task["external_id"] == expected_external_id)
    assert task["source_task_id"] == expected_source_id
    assert preview["wbs"]
    assert preview["relationships"]

    mapping = {
        "baseline_date": "2026-09-19",
        "source_project_id": preview["selected_project_id"],
        "task_overrides": {},
        "reason": "human_confirmed: W-30 matching-only native import",
    }
    mapped = browser.post(f"/api/v1/projects/{project_id}/schedule-imports/{record['id']}/mapping", json={"expected_revision": record["revision"], "mapping": mapping}, headers=headers)
    assert mapped.status_code == 200, mapped.json()
    stale = browser.post(f"/api/v1/projects/{project_id}/schedule-imports/{record['id']}/mapping", json={"expected_revision": record["revision"], "mapping": mapping}, headers=headers)
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "SCHEDULE_IMPORT_CONFLICT"
    staged = browser.post(f"/api/v1/projects/{project_id}/schedule-imports/{record['id']}/stage", json={"expected_revision": mapped.json()["revision"]}, headers=headers)
    assert staged.status_code == 201, staged.json()
    activated = browser.post(f"/api/v1/projects/{project_id}/schedules/{staged.json()['version']}/activate", json={"expected_active_version": None}, headers=headers)
    assert activated.status_code == 200, activated.json()

    db = factory()
    version_id = staged.json()["schedule_version_id"]
    metadata = db.get(ScheduleSourceMetadata, version_id)
    assert str(metadata.schedule_import_id) == record["id"]
    assert metadata.source_project_id == mapping["source_project_id"]
    assert expected_external_id in metadata.task_metadata
    assert metadata.task_metadata[expected_external_id]["source_task_id"] == expected_source_id
    assert metadata.wbs and metadata.relationships
    activities = list(db.scalars(select(Activity).where(Activity.schedule_version_id == version_id)))
    activity = next(activity for activity in activities if activity.external_id == expected_external_id)
    assert activity.measurement_basis == "unsupported"
    result = shortlist_activities(
        {"summary": activity.name, "explicit_activity_id": expected_external_id},
        version_id, activities,
        model_call=lambda **_: {"candidate_ids": [str(activity.id)]},
    )
    assert result and result[0].external_id == expected_external_id
    assert all(candidate.is_leaf for candidate in result)
    db.close()


def test_multisource_selection_duplicate_reuse_access_denial_and_rebase_protection(client):
    browser, factory = client
    headers = _login(browser, factory)
    project_id = _project(browser, headers)
    created = _upload(browser, project_id, headers, FIXTURES / "two_projects.xer")
    assert created.status_code == 201, created.json()
    record = created.json()
    assert record["state"] == "needs_project"
    assert record["preview"]["tasks"] == []
    selected = browser.post(f"/api/v1/projects/{project_id}/schedule-imports/{record['id']}/select-project", json={"expected_revision": record["revision"], "source_project_id": "1"}, headers=headers)
    assert selected.status_code == 200, selected.json()
    assert selected.json()["preview"]["selected_project_id"] == "1"
    assert any(task["external_id"] == "00024" for task in selected.json()["preview"]["tasks"])
    duplicate = _upload(browser, project_id, headers, FIXTURES / "two_projects.xer")
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == record["id"]

    with TestClient(app) as outsider:
        _login(outsider, factory, role="viewer")
        denied = outsider.get(f"/api/v1/projects/{project_id}/schedule-imports/{record['id']}")
        assert denied.status_code == 403

    mapping = {"baseline_date": "2026-09-19", "source_project_id": "1", "task_overrides": {}, "reason": "human_confirmed: selected source"}
    mapped = browser.post(f"/api/v1/projects/{project_id}/schedule-imports/{record['id']}/mapping", json={"expected_revision": selected.json()["revision"], "mapping": mapping}, headers=headers)
    assert mapped.status_code == 200, mapped.json()
    staged = browser.post(f"/api/v1/projects/{project_id}/schedule-imports/{record['id']}/stage", json={"expected_revision": mapped.json()["revision"]}, headers=headers)
    assert staged.status_code == 201, staged.json()
    assert browser.post(f"/api/v1/projects/{project_id}/schedules/{staged.json()['version']}/activate", json={"expected_active_version": None}, headers=headers).status_code == 200
    db = factory()
    active = db.get(Activity, db.scalar(select(Activity.id).where(Activity.schedule_version_id == staged.json()["schedule_version_id"])))
    db.add(ActivityState(activity_id=active.id, revision=1, observed_status="in_progress"))
    db.commit()
    db.close()
    replacement = _upload(browser, project_id, headers, WORKSPACE / "PROJECT.xer").json()
    mapped_replacement = browser.post(f"/api/v1/projects/{project_id}/schedule-imports/{replacement['id']}/mapping", json={"expected_revision": replacement["revision"], "mapping": {"baseline_date": "2026-09-19", "source_project_id": "4507", "task_overrides": {}, "reason": "human_confirmed: replacement"}}, headers=headers)
    assert mapped_replacement.status_code == 200, mapped_replacement.json()
    staged_replacement = browser.post(f"/api/v1/projects/{project_id}/schedule-imports/{replacement['id']}/stage", json={"expected_revision": mapped_replacement.json()["revision"]}, headers=headers)
    assert staged_replacement.status_code == 201, staged_replacement.json()
    rebase = browser.post(f"/api/v1/projects/{project_id}/schedules/{staged_replacement.json()['version']}/activate", json={"expected_active_version": staged.json()["version"]}, headers=headers)
    assert rebase.status_code == 409
    assert rebase.json()["detail"]["code"] == "SCHEDULE_REBASE_REQUIRED"


@pytest.mark.parametrize("code, status", [("SCHEDULE_PARSER_UNAVAILABLE", 503), ("SCHEDULE_PARSE_TIMEOUT", 504)])
def test_parser_failure_statuses_are_bounded_injection_only(client, monkeypatch, code, status):
    browser, factory = client
    headers = _login(browser, factory)
    project_id = _project(browser, headers)
    import app.ingest.native_schedule.storage as storage

    def unavailable(_path, _source_project_id=None):
        raise ParserRuntimeError(code, "injected W-30 parser dependency failure")

    monkeypatch.setattr(storage, "preview_schedule", unavailable)
    response = _upload(browser, project_id, headers, WORKSPACE / "PROJECT.xer")
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
