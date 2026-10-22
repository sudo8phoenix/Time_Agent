"""Real PostgreSQL transactions and independent processes share login admission."""
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
import multiprocessing
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, update
from sqlalchemy.orm import sessionmaker

from app.db.models import LoginThrottleBucket
from app.security.login_limiter import LoginLimited, SharedLoginLimiter
from app.settings import get_settings


def reserve_in_process(arguments):
    url, secret, host = arguments
    engine = create_engine(url)
    try:
        limiter = SharedLoginLimiter(sessionmaker(engine), secret)
        try:
            limiter.reserve(host, 'target')
            return 'admitted'
        except LoginLimited:
            return 'limited'
    finally:
        engine.dispose()


@pytest.fixture
def limiter():
    engine = create_engine(get_settings().database_url)
    secret = f'test-login-{uuid4()}'
    instance = SharedLoginLimiter(sessionmaker(engine), secret)
    yield instance
    # Delete only this test's HMAC-namespaced keys.
    keys = [instance._key('account', 'target')]
    keys += [instance._key('ip', f'host-{i}') for i in range(20)]
    with engine.begin() as connection:
        connection.execute(delete(LoginThrottleBucket).where(LoginThrottleBucket.key_hash.in_(keys)))
    engine.dispose()


def test_independent_api_processes_cannot_over_admit(limiter):
    url = get_settings().database_url
    arguments = [(url, limiter.secret.decode(), f'host-{i}') for i in range(20)]
    with ProcessPoolExecutor(max_workers=8, mp_context=multiprocessing.get_context('spawn')) as executor:
        results = list(executor.map(reserve_in_process, arguments))
    assert results.count('admitted') == 5
    assert results.count('limited') == 15
    # A new process/limiter after the first workers exit sees the committed state.
    assert reserve_in_process((url, limiter.secret.decode(), 'host-19')) == 'limited'


def test_stale_success_cannot_release_a_new_window(limiter):
    old = limiter.reserve('host-0', 'target')
    with limiter.session_factory() as db, db.begin():
        db.execute(update(LoginThrottleBucket).where(
            LoginThrottleBucket.key_hash == old.account_key,
        ).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    current = limiter.reserve('host-0', 'target')
    assert current.expires_at != old.expires_at
    limiter.release_success(old)
    with limiter.session_factory() as db:
        assert db.get(LoginThrottleBucket, current.account_key).attempts == 1


def test_failed_request_rollback_does_not_undo_admission(limiter):
    from types import SimpleNamespace
    from fastapi import HTTPException, Response
    from app.api.endpoints import auth
    from unittest.mock import patch
    request = SimpleNamespace(client=SimpleNamespace(host='host-0'))
    with patch.object(auth, 'login_limiter', limiter):
        for _ in range(5):
            with limiter.session_factory() as request_db:
                with pytest.raises(HTTPException) as error:
                    auth.login(auth.LoginRequest(username='target', password='wrong'),
                               Response(), request, request_db)
                assert error.value.status_code == 401
                request_db.rollback()
    with pytest.raises(LoginLimited):
        limiter.reserve('host-1', 'target')
