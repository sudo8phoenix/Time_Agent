"""Controlled synthetic transport/ownership faults; no live provider calls."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select

from app.agent import runtime
from app.db.models import Job, Observation, ProgressEvent, Proposal
from app.db.session import session_factory
from app.jobs.service import heartbeat
from app.jobs.worker import run_once
from app.llm.ollama import OllamaTransportError
from app.settings import get_settings
from evaluation.runtime_probe import observe_ownership, renewing_lease


def scenario(fixture, *, hierarchical, worker, replace_lease):
    settings = get_settings()
    original_flag = settings.agent_hierarchy_enabled
    original_model = fixture.model
    settings.agent_hierarchy_enabled = hierarchical
    result = {}
    ownership = []
    def model(**kwargs):
        if "candidate_ids" in kwargs["schema"].get("properties", {}):
            if replace_lease:
                with session_factory.begin() as db:
                    db.get(Job, fixture.job_id).lease_token = uuid4().hex
            raise OllamaTransportError("Synthetic retrieval interruption")
        return original_model(**kwargs)
    fixture.model = model
    def execute(db, job, *, token, should_stop, heartbeat_callback):
        nonlocal result, ownership
        if job.id != fixture.job_id:
            raise RuntimeError("Fault probe claimed unrelated work")
        with observe_ownership(runtime, session_factory, job.id, token) as ownership:
            try:
                result = runtime.process_job_with_graph(db, job, token=token,
                    session_factory=session_factory, database_url=settings.database_url,
                    should_stop=should_stop, heartbeat_callback=heartbeat_callback,
                    model_callable=model)
            except runtime.AgentRuntimeError as error:
                result = {"state": "interrupted", "error_code": error.code}
                raise
        return result
    try:
        if worker:
            with session_factory.begin() as db:
                job = db.get(Job, fixture.job_id)
                job.state, job.lease_token, job.lease_expires_at = "queued", None, None
            def beat(job, token):
                with session_factory.begin() as db:
                    return heartbeat(db, job.id, token)
            with session_factory() as db:
                run_once(db, execute, heartbeat_callback=beat)
        else:
            with renewing_lease(session_factory, fixture.job_id, fixture.token) as (beat, lost):
                with session_factory() as db:
                    try:
                        execute(db, db.get(Job, fixture.job_id), token=fixture.token,
                                should_stop=lost, heartbeat_callback=beat)
                    except runtime.AgentRuntimeError:
                        pass
        with session_factory() as db:
            job = db.get(Job, fixture.job_id)
            observations = select(Observation.id).where(Observation.job_id == job.id)
            proposals = db.scalar(select(func.count()).select_from(Proposal).where(Proposal.observation_id.in_(observations)))
            ledger = db.scalar(select(func.count()).select_from(ProgressEvent).where(ProgressEvent.observation_id.in_(observations)))
            row = {"graph_version": "v2" if hierarchical else "v1",
                "execution": "production_worker" if worker else "direct_with_heartbeat",
                "fault": "transport_plus_lease_replacement" if replace_lease else "transport_only",
                "result_state": result.get("state"), "error_code": result.get("error_code"),
                "persisted_job_state": job.state, "proposals": proposals, "ledger_writes": ledger,
                "ownership_checks": ownership}
        expected_code = "JOB_LEASE_LOST" if replace_lease else "AGENT_TOOL_FAILED"
        assert row["error_code"] == expected_code, row
        assert row["proposals"] == row["ledger_writes"] == 0
        assert any(e["phase"] == "check_failed" for e in ownership) == replace_lease
        return row
    finally:
        fixture.model = original_model
        settings.agent_hierarchy_enabled = original_flag


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    from sqlalchemy.engine import make_url
    url = make_url(get_settings().database_url)
    if url.host not in {"127.0.0.1", "localhost"} or url.database != "progress_test":
        raise SystemExit("Use only the isolated local progress_test database")
    if args.output_dir.exists():
        raise SystemExit("Use a new evidence directory")
    args.output_dir.mkdir(parents=True)
    # Reuse the deterministic repository fixture, including its cleanup, rather
    # than inventing another schedule/extraction contract for this fault probe.
    from backend.tests.integration.agent.test_agent_runtime import RuntimeFixture
    rows = []
    for hierarchical in (False, True):
        for worker in (False, True):
            for replace_lease in (False, True):
                fixture = RuntimeFixture()
                try:
                    row = scenario(fixture, hierarchical=hierarchical, worker=worker, replace_lease=replace_lease)
                    rows.append(row)
                    with (args.output_dir / "scenarios.jsonl").open("a") as stream:
                        stream.write(json.dumps(row) + "\n")
                finally:
                    fixture.cleanup()
    summary = {"captured_at": datetime.now(timezone.utc).isoformat(), "scenarios": len(rows),
        "transport_only_lease_loss": sum(r["fault"] == "transport_only" and r["error_code"] == "JOB_LEASE_LOST" for r in rows),
        "replacement_detected": sum(r["fault"] == "transport_plus_lease_replacement" and r["error_code"] == "JOB_LEASE_LOST" for r in rows),
        "proposals": sum(r["proposals"] for r in rows), "ledger_writes": sum(r["ledger_writes"] for r in rows),
        "historical_root_cause": "not_established_by_original_capture"}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
