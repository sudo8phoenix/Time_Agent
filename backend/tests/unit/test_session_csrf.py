from types import SimpleNamespace
from uuid import uuid4
from fastapi import Response
from app.api.endpoints.auth import csrf_for_session, digest, me


def test_session_restore_returns_stable_csrf_without_exposing_cookie():
    token = "private-session-cookie"
    record = SimpleNamespace(csrf_hash=digest("legacy-random-csrf"))
    class Database:
        def get(self, model, key):
            assert key == digest(token)
            return record
        def scalars(self, statement):
            return SimpleNamespace(all=lambda: [])
    user = SimpleNamespace(id=uuid4(), username="reviewer", role="reviewer")
    response = Response()
    restored = me(response, user, token, Database())
    assert restored["csrf_token"] == csrf_for_session(token)
    assert record.csrf_hash == digest(restored["csrf_token"])
    assert restored["csrf_token"] != token
    assert response.headers["cache-control"] == "no-store"
    assert me(Response(), user, token, Database())["csrf_token"] == restored["csrf_token"]
    assert csrf_for_session("another-session") != restored["csrf_token"]


def test_cookie_login_restore_csrf_logout_and_expiry():
    from datetime import datetime, timedelta, timezone
    from fastapi.testclient import TestClient
    from app.db.models import Session
    from app.db.passwords import hash_password
    from app.db.session import get_session
    from app.main import app

    user = SimpleNamespace(id=uuid4(), username="reviewer", role="reviewer", is_active=True, password_hash=hash_password("test-password"))
    records = {}
    class Database:
        def scalar(self, statement):
            return user
        def scalars(self, statement):
            return SimpleNamespace(all=lambda: [])
        def add(self, record):
            record.user = user
            records[record.token_hash] = record
        def get(self, model, key):
            assert model is Session
            return records.get(key)
        def commit(self):
            pass
    def database_session():
        yield Database()
    app.dependency_overrides[get_session] = database_session
    try:
        client = TestClient(app)
        assert client.get("/api/v1/auth/me").status_code == 401
        login = client.post("/api/v1/auth/login", json={"username": "reviewer", "password": "test-password"})
        assert login.status_code == 200
        cookie = login.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=43200" in cookie
        csrf = login.json()["csrf_token"]
        for _ in range(2):
            restored = client.get("/api/v1/auth/me")
            assert restored.status_code == 200
            assert restored.json()["csrf_token"] == csrf
            assert restored.headers["cache-control"] == "no-store"
        assert client.post("/api/v1/auth/logout").status_code == 403
        assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401
        client.post("/api/v1/auth/login", json={"username": "reviewer", "password": "test-password"})
        token = client.cookies.get("progress_session")
        records[digest(token)].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert client.get("/api/v1/auth/me").status_code == 401
        records[digest(token)].expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        user.is_active = False
        assert client.get("/api/v1/auth/me").status_code == 401
    finally:
        app.dependency_overrides.pop(get_session, None)
