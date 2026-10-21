"""Independent scopes are opt-in and unknown/shared aliases cannot evade quota."""

import pytest
from app.llm.account_scopes import resolve_scope, SCOPES
from app.llm.hosted import HostedAdmission, HostedCapacityError
from app.llm.provider import create_adapter
from app.settings import Settings


def settings(**values):
    return Settings(
        _env_file=None,
        llm_provider="groq",
        groq_account_scopes_enabled=True,
        groq_api_key="legacy",
        groq_api_key_1="one",
        groq_api_key_2="two",
        **values,
    )


def test_opt_in_off_retains_shared_scope():
    s = settings()
    s.groq_account_scopes_enabled = False
    assert resolve_scope(s, 0) is None and resolve_scope(s, 1) is None


@pytest.mark.parametrize("slot", [1, 2])
def test_verified_roles_receive_their_account_scope(slot):
    s = settings(extraction_key_slot=slot)
    adapter = create_adapter(s, role="extraction", timeout=30)
    assert adapter.capacity_scope == SCOPES[slot - 1]
    assert adapter._token == ("one" if slot == 1 else "two")


@pytest.mark.parametrize("slot", [0, 3])
def test_unknown_key_is_rejected(slot):
    with pytest.raises(HostedCapacityError):
        resolve_scope(settings(), slot)


@pytest.mark.parametrize("alias_of", [1, 2])
def test_aliases_share_scope_instead_of_multiplying_allowance(alias_of):
    s = settings()
    s.groq_api_key = getattr(s, f"groq_api_key_{alias_of}")
    assert resolve_scope(s, 0) == resolve_scope(s, alias_of)


def test_equal_keys_cannot_be_declared_two_independent_accounts():
    s = settings()
    s.groq_api_key_2 = s.groq_api_key_1
    with pytest.raises(HostedCapacityError):
        resolve_scope(s, 2)


def test_cooldown_is_independent_in_actual_admission_state_machine():
    gate = HostedAdmission(intervals={}, clock=lambda: 100)
    gate.acquire(SCOPES[0], {}, 10)
    gate.release(SCOPES[0], status=429, headers={"retry-after": "60"})
    assert gate.acquire(SCOPES[1], {}, 1) > 0
    gate.release(SCOPES[1], status=200)
    with pytest.raises(HostedCapacityError):
        gate.acquire(SCOPES[0], {}, 1)


def test_account_scopes_preserve_groq_token_smoothing():
    gate = HostedAdmission(intervals={}, clock=lambda: 100)
    gate.acquire(SCOPES[0], {"max_completion_tokens": 100}, 10)
    gate.release(SCOPES[0], status=200, headers={"x-ratelimit-limit-tokens": "8000"})
    state = gate.states[SCOPES[0]]
    assert state.token_limit == 8000
    assert state.next_request >= 100 + 60 * state.last_estimate / 8000
