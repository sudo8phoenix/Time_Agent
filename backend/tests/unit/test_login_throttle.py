from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response

from app.api.endpoints.auth import LoginRequest, _login_failures, login


def test_login_limits_repeated_failures():
    request = SimpleNamespace(client=SimpleNamespace(host="test-throttle"))
    database = SimpleNamespace(scalar=lambda statement: None)
    body = LoginRequest(username="test-throttle", password="incorrect")
    _login_failures.clear()
    try:
        for _ in range(5):
            with pytest.raises(HTTPException) as error:
                login(body, Response(), request, database)
            assert error.value.status_code == 401
        with pytest.raises(HTTPException) as error:
            login(body, Response(), request, database)
        assert error.value.status_code == 429
    finally:
        _login_failures.clear()
