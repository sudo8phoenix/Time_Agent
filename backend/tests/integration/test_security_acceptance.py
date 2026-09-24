"""Session lifecycle and project-scope acceptance checks."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import sessionmaker

from app.db.models import Project, ProjectMembership, Session, User
from app.db.passwords import hash_password
from app.db.session import engine, get_session
from app.main import app


@pytest.fixture
def secured_client():
    connection = engine.connect()
    outer = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")

    def database_session():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_session] = database_session
    user = User(username=f"security-{uuid4().hex}", password_hash=hash_password("acceptance-password"), role="reviewer")
    owned = Project(name=f"owned-{uuid4().hex}", timezone="UTC")
    foreign = Project(name=f"foreign-{uuid4().hex}", timezone="UTC")
    db = factory()
    db.add_all([user, owned, foreign])
    db.flush()
    db.add(ProjectMembership(project_id=owned.id, user_id=user.id))
    db.commit()
    ids = (user.id, owned.id, foreign.id)
    db.close()
    try:
        yield TestClient(app), factory, ids
    finally:
        app.dependency_overrides.clear()
        outer.rollback()
        connection.close()


def test_expired_and_revoked_sessions_are_rejected_and_project_scope_is_enforced(secured_client):
    client, factory, (user_id, owned_id, foreign_id) = secured_client
    lookup = factory()
    username = lookup.get(User, user_id).username
    lookup.close()
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "acceptance-password"})
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    assert client.get("/api/v1/auth/me").status_code == 200

    visible = client.get("/api/v1/projects")
    assert visible.status_code == 200
    assert [row["id"] for row in visible.json()["items"]] == [str(owned_id)]
    assert client.get(f"/api/v1/projects/{foreign_id}/progress").status_code == 403

    token = client.cookies.get("progress_session")
    session_hash = __import__("hashlib").sha256(token.encode()).hexdigest()
    db = factory()
    db.execute(update(Session).where(Session.token_hash == session_hash).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    db.commit()
    db.close()
    assert client.get("/api/v1/auth/me").status_code == 401

    # A new login creates a live token, then logout revokes it server-side.
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "acceptance-password"})
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
