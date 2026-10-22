from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.settings import Settings


def test_disabled_registration_rejects_before_database_writes(monkeypatch):
    from app.api.endpoints import auth

    monkeypatch.setattr(auth, "get_settings", lambda: Settings(
        _env_file=None, environment="production",
        secret_key="test-only-production-secret-with-32-characters",
        registration_enabled=None,
    ))

    # Any attempt to query or write through this session fails the test.
    app.dependency_overrides[get_session] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/auth/register", json={
                "username": "blocked-reviewer", "password": "correct horse battery",
            })
        assert response.status_code == 403
        assert "set-cookie" not in response.headers
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_registration_creates_private_workspace_and_restores_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)

    def database_session():
        with sessions() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[get_session] = database_session
    try:
        with TestClient(app) as alice, TestClient(app) as bob:
            a = alice.post("/api/v1/auth/register", json={"username": "alice", "password": "correct horse battery"})
            assert a.status_code == 201
            assert a.json()["user"]["role"] == "reviewer"
            assert alice.get("/api/v1/auth/me").status_code == 200
            projects = alice.get("/api/v1/projects").json()["items"]
            assert len(projects) == 1
            assert alice.post("/api/v1/auth/register", json={"username": "alice", "password": "another long password"}).status_code == 409
            assert bob.post("/api/v1/auth/register", json={"username": "bob", "password": "another long password"}).status_code == 201
            bob_projects = bob.get("/api/v1/projects").json()["items"]
            assert len(bob_projects) == 1
            assert bob_projects[0]["id"] != projects[0]["id"]
            assert alice.get("/api/v1/projects").json()["items"] == projects
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()
