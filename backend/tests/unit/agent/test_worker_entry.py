from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import ops.run_worker as worker_entry
from app.settings import Settings


def test_historical_legacy_snapshot_cannot_reroute_graph_worker(monkeypatch):
    calls = []
    monkeypatch.setattr(worker_entry, "get_settings", lambda: SimpleNamespace(
        database_url="postgresql+psycopg://unused",
    ))
    monkeypatch.setattr(worker_entry, "process_job_with_graph", lambda *args, **kwargs: (
        calls.append((args, kwargs)) or {"state": "ready_for_review"}
    ))
    job = SimpleNamespace(config_snapshot={"execution_mode": "legacy"})
    result = worker_entry.process_claimed_job(
        object(), job, token="fixture-token", should_stop=lambda: False,
        heartbeat_callback=None,
    )
    assert result == {"state": "ready_for_review"}
    assert len(calls) == 1
    assert calls[0][0][1] is job
    assert calls[0][1]["token"] == "fixture-token"


def test_settings_reject_legacy_execution_mode():
    with pytest.raises(ValidationError):
        Settings(agent_execution_mode="legacy")
