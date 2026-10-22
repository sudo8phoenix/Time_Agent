from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response

from app.api.endpoints.auth import LoginRequest, login
from app.security.login_limiter import LoginLimited


def test_login_limits_repeated_failures():
    request = SimpleNamespace(client=SimpleNamespace(host="test-throttle"))
    database = SimpleNamespace(scalar=lambda statement: None)
    body = LoginRequest(username="test-throttle", password="incorrect")
    for _ in range(5):
        with pytest.raises(HTTPException) as error:
            login(body, Response(), request, database)
        assert error.value.status_code == 401
    with pytest.raises(HTTPException) as error:
        login(body, Response(), request, database)
    assert error.value.status_code == 429


pytestmark = pytest.mark.usefixtures("shared_login_limiter")


def test_account_limit_survives_changing_ip_addresses(shared_login_limiter):
    reserve_login_attempt = shared_login_limiter.reserve

    for index in range(5):
        reserve_login_attempt(f"host-{index}", "target")
    with pytest.raises(LoginLimited) as error:
        reserve_login_attempt("another-host", "TARGET")
    assert error.value.retry_after > 0


def test_ip_limit_survives_changing_usernames(shared_login_limiter):
    from app.security.login_limiter import MAX_IP_ATTEMPTS as LOGIN_MAX_IP_ATTEMPTS
    reserve_login_attempt = shared_login_limiter.reserve

    for index in range(LOGIN_MAX_IP_ATTEMPTS):
        reserve_login_attempt("same-host", f"user-{index}")
    with pytest.raises(LoginLimited) as error:
        reserve_login_attempt("same-host", "another-user")
    assert error.value.retry_after > 0


def test_parallel_logins_are_limited_before_password_verification(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock
    from app.api.endpoints import auth

    release = Event()
    five_checks_started = Event()
    counter_lock = Lock()
    started = 0

    def verify(password, encoded):
        nonlocal started
        with counter_lock:
            started += 1
            if started == 5:
                five_checks_started.set()
        assert release.wait(timeout=10)
        return False

    monkeypatch.setattr(auth, "verify_password", verify)
    request = SimpleNamespace(client=SimpleNamespace(host="concurrent-host"))
    database = SimpleNamespace(scalar=lambda statement: None)
    body = LoginRequest(username="parallel-target", password="incorrect")

    def attempt():
        try:
            login(body, Response(), request, database)
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(attempt) for _ in range(12)]
        try:
            assert five_checks_started.wait(timeout=10)
        finally:
            release.set()
        results = [future.result(timeout=10) for future in futures]
    assert results.count(401) == 5
    assert results.count(429) == 7
    assert started == 5


def test_capacity_does_not_evict_active_limits(monkeypatch, shared_login_limiter):
    from app.security import login_limiter
    from app.db.models import LoginThrottleBucket
    from sqlalchemy import select
    monkeypatch.setattr(login_limiter, 'MAX_BUCKETS', 2)
    shared_login_limiter.reserve("host", "first-user")
    with pytest.raises(LoginLimited):
        shared_login_limiter.reserve("host", "second-user")
    with shared_login_limiter.session_factory() as db:
        assert len(db.scalars(select(LoginThrottleBucket)).all()) == 2


def test_expired_limits_allow_login_again(shared_login_limiter):
    from datetime import datetime, timedelta, timezone
    from app.db.models import LoginThrottleBucket
    from sqlalchemy import update
    for _ in range(5):
        shared_login_limiter.reserve("host", "user")
    with shared_login_limiter.session_factory() as db, db.begin():
        db.execute(update(LoginThrottleBucket).values(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    shared_login_limiter.reserve("host", "user")


def test_unknown_user_still_performs_password_verification(monkeypatch):
    from app.api.endpoints import auth

    checked = []
    monkeypatch.setattr(auth, "verify_password", lambda password, encoded: checked.append(encoded) or False)
    with pytest.raises(HTTPException) as error:
        login(
            LoginRequest(username="unknown", password="incorrect"), Response(),
            SimpleNamespace(client=SimpleNamespace(host="host")),
            SimpleNamespace(scalar=lambda statement: None),
        )
    assert error.value.status_code == 401
    assert checked == [auth._dummy_password_hash]


def test_success_preserves_other_failures_and_ip_attempts(monkeypatch, shared_login_limiter):
    from app.api.endpoints import auth
    from app.db.models import LoginThrottleBucket
    from sqlalchemy import select
    for _ in range(3):
        shared_login_limiter.reserve("host", "user")
    user = SimpleNamespace(password_hash="encoded")
    monkeypatch.setattr(auth, "verify_password", lambda password, encoded: True)
    monkeypatch.setattr(auth, "create_session", lambda *args: {"ok": True})
    assert login(
        LoginRequest(username="user", password="correct"), Response(),
        SimpleNamespace(client=SimpleNamespace(host="host")),
        SimpleNamespace(scalar=lambda statement: user),
    ) == {"ok": True}
    with shared_login_limiter.session_factory() as db:
        assert sorted(db.scalars(select(LoginThrottleBucket.attempts)).all()) == [3, 4]


def test_independent_workers_share_limits_and_restart_does_not_clear_them(shared_login_limiter):
    from app.security.login_limiter import SharedLoginLimiter
    first = shared_login_limiter
    for index in range(5):
        worker = SharedLoginLimiter(first.session_factory, 'unit-test-secret')
        worker.reserve(f'host-{index}', 'same-account')
    with pytest.raises(LoginLimited):
        SharedLoginLimiter(first.session_factory, 'unit-test-secret').reserve('new-host', 'same-account')


def test_database_failure_fails_closed_without_cookie(monkeypatch):
    from app.api.endpoints import auth
    from app.security.login_limiter import SharedLoginLimiter
    from sqlalchemy.exc import OperationalError
    def unavailable():
        raise OperationalError('PRIVATE DATABASE CONNECTION', {}, Exception('SECRET'))
    monkeypatch.setattr(auth, 'login_limiter', SharedLoginLimiter(unavailable, 'secret'))
    response = Response()
    with pytest.raises(HTTPException) as error:
        login(LoginRequest(username='user', password='password'), response,
              SimpleNamespace(client=SimpleNamespace(host='host')), object())
    assert error.value.status_code == 503
    assert 'PRIVATE' not in error.value.detail
    assert 'set-cookie' not in response.headers
