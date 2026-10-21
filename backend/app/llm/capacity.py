"""Deployment-wide hosted admission using short PostgreSQL transactions.

No connection or transaction is held during inference or admission waits. The
lease covers socket connect/header timeout windows plus a crash-recovery margin.
Quota state contains only numeric counters/times and allowlisted numeric headers.
"""
from dataclasses import asdict
from datetime import timedelta
import time
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from ..db.models import HostedProviderAdmission
from .hosted import HostedAdmission, HostedCapacityError, HostedQuotaError, ProviderState


class DatabaseAdmission:
    def __init__(self, sessions, *, clock=time.monotonic, sleep=time.sleep, intervals=None):
        self.sessions, self.clock, self.sleep = sessions, clock, sleep
        self.intervals = intervals

    def _gate(self, row, now):
        started = self.clock()
        gate = HostedAdmission(intervals=self.intervals,
            clock=lambda: now.timestamp() + self.clock() - started)
        state = ProviderState(**row.state)
        state.active = bool(row.owner and row.lease_expires_at and row.lease_expires_at > now)
        gate.states[row.provider] = state
        return gate

    def acquire(self, provider, payload, timeout):
        from .account_scopes import SCOPES, check_policy
        if provider not in {"groq", "openrouter", *SCOPES}:
            raise HostedCapacityError("Unsupported hosted capacity scope")
        deadline = self.clock() + timeout
        while True:
            remaining = deadline - self.clock()
            if remaining <= .01:
                raise HostedCapacityError("Shared provider admission exceeded the request timeout")
            try:
                with self.sessions.begin() as db:
                    # A lock timeout keeps a contended/broken database inside the
                    # caller's admission deadline. It never triggers a local bypass.
                    db.execute(text("SELECT set_config('lock_timeout', :timeout, true)"),
                               {"timeout": f"{max(1, min(1000, int(remaining * 1000)))}ms"})
                    db.execute(insert(HostedProviderAdmission).values(provider=provider, state={}).on_conflict_do_nothing())
                    row = db.scalar(select(HostedProviderAdmission).where(
                        HostedProviderAdmission.provider == provider).with_for_update())
                    check_policy(db, provider)
                    now = db.scalar(select(func.clock_timestamp()))
                    gate = self._gate(row, now)
                    try:
                        gate.acquire(provider, payload, .001)
                    except HostedCapacityError as error:
                        wait = error.retry_after_seconds or min(.25, remaining / 2)
                    else:
                        owner = str(uuid4())
                        remaining = deadline - self.clock()
                        if remaining <= 0:
                            raise HostedCapacityError("Shared provider admission exceeded the request timeout")
                        row.owner = owner
                        row.lease_expires_at = now + timedelta(seconds=2 * remaining + 5)
                        row.state = asdict(gate.states[provider])
                        return owner, remaining
            except (HostedQuotaError, HostedCapacityError):
                raise
            except Exception:
                raise HostedCapacityError("Shared provider admission is unavailable") from None
            remaining = deadline - self.clock()
            if wait >= remaining:
                raise HostedCapacityError("Shared provider cooldown exceeds the request timeout",
                                          retry_after_seconds=wait)
            self.sleep(min(wait, .25, remaining))

    def release(self, provider, owner, *, status=None, headers=None):
        try:
            with self.sessions.begin() as db:
                db.execute(text("SELECT set_config('lock_timeout', '1000ms', true)"))
                row = db.scalar(select(HostedProviderAdmission).where(
                    HostedProviderAdmission.provider == provider).with_for_update())
                if row is None or row.owner != owner:
                    return False  # A stale process cannot release a replacement lease.
                now = db.scalar(select(func.clock_timestamp()))
                gate = self._gate(row, now)
                gate.release(provider, status=status, headers=headers)
                row.state = asdict(gate.states[provider])
                row.owner = row.lease_expires_at = None
                return True
        except Exception:
            # Keep the lease until its deadline. Never infer that an unavailable
            # coordinator permits a new call in this or another worker.
            raise HostedCapacityError("Shared provider release is unavailable") from None
