"""Integration tests start from deterministic routing, independent of local rollout.

Tests of hierarchy/model assistance explicitly opt in and inject their adapters.
Do this before application imports so a developer's live .env cannot silently
activate paid orchestration during the database suite.
"""

import os
import sys

import pytest
from sqlalchemy.engine import make_url

from app.settings import get_settings

os.environ["AGENT_HIERARCHY_ENABLED"] = "false"
os.environ["ORCHESTRATOR_MODEL_ASSISTED"] = "false"
# Embedded pytest callers (for example after an Alembic migration) may already
# have cached the developer's rollout flags. Re-read only the test environment.
get_settings.cache_clear()
_settings = get_settings()
_url = make_url(_settings.database_url)
if _url.host not in {"127.0.0.1", "localhost", "::1"} or not (
    _url.database == "progress_test" or (_url.database or "").startswith("progress_rehearsal_")
):
    raise RuntimeError("Integration tests require an explicit isolated DATABASE_URL")
_loaded = sys.modules.get("app.db.session")
if _loaded is not None and _loaded.engine.url != _url:
    raise RuntimeError(
        "Restart integration tests with the isolated database configured before imports"
    )


@pytest.fixture(autouse=True)
def block_uninjected_provider_http(monkeypatch):
    """All integration model responses must use an explicit test transport."""
    from app.llm import hosted

    def blocked(*args, **kwargs):
        raise AssertionError("Provider HTTP is disabled in integration tests; inject a transport")

    monkeypatch.setattr(hosted, "urlopen", blocked)
