"""Bounded synthetic DatabaseAdmission soak; refuses any DB except progress_test.

Creates one unique schema and provider-state table per run. Uses production
DatabaseAdmission transactions, but never constructs an adapter or opens network
transport. All synthetic state is retained in that schema for inspection.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import HostedProviderAdmission
from app.llm.capacity import DatabaseAdmission
from app.llm.hosted import HostedCapacityError, HostedQuotaError, HostedAdmission


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int((len(values) - 1) * fraction))]


def _round(value):
    return round(value, 3) if value is not None else None


def summarize_ms(values):
    return {"count": len(values), "p50": _round(percentile(values, .5)),
            "p95": _round(percentile(values, .95)),
            "max": _round(max(values) if values else None)}


def exception_type(error):
    """Return an exception class only; messages may contain credentials or SQL."""
    return type(error).__name__


def validate_target(raw_url):
    try:
        url = make_url(raw_url)
    except Exception:
        raise ValueError("invalid database target") from None
    if url.get_backend_name() != "postgresql" or url.database != "progress_test":
        raise ValueError("target must be progress_test PostgreSQL")
    if url.host not in {"127.0.0.1", "localhost"}:
        raise ValueError("target must be local")
    return url


def open_exclusive(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("x", encoding="utf-8")


def write_json_exclusive(path, value):
    with open_exclusive(path) as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def local_clock_checks():
    now = [100.0]
    gate = HostedAdmission(intervals={}, clock=lambda: now[0])
    gate.acquire("groq", {}, 1)
    gate.release("groq", status=200, headers={
        "x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "10s"})
    now[0] = 90.0  # Simulated backward wall-clock movement must not clear a future reset.
    backward_kept_quota_closed = False
    try:
        gate.acquire("groq", {}, 1)
    except HostedQuotaError:
        backward_kept_quota_closed = True
    now[0] = 111.0  # Forward movement beyond the reset permits recovery.
    gate.acquire("groq", {}, 1)
    gate.release("groq", status=200, headers={})
    return {"backward_step_did_not_clear_future_quota_reset": backward_kept_quota_closed,
            "forward_step_past_reset_recovered": not gate.states["groq"].remaining_requests == 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    try:
        url = validate_target(args.database_url)
    except ValueError as error:
        parser.error(str(error))
    if not 30 <= args.seconds <= 60 or not 2 <= args.workers <= 8:
        parser.error("Use a new evidence file, 30–60 seconds and 2–8 workers")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_stream = open_exclusive(args.output)
    except FileExistsError:
        parser.error("Evidence output already exists")
    output_stream.write(json.dumps({
        "status": "started",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source": str(Path(__file__)),
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
    }, indent=2) + "\n")
    output_stream.flush()

    run_id = uuid4().hex[:12]
    schema = "perf_" + run_id
    admin = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=0)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, pool_pre_ping=True, pool_size=args.workers + 2,
                           max_overflow=0, connect_args={"options": f"-csearch_path={schema},public"})
    HostedProviderAdmission.__table__.create(engine)
    Sessions = sessionmaker(engine, expire_on_commit=False)

    active = 0
    max_active = 0
    checked_out = 0
    max_checked_out = 0
    transactions = []
    guard = threading.Lock()

    @event.listens_for(engine, "checkout")
    def checkout(*_):
        nonlocal checked_out, max_checked_out
        with guard:
            checked_out += 1
            max_checked_out = max(max_checked_out, checked_out)

    @event.listens_for(engine, "checkin")
    def checkin(*_):
        nonlocal checked_out
        with guard:
            checked_out -= 1

    @event.listens_for(Session, "after_begin")
    def begin(_session, _transaction, _connection):
        if _session.bind is not engine:
            return
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        _session.info["perf_tx_started"] = time.monotonic()

    @event.listens_for(Session, "after_transaction_end")
    def end(session, transaction):
        if session.bind is not engine:
            return
        nonlocal active
        if transaction.parent is None:
            started = session.info.pop("perf_tx_started", None)
            with guard:
                active -= 1
                if started is not None:
                    transactions.append((time.monotonic() - started) * 1000)

    gate = DatabaseAdmission(Sessions, intervals={"groq": 0})
    stop = threading.Event()
    barrier = threading.Barrier(args.workers)
    rows = []
    errors = []

    def worker(index):
        local_rows = []
        try:
            barrier.wait(timeout=5)
            while not stop.is_set():
                submitted = time.monotonic()
                owner, _ = gate.acquire("groq", {"kind": "synthetic", "max_completion_tokens": 8}, 5)
                admitted = time.monotonic()
                time.sleep(.002)
                gate.release("groq", owner, status=200, headers={})
                local_rows.append({"worker": index, "wait_ms": (admitted - submitted) * 1000})
        except BaseException as error:
            with guard:
                errors.append(exception_type(error))
        finally:
            with guard:
                rows.extend(local_rows)

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(args.workers)]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    deadline = started + args.seconds
    while time.monotonic() < deadline and not errors:
        time.sleep(.1)
    stop.set()
    for thread in threads:
        thread.join(timeout=7)
    lingering = any(thread.is_alive() for thread in threads)
    if lingering:
        errors.append("WorkerJoinTimeout")

    # Exercise durable cooldown and daily exhaustion in the unique provider row.
    diagnostic_errors = []
    cooldown_blocked = quota_blocked = quota_reset_recovered = None
    if not lingering:
        try:
            owner, _ = gate.acquire("groq", {}, 2)
            gate.release("groq", owner, status=429, headers={"Retry-After": "0.2"})
            try:
                gate.acquire("groq", {}, .03)
            except HostedCapacityError:
                cooldown_blocked = True
            time.sleep(.22)
            owner, _ = gate.acquire("groq", {}, 2)
            gate.release("groq", owner, status=200, headers={
                "x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "0.2"})
            try:
                gate.acquire("groq", {}, .2)
            except HostedQuotaError:
                quota_blocked = True
            time.sleep(.25)
            owner, _ = gate.acquire("groq", {}, 2)
            quota_reset_recovered = gate.release("groq", owner, status=200, headers={})
        except BaseException as error:
            diagnostic_errors.append(exception_type(error))

    state = db_sample = None
    if not lingering:
        try:
            with Sessions() as session:
                state = session.get(HostedProviderAdmission, "groq").state
                db_sample = session.execute(text("select current_database(), current_schema()" )).one()
        except BaseException as error:
            diagnostic_errors.append(exception_type(error))
    duration = time.monotonic() - started
    with guard:
        rows = rows[:]
        tx = transactions[:]
        worker_counts = {str(i): sum(r["worker"] == i for r in rows) for i in range(args.workers)}
        observed_max_active, observed_max_connections = max_active, max_checked_out
    waits = [row["wait_ms"] for row in rows]
    result = {
        "status": "incomplete" if errors or diagnostic_errors or lingering else "completed",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source": str(Path(__file__)),
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "database": {"database": db_sample[0], "schema": db_sample[1], "schema_retained": True}
                    if db_sample else {"database": "progress_test", "schema": schema, "schema_retained": True},
        "parameters": {"duration_budget_seconds": args.seconds, "workers": args.workers,
                       "synthetic_slot_hold_seconds": .002, "provider_interval_seconds": 0,
                       "network_transport": "none", "inference": "none"},
        "soak": {"elapsed_seconds": round(duration, 3), "completed_reservations": len(rows),
                 "throughput_per_second": round(len(rows) / duration, 2) if rows else None,
                 "completions_per_worker": worker_counts,
                 "admission_wait_ms": {key: value for key, value in summarize_ms(waits).items()
                                       if key != "count"},
                 "db_transaction_ms": summarize_ms(tx),
                 "peak_open_transactions": observed_max_active,
                 "peak_checked_out_connections": observed_max_connections,
                 "errors": errors, "diagnostic_errors": diagnostic_errors,
                 "diagnostics_skipped_for_lingering_workers": lingering},
        "quota_faults": {"cooldown_deadline_rejected": cooldown_blocked,
                         "daily_exhaustion_rejected": quota_blocked,
                         "daily_reset_recovered": quota_reset_recovered,
                         "persisted_numeric_state": state},
        "controlled_clock_steps": local_clock_checks(),
        "clock_note": "DatabaseAdmission uses PostgreSQL clock_timestamp for persisted cooldown/quota time and a monotonic local deadline. Clock jumps are not simulated in this DB soak; controlled in-process fake-clock tests remain the clock-change evidence.",
        "limits": ["Synthetic 2ms reservation hold, not provider transport or application workload.",
                   "Only a single local PostgreSQL instance and unique schema; no other clients or production quota traffic.",
                   "Finite 30-second minimum soak cannot establish long-duration memory/storage stability or operational throughput.",
                   "Fairness is observational only; equal-sized completions do not imply starvation bounds."],
    }
    output_stream.seek(0)
    output_stream.truncate()
    output_stream.write(json.dumps(result, indent=2) + "\n")
    output_stream.close()
    print(json.dumps(result))
    if not lingering:
        engine.dispose()
        admin.dispose()


if __name__ == "__main__":
    main()
