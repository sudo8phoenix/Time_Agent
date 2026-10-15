"""Private evaluation ownership snapshots; no tokens, prompts or error text."""
from contextlib import contextmanager
from datetime import datetime, timezone
import threading

from app.db.models import Job
from app.jobs.service import LEASE_SECONDS, heartbeat


def ownership_snapshot(sessions, job_id, token):
    with sessions() as db:
        job = db.get(Job, job_id)
        if not job:
            return {"exists": False}
        expiry = job.lease_expires_at
        if expiry and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        timestamp = datetime.now(timezone.utc)
        return {"exists": True, "job_state": job.state, "job_stage": job.stage,
            "attempts": job.attempts, "token_matches": job.lease_token == token,
            "lease_remaining_seconds": round((expiry - timestamp).total_seconds(), 3) if expiry else None,
            "captured_at": timestamp.isoformat()}


@contextmanager
def observe_ownership(runtime, sessions, job_id, token):
    """Evaluation already runs isolated sequential arms; restore hooks on all exits."""
    original = runtime._ensure_active
    events = []
    def record(phase):
        if len(events) >= 4096:
            return
        try:
            entry = {"phase": phase, **ownership_snapshot(sessions, job_id, token)}
            events.append(entry)
            return entry
        except Exception:
            events.append({"phase": phase, "diagnostic_unavailable": True})
    def check(*args, **kwargs):
        record("before_check")
        try:
            return original(*args, **kwargs)
        except Exception as error:
            entry = record("check_failed")
            if entry is not None:
                entry["error_code"] = getattr(error, "code", "OWNERSHIP_CHECK_FAILED")
            raise
        finally:
            record("after_check")
    runtime._ensure_active = check
    try:
        record("initial")
        yield events
    finally:
        record("final")
        runtime._ensure_active = original


@contextmanager
def renewing_lease(sessions, job_id, token):
    """Use the same independent-session heartbeat primitive as the worker."""
    stop, lost = threading.Event(), threading.Event()
    def beat(*_):
        with sessions.begin() as db:
            return heartbeat(db, job_id, token)
    def renew():
        while not stop.wait(max(1, LEASE_SECONDS // 3)):
            try:
                if not beat():
                    lost.set()
                    return
            except Exception:
                lost.set()
                return
    thread = threading.Thread(target=renew, name="evaluation-lease-heartbeat", daemon=True)
    thread.start()
    try:
        yield beat, lost.is_set
    finally:
        stop.set()
        thread.join(timeout=2)
