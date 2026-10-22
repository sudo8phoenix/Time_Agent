"""Explicit isolated infrastructure for authentication tests."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.models import LoginThrottleBucket
from app.security.login_limiter import SharedLoginLimiter


@pytest.fixture
def shared_login_limiter(tmp_path, monkeypatch):
    from app.api.endpoints import auth
    engine = create_engine(f'sqlite:///{tmp_path / "login.sqlite"}',
                           connect_args={'check_same_thread': False, 'timeout': 10})
    LoginThrottleBucket.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    limiter = SharedLoginLimiter(factory, 'unit-test-secret')
    monkeypatch.setattr(auth, 'login_limiter', limiter)
    yield limiter
    engine.dispose()


@pytest.fixture(autouse=True)
def local_parser_service_transport(monkeypatch):
    """Unit tests exercise fixed dispatch locally; Docker confinement has its own suite."""
    from app.ingest import parser_service, report_parser
    from app.ingest.native_schedule import runner
    def request(payload, **kwargs):
        try:
            result = parser_service.dispatch(payload)
            return {'ok': True, 'result': result, 'error': None}
        except runner.ParserRuntimeError as exc:
            return {'ok': False, 'result': None, 'error': exc.code}
        except (ValueError, TypeError, KeyError) as exc:
            return {'ok': False, 'result': None, 'error': report_parser._safe_error(str(exc))}
    monkeypatch.setattr(report_parser, 'request_parser', request)
    monkeypatch.setattr(runner, 'request_parser', request)
