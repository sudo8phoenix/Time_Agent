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


def test_known_cooldown_keeps_report_queued_without_spending_attempt():
    from datetime import datetime, timezone, timedelta
    from sqlalchemy.orm import Session
    from app.db.models import HostedProviderAdmission, Job
    from app.jobs.admission import report_admission_ready
    from app.jobs.service import claim_job
    from test_agent_tools import Fixture
    fixture = Fixture()
    now = datetime.now(timezone.utc)
    settings = Settings(_env_file=None, llm_provider='groq',
                        agent_hierarchy_enabled=True, orchestrator_model_assisted=True,
                        groq_account_scopes_enabled=False)
    with Session(fixture.engine) as db:
        job = db.get(Job, fixture.job_id)
        job.state = 'queued'
        job.attempts = 0
        job.lease_token = None
        job.lease_expires_at = None
        db.add(HostedProviderAdmission(provider='groq', state={
            'cooldown': (now + timedelta(minutes=20)).timestamp()}))
        db.commit()
        def gate(session, candidate):
            return report_admission_ready(session, candidate, settings=settings, now=now)
        assert claim_job(db, admission_check=gate) is None
        db.commit()
        db.refresh(job)
        assert job.state == 'queued' and job.attempts == 0
        assert job.lease_token is None
        # Passage of real cooldown time allows normal claiming, with no quota reset.
        later = now + timedelta(minutes=21)
        assert claim_job(db, now=later, admission_check=lambda session, candidate:
            report_admission_ready(session, candidate, settings=settings, now=later))
        assert job.state == 'running' and job.attempts == 1
