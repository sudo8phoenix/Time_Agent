"""Integration entrypoint must not inherit live flags, database or provider HTTP."""

from pathlib import Path
import os
import runpy
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url
from app.settings import get_settings

CONFTEXT = Path(__file__).parents[1] / "integration/conftest.py"
TEST_URL = "postgresql+psycopg://fixture:fixture@127.0.0.1/progress_rehearsal_guard"


@pytest.fixture(autouse=True)
def clear_settings(monkeypatch):
    for name in ("AGENT_HIERARCHY_ENABLED", "ORCHESTRATOR_MODEL_ASSISTED"):
        monkeypatch.setenv(name, os.environ.get(name, "false"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_cached_live_flags_are_cleared_before_integration_imports(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.setenv("AGENT_HIERARCHY_ENABLED", "true")
    monkeypatch.setenv("ORCHESTRATOR_MODEL_ASSISTED", "true")
    monkeypatch.setitem(
        sys.modules,
        "app.db.session",
        SimpleNamespace(engine=SimpleNamespace(url=make_url(TEST_URL))),
    )
    assert get_settings().orchestrator_model_assisted
    namespace = runpy.run_path(str(CONFTEXT))
    assert not namespace["_settings"].agent_hierarchy_enabled
    assert not namespace["_settings"].orchestrator_model_assisted


def test_application_database_is_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://fixture:fixture@127.0.0.1/progress")
    with pytest.raises(RuntimeError, match="explicit isolated DATABASE_URL"):
        runpy.run_path(str(CONFTEXT))


def test_already_loaded_wrong_database_engine_is_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    wrong = make_url(TEST_URL).set(database="progress")
    monkeypatch.setitem(
        sys.modules, "app.db.session", SimpleNamespace(engine=SimpleNamespace(url=wrong))
    )
    with pytest.raises(RuntimeError, match="before imports"):
        runpy.run_path(str(CONFTEXT))


def test_uninjected_provider_http_is_blocked(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.setitem(
        sys.modules,
        "app.db.session",
        SimpleNamespace(engine=SimpleNamespace(url=make_url(TEST_URL))),
    )
    namespace = runpy.run_path(str(CONFTEXT))
    namespace["block_uninjected_provider_http"].__wrapped__(monkeypatch)
    from app.llm import hosted

    with pytest.raises(AssertionError, match="Provider HTTP is disabled"):
        hosted.urlopen("https://api.groq.com/openai/v1/chat/completions")
