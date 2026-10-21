"""Trusted owner-confirmed account aliases; no per-key quota multiplication.

The opt-in policy requires explicit database activation after old workers stop.
Unknown credentials fail closed; aliases of a verified credential share its scope.
"""

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..db.models import HostedProviderAdmission
from .hosted import HostedCapacityError

SCOPES = ("groq:account-1", "groq:account-2")
MARKER = "groq:scope-v1"


def resolve_scope(settings, slot):
    if not getattr(settings, "groq_account_scopes_enabled", False):
        return None
    keys = {}
    for number in (0, 1, 2):
        key = getattr(settings, "groq_api_key" if number == 0 else f"groq_api_key_{number}", None)
        keys[number] = key.get_secret_value() if key else None
    if not keys[1] or not keys[2] or keys[1] == keys[2]:
        raise HostedCapacityError("Independent account configuration is incomplete")
    selected = keys.get(slot)
    for number in (1, 2):
        if selected and selected == keys[number]:
            return SCOPES[number - 1]
    raise HostedCapacityError("Credential account scope is unverified")


def check_policy(db, scope):
    if scope != "groq" and scope not in SCOPES:
        return
    marker = db.scalar(
        select(HostedProviderAdmission)
        .where(HostedProviderAdmission.provider == MARKER)
        .with_for_update()
    )
    if scope == "groq" and marker is not None:
        raise HostedCapacityError("Legacy workers must restart under the activated account policy")
    if scope in SCOPES and (marker is None or marker.state != {"version": 1, "enabled": True}):
        raise HostedCapacityError("Account policy requires explicit database activation")


def activate(sessions):
    """Explicit, transactionally fenced migration; never called by a model request.

    Preserve the old unknown-account quota in both accounts conservatively. There
    is no automatic rollback or reset: rollback needs a separately reviewed merge
    of both current states, not deleting this marker or restoring old balances.
    """
    with sessions.begin() as db:
        # Serialize activation against provider-wide acquisition and other activators.
        db.execute(
            insert(HostedProviderAdmission)
            .values(provider="groq", state={})
            .on_conflict_do_nothing()
        )
        old = db.scalar(
            select(HostedProviderAdmission)
            .where(HostedProviderAdmission.provider == "groq")
            .with_for_update()
        )
        existing = db.get(HostedProviderAdmission, MARKER)
        if existing is not None:
            raise HostedCapacityError("Account policy is already activated")
        if old.owner:
            raise HostedCapacityError("Stop old in-flight work before account activation")
        for scope in SCOPES:
            if db.get(HostedProviderAdmission, scope) is not None:
                raise HostedCapacityError("Retained account state must not be replaced")
            state = deepcopy(old.state)
            state["active"] = False
            db.add(HostedProviderAdmission(provider=scope, state=state))
        db.add(HostedProviderAdmission(provider=MARKER, state={"version": 1, "enabled": True}))
