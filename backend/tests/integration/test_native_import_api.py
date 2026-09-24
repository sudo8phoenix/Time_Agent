from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db.models import User
from app.db.passwords import hash_password
from app.db.session import engine, get_session
from app.main import app
from app.settings import get_settings


ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def client(tmp_path, monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
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


def test_reviewer_can_upload_map_and_stage_native_import(client):
    browser, factory = client
    session = factory()
    username = f"native-api-{uuid4().hex}"
    session.add(
        User(username=username, password_hash=hash_password("test-password"), role="reviewer")
    )
    session.commit()
    session.close()
    login = browser.post(
        "/api/v1/auth/login", json={"username": username, "password": "test-password"}
    )
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    project = browser.post(
        "/api/v1/projects",
        json={"name": f"Native {uuid4().hex}", "timezone": "Asia/Kolkata"},
        headers=headers,
    ).json()
    raw = (ROOT / "PROJECT.xer").read_bytes()
    created = browser.post(
        f"/api/v1/projects/{project['id']}/schedule-imports",
        files={"upload": ("PROJECT.xer", raw, "application/octet-stream")},
        headers=headers,
    )
    assert created.status_code == 201, created.json()
    record = created.json()
    assert record["state"] == "needs_mapping"
    mapping = {
        "baseline_date": "2026-09-19",
        "source_project_id": "4507",
        "task_overrides": {},
        "reason": "human_confirmed: matching-only import",
    }
    mapped = browser.post(
        f"/api/v1/projects/{project['id']}/schedule-imports/{record['id']}/mapping",
        json={"expected_revision": record["revision"], "mapping": mapping},
        headers=headers,
    )
    assert mapped.status_code == 200, mapped.json()
    staged = browser.post(
        f"/api/v1/projects/{project['id']}/schedule-imports/{record['id']}/stage",
        json={"expected_revision": mapped.json()["revision"]},
        headers=headers,
    )
    assert staged.status_code == 201, staged.json()
    assert staged.json()["state"] == "staged"
    assert staged.json()["schedule_version_id"]
