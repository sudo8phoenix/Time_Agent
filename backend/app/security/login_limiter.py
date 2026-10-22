"""Database-backed login admission, committed independently of failed logins."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import hmac
import math

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import LoginThrottleBucket

WINDOW_SECONDS = 300
MAX_ACCOUNT_FAILURES = 5
MAX_IP_ATTEMPTS = 50
MAX_BUCKETS = 10_000
# All workers serialize the short admission transaction, including capacity checks.
ADVISORY_LOCK = 734976210


@dataclass
class LoginLimited(Exception):
    retry_after: int


class LoginLimiterUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Reservation:
    account_key: str
    expires_at: datetime


class SharedLoginLimiter:
    def __init__(self, session_factory, secret: str):
        self.session_factory = session_factory
        self.secret = secret.encode()

    def _key(self, kind, value):
        return hmac.new(self.secret, f'{kind}:{value}'.encode(), hashlib.sha256).hexdigest()

    def reserve(self, host: str, username: str) -> Reservation:
        limits = ((self._key('account', username.casefold()), MAX_ACCOUNT_FAILURES),
                  (self._key('ip', host), MAX_IP_ATTEMPTS))
        try:
            with self.session_factory() as db, db.begin():
                dialect = db.get_bind().dialect.name
                if dialect == 'postgresql':
                    db.execute(text('SET LOCAL lock_timeout = \'3s\''))
                    db.execute(text('SET LOCAL statement_timeout = \'5s\''))
                    db.execute(select(func.pg_advisory_xact_lock(ADVISORY_LOCK)))
                elif dialect == 'sqlite':
                    # Used by isolated tests; PostgreSQL is the deployed backend.
                    db.execute(text('BEGIN IMMEDIATE'))
                else:
                    raise LoginLimiterUnavailable()
                now = db.scalar(select(
                    func.clock_timestamp() if dialect == 'postgresql' else func.current_timestamp()
                ))
                db.execute(delete(LoginThrottleBucket).where(LoginThrottleBucket.expires_at <= now))
                buckets = {key: db.get(LoginThrottleBucket, key) for key, _ in limits}
                missing = sum(bucket is None for bucket in buckets.values())
                total = db.scalar(select(func.count()).select_from(LoginThrottleBucket))
                if total + missing > MAX_BUCKETS:
                    raise LoginLimited(WINDOW_SECONDS)
                for key, limit in limits:
                    bucket = buckets[key]
                    if bucket is not None and bucket.attempts >= limit:
                        remaining = (bucket.expires_at - now).total_seconds()
                        raise LoginLimited(max(1, math.ceil(remaining)))
                for key, _ in limits:
                    bucket = buckets[key]
                    if bucket is None:
                        bucket = LoginThrottleBucket(
                            key_hash=key, attempts=0,
                            expires_at=now + timedelta(seconds=WINDOW_SECONDS),
                        )
                        db.add(bucket)
                        buckets[key] = bucket
                    bucket.attempts += 1
                reservation = Reservation(limits[0][0], buckets[limits[0][0]].expires_at)
            return reservation
        except SQLAlchemyError as exc:
            # Never fall back to a worker-local counter or disclose DB diagnostics.
            raise LoginLimiterUnavailable() from exc

    def release_success(self, reservation: Reservation) -> None:
        try:
            with self.session_factory() as db, db.begin():
                # Atomic decrement cannot erase other failures or a newer window.
                db.execute(update(LoginThrottleBucket).where(
                    LoginThrottleBucket.key_hash == reservation.account_key,
                    LoginThrottleBucket.expires_at == reservation.expires_at,
                    LoginThrottleBucket.attempts > 0,
                ).values(attempts=LoginThrottleBucket.attempts - 1))
        except SQLAlchemyError as exc:
            raise LoginLimiterUnavailable() from exc
