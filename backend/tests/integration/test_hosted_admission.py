"""Shared quota state and crash recovery across independent worker processes."""
from datetime import timedelta
import json
import os
import subprocess
import sys

import pytest
from sqlalchemy import delete, func, select

from app.db.models import HostedProviderAdmission
from app.db.session import session_factory
from app.llm.capacity import DatabaseAdmission
from app.llm.hosted import HostedCapacityError, HostedQuotaError


@pytest.fixture
def gate():
    with session_factory.begin() as db:
        db.execute(delete(HostedProviderAdmission))
    yield DatabaseAdmission(session_factory, intervals={})
    with session_factory.begin() as db:
        db.execute(delete(HostedProviderAdmission))


def test_independent_workers_share_exclusivity_and_cooldown(gate):
    other = DatabaseAdmission(session_factory, intervals={})
    owner, _ = gate.acquire("groq", {}, 1)
    with pytest.raises(HostedCapacityError):
        other.acquire("groq", {}, .03)
    # Another provider remains independent.
    router, _ = other.acquire("openrouter", {}, 1)
    assert other.release("openrouter", router)
    assert gate.release("groq", owner, status=429, headers={"Retry-After": "120",
        "Authorization": "never-store-this", "x-ratelimit-remaining-tokens": "10"})
    with pytest.raises(HostedCapacityError) as error:
        other.acquire("groq", {}, .1)
    assert error.value.retry_after_seconds > 119
    with session_factory() as db:
        row = db.get(HostedProviderAdmission, "groq")
        assert row.owner is None and row.lease_expires_at is None
        assert "never-store-this" not in json.dumps(row.state)
        assert row.state["headers"]["retry-after"] == 120


def test_daily_exhaustion_persists_and_reset_allows_recovery(gate):
    owner, _ = gate.acquire("groq", {}, 1)
    gate.release("groq", owner, status=200, headers={"x-ratelimit-remaining-requests": "0",
        "x-ratelimit-reset-requests": "1h"})
    with pytest.raises(HostedQuotaError):
        DatabaseAdmission(session_factory).acquire("groq", {}, 1)
    with session_factory.begin() as db:
        row = db.get(HostedProviderAdmission, "groq")
        row.state = {**row.state, "request_reset": 1}
    second, _ = gate.acquire("groq", {}, 1)
    assert gate.release("groq", second)


def test_killed_worker_lease_recovers_and_stale_release_is_fenced(gate):
    code = '''
import json,time
from app.db.session import session_factory
from app.llm.capacity import DatabaseAdmission
owner, remaining = DatabaseAdmission(session_factory, intervals={}).acquire("groq", {}, 2)
print(json.dumps({"owner":owner}), flush=True)
time.sleep(30)
'''
    child = subprocess.Popen([sys.executable, "-c", code], env={**os.environ,
        "PYTHONPATH": "backend"}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        stale = json.loads(child.stdout.readline())["owner"]
        child.kill()
        child.wait(timeout=5)
        with pytest.raises(HostedCapacityError):
            gate.acquire("groq", {}, .03)
        # Advance the database lease past its bounded crash-recovery deadline.
        with session_factory.begin() as db:
            row = db.get(HostedProviderAdmission, "groq")
            row.lease_expires_at = db.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
        replacement, _ = gate.acquire("groq", {}, 1)
        assert replacement != stale
        assert gate.release("groq", stale, status=429, headers={"Retry-After": "3600"}) is False
        with session_factory() as db:
            assert db.get(HostedProviderAdmission, "groq").owner == replacement
        assert gate.release("groq", replacement)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_database_outage_never_falls_back_to_uncoordinated_inference():
    class Offline:
        def begin(self):
            raise OSError("private connection details")
    with pytest.raises(HostedCapacityError) as error:
        DatabaseAdmission(Offline()).acquire("groq", {}, .1)
    assert "private" not in str(error.value)


def test_default_transport_shares_cooldown_and_holds_no_database_transaction(gate, monkeypatch):
    from urllib.error import HTTPError
    from app.llm import hosted
    from app.llm.groq import GroqChatAdapter
    calls = []
    monkeypatch.setattr(hosted, "ADMISSION", hosted.DeploymentHostedAdmission())
    def limited(*args, **kwargs):
        calls.append(1)
        with session_factory.begin() as db:
            row = db.scalar(select(HostedProviderAdmission).where(
                HostedProviderAdmission.provider == "groq").with_for_update(nowait=True))
            assert row.owner  # Reservation committed; no network-spanning transaction.
        raise HTTPError("https://api.groq.com/", 429, "ignored", {"Retry-After": "120"}, None)
    monkeypatch.setattr(hosted, "urlopen", limited)
    options = dict(system="s", user="u", schema={"type": "object"})
    with pytest.raises(hosted.HostedRateLimitError):
        GroqChatAdapter("fixture", bearer_token="first-role-key", timeout=.5).chat(**options)
    with pytest.raises(HostedCapacityError):
        GroqChatAdapter("fixture", bearer_token="second-role-key", timeout=.5).chat(**options)
    assert calls == [1]


def test_three_processes_sustain_twelve_serialized_reservations(gate):
    code = '''
import json,time
from app.db.session import session_factory
from app.llm.capacity import DatabaseAdmission
coordinator = DatabaseAdmission(session_factory, intervals={})
rows=[]
for ordinal in range(4):
    owner, remaining = coordinator.acquire("groq", {}, 5)
    started=time.monotonic()
    time.sleep(.01)  # Synthetic work only; no provider request.
    finished=time.monotonic()
    assert coordinator.release("groq",owner,status=200)
    rows.append([started,finished])
print(json.dumps(rows),flush=True)
'''
    children = [subprocess.Popen([sys.executable, "-c", code], env={**os.environ,
        "PYTHONPATH": "backend"}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(3)]
    try:
        intervals = []
        for child in children:
            output, _ = child.communicate(timeout=15)
            assert child.returncode == 0
            intervals.extend(json.loads(output))
        intervals.sort()
        assert len(intervals) == 12
        assert all(second[0] >= first[1] for first, second in zip(intervals, intervals[1:]))
        with session_factory() as db:
            assert db.get(HostedProviderAdmission, "groq").owner is None
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
