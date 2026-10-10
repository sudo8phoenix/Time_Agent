"""Durable single-job worker primitives."""
from __future__ import annotations
from collections.abc import Callable
import inspect
import logging
import threading
from sqlalchemy.orm import Session
from .service import LEASE_SECONDS, claim_job, publish_stage, heartbeat, release_job

logger = logging.getLogger(__name__)

Pipeline = Callable[..., dict]

class WorkerShutdown(Exception):
    pass

def run_once(db: Session, pipeline: Pipeline, *, should_stop: Callable[[], bool] | None = None,
             heartbeat_callback: Callable[[object, str], bool] | None = None) -> bool:
    claimed = claim_job(db)
    if not claimed:
        return False
    job, token = claimed
    db.commit()  # make the lease visible before potentially slow model calls
    heartbeat_stop = threading.Event()
    lease_lost = threading.Event()
    heartbeat_thread = None
    if heartbeat_callback:
        def renew():
            while not heartbeat_stop.wait(max(1, LEASE_SECONDS // 3)):
                try:
                    if not heartbeat_callback(job, token):
                        lease_lost.set()
                        return
                except Exception:
                    lease_lost.set()
                    return
        heartbeat_thread = threading.Thread(target=renew, name="job-lease-heartbeat", daemon=True)
        heartbeat_thread.start()
    try:
        def stop_requested():
            if lease_lost.is_set():
                raise RuntimeError("JOB_LEASE_LOST")
            return bool(should_stop and should_stop())

        parameters = inspect.signature(pipeline).parameters
        if "token" in parameters or any(p.kind == p.VAR_KEYWORD for p in parameters.values()):
            result = pipeline(db, job, token=token, should_stop=stop_requested,
                              heartbeat_callback=heartbeat_callback) or {}
        else:
            result = pipeline(db, job) or {}
        db.commit()
        if not result.get("published"):
            publish_stage(
                db,
                job.id,
                token,
                stage=str(result.get("stage", "persist")),
                state=str(result.get("state", "ready_for_review")),
                extracted_count=result.get("extracted_count"),
                proposal_count=result.get("proposal_count"),
                error_code=result.get("error_code"),
                error_message=result.get("error_message"),
            )
            db.commit()
    except Exception as exc:
        logger.warning("job pipeline failed: %s", type(exc).__name__)
        db.rollback()
        try:
            if isinstance(exc, WorkerShutdown):
                release_job(db, job.id, token)
            else:
                code = getattr(exc, "code", "PIPELINE_ERROR")
                if not isinstance(code, str) or code not in {
                    "AGENT_FRAMEWORK_UNAVAILABLE", "AGENT_STATE_INVALID",
                    "AGENT_STATE_TOO_LARGE", "AGENT_STEP_LIMIT",
                    "AGENT_OBSERVATION_LIMIT", "AGENT_REPAIR_LIMIT",
                    "AGENT_CHECKPOINT_FAILED", "AGENT_CHECKPOINT_INCOMPATIBLE",
                    "AGENT_TOOL_FAILED", "AGENT_RUN_CONFLICT", "AGENT_INTERNAL_ERROR",
                    "JOB_LEASE_LOST", "SCHEDULE_VERSION_STALE", "PIPELINE_ERROR",
                }:
                    code = "PIPELINE_ERROR"
                safe_message = getattr(exc, "safe_message", "The job pipeline failed safely.")
                publish_stage(
                    db,
                    job.id,
                    token,
                    stage=job.stage or "persist",
                    state="failed",
                    error_code=code,
                    error_message=str(safe_message)[:1000],
                )
        except RuntimeError:
            db.rollback()
        else:
            db.commit()
    finally:
        heartbeat_stop.set()
        if heartbeat_thread:
            heartbeat_thread.join(timeout=2)
    return True


def run_loop(session_factory: Callable[[], Session], pipeline: Pipeline, *,
             should_stop: Callable[[], bool], poll_seconds: float = 2.0) -> None:
    """Poll durably; heartbeat sessions stay independent from job processing."""
    import time

    def beat(job, token: str) -> bool:
        with session_factory() as heartbeat_db:
            owned = heartbeat(heartbeat_db, job.id, token)
            heartbeat_db.commit()
            return owned

    while not should_stop():
        with session_factory() as db:
            worked = run_once(db, pipeline, should_stop=should_stop,
                              heartbeat_callback=beat)
        if not worked and not should_stop():
            time.sleep(poll_seconds)
