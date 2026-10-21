"""Real PostgreSQL account-policy boundaries in retained isolated test schemas."""

import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from app.db.models import HostedProviderAdmission
from app.llm.account_scopes import activate, SCOPES, MARKER
from app.llm.capacity import DatabaseAdmission
from app.llm.hosted import HostedCapacityError
from evaluation.deployment_rehearsal import _validate_target


@pytest.fixture
def scopes():
    url = os.environ.get("BATCH32_SCOPE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Explicit isolated account-policy database required")
    _validate_target(url)
    base = create_engine(url)
    schema = "scope_case_" + uuid4().hex
    with base.begin() as db:
        db.execute(text(f"CREATE SCHEMA {schema}"))
    engine = base.execution_options(schema_translate_map={None: schema})
    HostedProviderAdmission.__table__.create(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    yield sessions, DatabaseAdmission(sessions, intervals={})
    # Retain every schema/state for review; no DROP or balance resets.
    base.dispose()


def test_account_cannot_bypass_legacy_coordinator_before_activation(scopes):
    sessions, gate = scopes
    with pytest.raises(HostedCapacityError):
        gate.acquire(SCOPES[0], {}, 0.05)
    owner, _ = gate.acquire("groq", {}, 0.1)
    assert gate.release("groq", owner, status=200)
    with sessions() as db:
        assert db.get(HostedProviderAdmission, SCOPES[0]) is None


def test_activation_preserves_unknown_prior_balances_in_both_accounts(scopes):
    sessions, gate = scopes
    owner, _ = gate.acquire("groq", {}, 0.1)
    gate.release(
        "groq",
        owner,
        status=200,
        headers={
            "x-ratelimit-remaining-requests": "321",
            "x-ratelimit-reset-requests": "1h",
            "x-ratelimit-remaining-tokens": "1000",
            "x-ratelimit-reset-tokens": "60s",
        },
    )
    with sessions() as db:
        old = dict(db.get(HostedProviderAdmission, "groq").state)
    activate(sessions)
    with sessions() as db:
        assert db.get(HostedProviderAdmission, "groq").state == old
        for scope in SCOPES:
            state = db.get(HostedProviderAdmission, scope).state
            assert state["remaining_requests"] == 321 and state["remaining_tokens"] == 1000
        assert db.get(HostedProviderAdmission, MARKER).state == {"version": 1, "enabled": True}


def test_account_cooldown_and_active_leases_are_independent(scopes):
    sessions, gate = scopes
    activate(sessions)
    first, _ = gate.acquire(SCOPES[0], {}, 0.1)
    assert gate.release(SCOPES[0], first, status=429, headers={"retry-after": "60"})
    second, _ = gate.acquire(SCOPES[1], {}, 0.1)
    assert not gate.release(SCOPES[1], "stale-owner", status=200)
    with pytest.raises(HostedCapacityError):
        gate.acquire(SCOPES[0], {}, 0.05)
    with pytest.raises(HostedCapacityError):
        gate.acquire(SCOPES[1], {}, 0.05)
    assert gate.release(SCOPES[1], second, status=200)


def test_old_workers_and_reactivation_fail_without_reset(scopes):
    sessions, gate = scopes
    activate(sessions)
    with pytest.raises(HostedCapacityError):
        gate.acquire("groq", {}, 0.05)
    with sessions() as db:
        before = {
            row.provider: dict(row.state) for row in db.scalars(select(HostedProviderAdmission))
        }
    with pytest.raises(HostedCapacityError):
        activate(sessions)
    with sessions() as db:
        after = {
            row.provider: dict(row.state) for row in db.scalars(select(HostedProviderAdmission))
        }
    assert before == after


def test_activation_refuses_inflight_old_work(scopes):
    sessions, gate = scopes
    owner, _ = gate.acquire("groq", {}, 0.1)
    with pytest.raises(HostedCapacityError):
        activate(sessions)
    with sessions() as db:
        assert db.get(HostedProviderAdmission, "groq").owner == owner
        assert db.get(HostedProviderAdmission, MARKER) is None
    assert gate.release("groq", owner, status=200)
