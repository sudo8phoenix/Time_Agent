"""PostgreSQL flow through a small real-project Cambridge snapshot."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.agent.schedule_decision import shortlist_activities
from app.db.models import Activity, Project, ScheduleSourceMetadata, User
from app.db.passwords import hash_password
from app.db.session import engine, get_session
from app.main import app
from app.settings import get_settings

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT.parent / "data/cambridge -construction schedules/JPF_Anonymised_Project_Data.json"
PROJECT_ID = "5060"  # 1,496 source activities; derived snapshot is below the upload limit.


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


def _login(browser, factory):
    username = f"cambridge-{uuid4().hex}"
    db = factory()
    db.add(User(username=username, password_hash=hash_password("test-password"), role="reviewer"))
    db.commit()
    db.close()
    response = browser.post("/api/v1/auth/login", json={"username": username, "password": "test-password"})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_real_cambridge_snapshot_upload_select_map_stage_activate_retrieve(client, tmp_path):
    if not SOURCE.is_file():
        pytest.skip("Cambridge source dataset is not available in this checkout")
    snapshot = tmp_path / "cambridge-5060.json"
    prepared = subprocess.run([sys.executable, str(ROOT / "ops/prepare_cambridge_import.py"),
                               str(SOURCE), PROJECT_ID, str(snapshot)], cwd=ROOT,
                              capture_output=True, text=True, check=True, timeout=300)
    provenance = json.loads(prepared.stdout)
    assert provenance["snapshot_bytes"] < 10 * 1024 * 1024
    browser, factory = client
    headers = _login(browser, factory)
    project = browser.post("/api/v1/projects", json={"name": f"Cambridge test {uuid4().hex}",
                               "timezone": "Asia/Kolkata"}, headers=headers)
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    upload = browser.post(f"/api/v1/projects/{project_id}/schedule-imports",
        files={"upload": (snapshot.name, snapshot.read_bytes(), "application/json")}, headers=headers)
    assert upload.status_code == 201, upload.text
    record = upload.json()
    assert record["source_format"] == "cambridge_json"
    selected = browser.post(f"/api/v1/projects/{project_id}/schedule-imports/{record['id']}/select-project",
        json={"expected_revision": record["revision"], "source_project_id": PROJECT_ID}, headers=headers)
    assert selected.status_code == 200, selected.text
    preview = selected.json()["preview"]
    assert preview["selected_project_id"] == PROJECT_ID and preview["tasks"]
    mapping = {"baseline_date": "2026-10-01", "source_project_id": PROJECT_ID,
               "task_overrides": {}, "reason": "test evidence: map real-derived Cambridge snapshot"}
    mapped = browser.post(f"/api/v1/projects/{project_id}/schedule-imports/{record['id']}/mapping",
        json={"expected_revision": selected.json()["revision"], "mapping": mapping}, headers=headers)
    assert mapped.status_code == 200, mapped.text
    staged = browser.post(f"/api/v1/projects/{project_id}/schedule-imports/{record['id']}/stage",
        json={"expected_revision": mapped.json()["revision"]}, headers=headers)
    assert staged.status_code == 201, staged.text
    assert staged.json()["state"] == "staged"
    db = factory()
    assert db.get(Project, project_id).active_schedule_version_id is None
    db.close()
    activated = browser.post(f"/api/v1/projects/{project_id}/schedules/{staged.json()['version']}/activate",
        json={"expected_active_version": None}, headers=headers)
    assert activated.status_code == 200, activated.text

    db = factory()
    version_id = staged.json()["schedule_version_id"]
    metadata = db.get(ScheduleSourceMetadata, version_id)
    assert metadata.source_metadata["derived_from_parent"] is True
    assert metadata.source_metadata["parent_source_sha256"] == provenance["parent_source_sha256"]
    assert metadata.source_metadata["upstream_identity_verified"] is False
    assert metadata.task_metadata
    assert metadata.relationships
    assert {edge["lag_unit"] for edge in metadata.relationships} == {"unknown_unreviewed"}
    first_id = next(iter(metadata.task_metadata))
    saved_task = metadata.task_metadata[first_id]
    assert saved_task["source_task_id"] == first_id
    assert saved_task["source_fields"]["raw_fields"]["Task_ID"] == first_id
    activities = list(db.scalars(select(Activity).where(Activity.schedule_version_id == version_id)))
    db.refresh(db.get(Project, project_id))
    assert db.get(Project, project_id).active_schedule_version_id == UUID(version_id)
    target = next(activity for activity in activities if activity.external_id == first_id)
    for attr, source_key in (("actual_start", "Actual_Start_Date"), ("actual_finish", "Actual_Finish_Date")):
        raw_value = saved_task["source_fields"]["raw_fields"].get(source_key)
        persisted_value = getattr(target, attr)
        assert persisted_value.isoformat() == str(raw_value)[:10] if raw_value else persisted_value is None
    assert browser.get(f"/api/v1/projects/{project_id}/schedule-imports/{record['id']}", headers=headers).status_code == 200
    matches = shortlist_activities({"summary": target.name, "explicit_activity_id": target.external_id},
        version_id, [target], model_call=lambda **_: {"candidate_ids": [str(target.id)]})
    assert matches and matches[0].external_id == first_id
    db.close()
