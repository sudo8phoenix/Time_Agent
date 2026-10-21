"""Bounded offline mixed workload on a new SQLite WAL database.

Measures actual production queue, validation, approval, outbox and API paths.
Provider transport/admission are absent and reported as unmeasured, never zero.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
from pathlib import Path
import resource
import threading
import time
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.endpoints.review import ApprovalRequest, approve
from app.conversation import runtime
from app.conversation.service import add_turn
from app.db.models import (Activity, ActivityState, Base, Conversation, ConversationTask,
    Fragment, IntegrationOutbox, Job, Observation, Project, ProjectMembership,
    Proposal, ScheduleVersion, User)
from app.ingest.reports import ingest_report
from app.jobs.service import claim_job, enqueue_job, publish_stage
from app.llm.extract import FragmentInput, extract_fragments
from backend.tests.unit.test_extraction import observation


def run(output: Path, reports_per_phase=12, duration_seconds=30):
    output.mkdir(parents=True, exist_ok=False)
    scratch = tempfile.TemporaryDirectory(prefix="batch26-runtime-")
    database = Path(scratch.name) / "isolated-runtime.sqlite"
    engine = create_engine(f"sqlite:///{database}", connect_args={"timeout": 20}, pool_size=8, max_overflow=0)
    with engine.connect() as connection:
        connection.execute(text("PRAGMA journal_mode=WAL"))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    lock = threading.Lock()
    measurements = defaultdict(list)
    resources = []
    connections = {"current": 0, "peak": 0}
    errors = []
    submissions = {}
    completed = {}
    samples = []
    row_counts = []

    @event.listens_for(engine, "checkout")
    def checkout(*_):
        with lock:
            connections["current"] += 1
            connections["peak"] = max(connections["peak"], connections["current"])

    @event.listens_for(engine, "checkin")
    def checkin(*_):
        with lock:
            connections["current"] -= 1

    @event.listens_for(Session, "after_begin")
    def transaction_begin(session, *_):
        if session.bind is engine:
            session.info["probe_started"] = time.perf_counter()

    @event.listens_for(Session, "after_transaction_end")
    def transaction_end(session, transaction):
        if session.bind is engine and transaction.parent is None:
            started = session.info.pop("probe_started", None)
            if started is not None:
                with lock:
                    measurements["db_transaction_ms"].append((time.perf_counter() - started) * 1000)

    @event.listens_for(engine, "before_cursor_execute")
    def query_begin(connection, *_):
        connection.info["query_started"] = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def query_end(connection, *_):
        with lock:
            measurements["db_statement_ms"].append((time.perf_counter() - connection.info.pop("query_started")) * 1000)

    with sessions.begin() as db:
        user = User(username="offline-reviewer", password_hash="unused", role="reviewer")
        project = Project(name="Isolated batch26", timezone="UTC")
        schedule = ScheduleVersion(project=project, version_number=1, content_sha256="a" * 64, state="active")
        db.add_all([user, project, schedule])
        db.flush()
        project.active_schedule_version_id = schedule.id
        db.add(ProjectMembership(user_id=user.id, project_id=project.id))
        user_id, project_id, schedule_id = user.id, project.id, schedule.id
        db.add(Activity(schedule_version_id=schedule.id, external_id="EX-F01", name="Excavation F-01",
            wbs="1", discipline="civil", work_type="excavation", area="F-01", asset_tags="F-01",
            is_leaf=True, measurement_basis="unsupported"))

    # HTTP uses the real persisted Job state. This isolated read-only endpoint
    # deliberately excludes production authentication/browser rendering latency.
    app = FastAPI()
    @app.get("/readiness/{job_id}")
    def readiness(job_id: str):
        from uuid import UUID
        with sessions() as db:
            job = db.get(Job, UUID(job_id))
            return {"id": job_id, "state": job.state, "stage": job.stage,
                    "extracted_count": job.extracted_count, "proposal_count": job.proposal_count}

    from app.integrations.outbox import run_once as deliver
    class Connector:
        def deliver(self, value):
            return {"offline_receipt": value["idempotency_key"]}

    # A bounded original-byte sink preserves actual report storage cost locally.
    import app.ingest.reports as reports_module
    original_store = reports_module._store_original
    reports_module._store_original = lambda key, raw: (Path(scratch.name) / (Path(key).name)).write_bytes(raw)
    started = time.perf_counter()
    try:
        phase_number = 0
        while phase_number < 2 or time.perf_counter() - started < duration_seconds:
            phase = "application_cold" if phase_number == 0 else f"application_warm_{phase_number}"
            phase_number += 1
            phase_start = time.perf_counter()
            phase_jobs = []
            approval_ids = []
            with sessions.begin() as db:
                for number in range(reports_per_phase):
                    shape = "short" if number % 2 == 0 else "long_multi_event"
                    count = 2 if shape == "short" else 160
                    parts = [(f"line-{index}", f"On 2026-09-21, erected 3 spools on line L{number}-{index} in AREA-A.")
                             for index in range(count)]
                    raw = (phase + "\n" + "\n".join(value for _, value in parts)).encode()
                    begin = time.perf_counter()
                    report, _ = ingest_report(db, db.get(Project, project_id), raw, filename=f"{phase}-{number}.txt",
                                             report_date=date(2026, 9, 21), parsed_parts=parts)
                    job, _ = enqueue_job(db, db.get(Project, project_id), report)
                    submissions[str(job.id)] = {"at": begin, "phase": phase, "shape": shape,
                                                "events": count, "bytes": len(raw)}
                    phase_jobs.append(job.id)
                    measurements["intake_db_ms"].append((time.perf_counter() - begin) * 1000)
                for number in range(6):
                    conversation = Conversation(project_id=project_id, creator_id=user_id, schedule_version_id=schedule_id,
                        revision=0, status="draft", draft={"orchestration_version": runtime.VERSION, "report_date": "2026-10-09"})
                    db.add(conversation)
                    db.flush()
                    add_turn(db, conversation, "user", "Started excavation at F-01 at 08:30", user_id)
                    runtime.enqueue(db, conversation)
                    activity = Activity(schedule_version_id=schedule_id, external_id=f"{phase}-{number}", name="Install",
                        wbs="1", discipline="mechanical", work_type="pipe_spool_erection", area="A", is_leaf=True,
                        measurement_basis="quantity_ratio", planned_quantity=10, unit="spool", baseline_quantity=0,
                        baseline_date=date(2026, 1, 1))
                    db.add(activity)
                    db.flush()
                    db.add(ActivityState(activity_id=activity.id, revision=0, completed_quantity=0))
                    observation_row = Observation(job_id=phase_jobs[number], ordinal=1000, fields={"summary": "installed", "quantity": "2"})
                    db.add(observation_row)
                    db.flush()
                    proposal = Proposal(observation_id=observation_row.id, project_id=project_id, chosen_activity_id=activity.id,
                        proposed_effects={"quantity": "2", "unit": "spool", "quantity_semantics": "delta",
                                          "event_type": "actual_progress", "effective_date": "2026-01-02"})
                    db.add(proposal)
                    db.flush()
                    approval_ids.append(proposal.id)

            committed_at = time.perf_counter()
            for job_id in phase_jobs:
                submissions[str(job_id)]["queue_committed_at"] = committed_at
            stop = threading.Event()
            def guarded(function):
                try:
                    function()
                except Exception as error:
                    with lock:
                        errors.append({"phase": phase, "type": type(error).__name__, "message": str(error)[:200]})
                    stop.set()

            def report_worker():
                while not stop.is_set():
                    with sessions.begin() as db:
                        claimed = claim_job(db)
                        if claimed is None:
                            return
                        job, token = claimed
                        job_id = job.id
                        fragments = db.scalars(select(Fragment).where(Fragment.report_id == job.report_id).order_by(Fragment.ordinal)).all()
                        inputs = [FragmentInput(str(f.id), f.locator, f.original_text) for f in fragments]
                    claim_at = time.perf_counter()
                    sub = submissions[str(job_id)]
                    measurements["application_queue_wait_ms"].append((claim_at - sub["queue_committed_at"]) * 1000)
                    begin = time.perf_counter()
                    def fixture_response(**request):
                        # Known finite fixture adapter, not a semantic/model benchmark.
                        import re
                        rows = []
                        for fragment_id, quote in re.findall(r"\[([^ ]+) \|[^\n]+\]\n([^\n]+)", request["user"]):
                            row = observation(quote)
                            row["summary"] = quote
                            row["evidence"][0]["fragment_id"] = fragment_id
                            rows.append(row)
                        return {"observations": rows}
                    results = extract_fragments(inputs, fixture_response)
                    events = [item for result in results for item in result.observations]
                    elapsed = (time.perf_counter() - begin) * 1000
                    measurements[f"{'cold' if phase_number == 1 else 'warm'}:{sub['shape']}:extraction_postprocess_ms"].append(elapsed)
                    assert len(events) == sub["events"]
                    with sessions.begin() as db:
                        for index, item in enumerate(events):
                            db.add(Observation(job_id=job_id, fragment_id=__import__('uuid').UUID(item.evidence[0].fragment_id),
                                               ordinal=index + 1, fields=item.model_dump(mode="json")))
                        publish_stage(db, job_id, token, stage="persist", state="ready_for_review", extracted_count=len(events), proposal_count=0)
                    with lock:
                        completed[str(job_id)] = time.perf_counter()

            def conversation_worker():
                from backend.tests.integration.test_durable_conversations import extraction
                while not stop.is_set():
                    begin = time.perf_counter()
                    if not runtime.run_once(sessions, model_factory=lambda role: extraction):
                        return
                    measurements[f"{'cold' if phase_number == 1 else 'warm'}:conversation_task_ms"].append((time.perf_counter() - begin) * 1000)

            def approval_worker():
                for proposal_id in approval_ids:
                    begin = time.perf_counter()
                    with sessions.begin() as db:
                        approve(proposal_id, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0,
                                idempotency_key=str(proposal_id)), db.get(User, user_id), db)
                    measurements[f"{'cold' if phase_number == 1 else 'warm'}:approval_ms"].append((time.perf_counter() - begin) * 1000)

            def observer():
                with TestClient(app) as client:
                    while not stop.is_set():
                        read_at = time.perf_counter()
                        with sessions() as db:
                            backlog = db.scalar(select(func.count()).select_from(Job).where(Job.state.in_(["queued", "running"])))
                            conv_backlog = db.scalar(select(func.count()).select_from(ConversationTask).where(ConversationTask.state.in_(["queued", "running"])))
                            pending_delivery = db.scalar(select(func.count()).select_from(IntegrationOutbox).where(IntegrationOutbox.status == "pending"))
                        samples.append({"phase": phase, "elapsed_s": read_at - started, "report_backlog": backlog,
                                        "conversation_backlog": conv_backlog, "pending_delivery": pending_delivery})
                        for job_id in phase_jobs:
                            if str(job_id) in completed and not any(row["job_id"] == str(job_id) for row in resources):
                                begin = time.perf_counter()
                                response = client.get(f"/readiness/{job_id}")
                                assert response.status_code == 200 and response.json()["state"] == "ready_for_review"
                                measurements["api_read_ms"].append((time.perf_counter() - begin) * 1000)
                                measurements["api_response_bytes"].append(len(response.content))
                                resources.append({"job_id": str(job_id), "phase": phase, "shape": submissions[str(job_id)]["shape"],
                                    "submission_to_api_visible_ms": (time.perf_counter() - submissions[str(job_id)]["at"]) * 1000})
                        deliver(sessions, Connector(), project_id=project_id)
                        if not backlog and not conv_backlog and not pending_delivery:
                            return
                        if time.perf_counter() - phase_start > 30:
                            raise TimeoutError("bounded phase did not drain")
                        stop.wait(.005)

            with ThreadPoolExecutor(max_workers=4) as workers:
                futures = [workers.submit(guarded, function) for function in [report_worker, conversation_worker, approval_worker, observer]]
                for future in futures:
                    future.result(timeout=40)
            # Approval thread can enqueue after observer's first empty-outbox read.
            while deliver(sessions, Connector(), project_id=project_id):
                pass
            with sessions() as db:
                row_counts.append({"phase": phase, "elapsed_s": time.perf_counter() - phase_start,
                    "observations": db.scalar(select(func.count()).select_from(Observation)),
                    "delivered": db.scalar(select(func.count()).select_from(IntegrationOutbox).where(IntegrationOutbox.status == "delivered")),
                    "approved": db.scalar(select(func.count()).select_from(Proposal).where(Proposal.review_state == "approved")),
                    "conversation_succeeded": db.scalar(select(func.count()).select_from(ConversationTask).where(ConversationTask.state == "succeeded")),
                    "database_bytes": database.stat().st_size,
                    "wal_bytes": Path(str(database) + "-wal").stat().st_size if Path(str(database) + "-wal").exists() else 0,
                    "peak_rss_platform_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
    finally:
        reports_module._store_original = original_store
        engine.dispose()
    def summary(values):
        ordered = sorted(values)
        return {"count": len(values), "min": min(values), "p50": ordered[len(ordered)//2],
                "p95": ordered[min(len(ordered)-1, int(len(ordered)*.95))], "max": max(values)} if values else None
    result = {"status": "completed" if not errors and len(resources) == reports_per_phase * phase_number and row_counts[-1]["conversation_succeeded"] == phase_number * 6 else "incomplete",
        "elapsed_seconds": time.perf_counter() - started,
        "provider_admission_wait_ms": None, "provider_transport_ms": None,
        "provider_note": "No provider transport or admission gate used; unmeasured, not zero.",
        "measurements": {key: summary(values) for key, values in measurements.items()},
        "api_visible_readiness": resources, "queue_samples": samples, "phase_resources": row_counts,
        "peak_checked_out_connections": connections["peak"], "errors": errors,
        "report_completions": len(completed), "submissions": list(submissions.values()),
        "limits": ["SQLite WAL, no PostgreSQL concurrency claim", "Fixture extraction responses, no LLM throughput/accuracy claim",
            "application_cold means first workload on new engine, not OS cache flush",
            "in-process readiness API excludes production authentication and browser paint",
            "burst/drain bounded workload, not sustainable quota-aware capacity or starvation proof",
            "evaluation isolated by separate database; no production capacity reservation policy tested"]}
    scratch.cleanup()
    (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps({"status": result["status"], "completed": result["report_completions"], "errors": result["errors"]}))
    raise SystemExit(0 if result["status"] == "completed" else 1)
