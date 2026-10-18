"""Rehearse worker recovery using synthetic reports in an isolated PostgreSQL DB.

This starts exactly two real ``ops/run_worker.py`` subprocesses with runtime
hierarchy flags disabled. Two v2 runs are pinned before launch so the worker
must resume those runs from their persisted configuration; two later jobs use
the v1 graph. The script never approves proposals or removes fixture data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
WORKER = ROOT / "ops" / "run_worker.py"
CASE_IDS = ("C01", "C02", "C03", "C18")
FREE_PLANNER = "nvidia/nemotron-3.5-super-vl:free"
TERMINAL_STATES = {"ready_for_review", "needs_transcription", "failed", "stale", "cancelled"}
REQUIRED_TABLES = {
    "projects", "schedule_versions", "activities", "reports", "fragments",
    "jobs", "agent_runs", "observations", "proposals", "progress_events",
    "activity_states", "checkpoints", "checkpoint_blobs", "checkpoint_writes",
    "agent_tasks", "conversation_tasks", "conversation_task_calls", "hosted_provider_admission",
}
SECRET_ENV_NAMES = (
    "GROQ_API_KEY", "GROQ_API_KEY_1", "GROQ_API_KEY_2", "OPENROUTER_API_KEY",
    "OLLAMA_API_KEY",
)

sys.path.insert(0, str(BACKEND))

from app.agent import runtime  # noqa: E402
from app.db.models import AgentRun, ConversationTask, Job, Observation, ProgressEvent, Project, Proposal, Report  # noqa: E402
from app.jobs.service import enqueue_job  # noqa: E402
from app.settings import get_settings  # noqa: E402
from evaluation.report_planner_eval import load_cases, seed  # noqa: E402


def _validate_target(database_url: str) -> None:
    try:
        url = make_url(database_url)
    except Exception:
        raise ValueError("DATABASE_URL is invalid") from None
    if (url.drivername not in {"postgresql+psycopg", "postgresql"} or
            url.host not in {"127.0.0.1", "localhost", "::1"} or
            not url.database or not re.fullmatch(r"progress_rehearsal_[A-Za-z0-9_]+", url.database)):
        raise ValueError("DATABASE_URL must target a local progress_rehearsal_* PostgreSQL database")


def _ensure_migrated(engine) -> None:
    try:
        names = set(inspect(engine).get_table_names())
    except Exception:
        raise RuntimeError("Isolated rehearsal database is unavailable") from None
    missing = REQUIRED_TABLES - names
    if missing:
        raise RuntimeError("Database is not migrated for worker/checkpoint execution")
    with engine.connect() as db:
        if db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != "0018_hosted_admission":
            raise RuntimeError("Rehearsal requires the verified 0018 migration head")


def _settings_for_rehearsal(database_url: str):
    original = get_settings()
    return original.model_copy(update={
        "database_url": database_url,
        "report_model_timeout_seconds": 90,
        "llm_provider": "groq",
        "groq_model": original.groq_model,
        "orchestrator_provider": "openrouter",
        "orchestrator_model": FREE_PLANNER,
        "orchestrator_key_slot": 0,
        "extraction_provider": "groq",
        "extraction_model": original.groq_model,
        "extraction_key_slot": 0,
        "selection_provider": "groq",
        "selection_model": original.groq_model,
        "selection_key_slot": 0,
        "agent_hierarchy_enabled": False,
        "orchestrator_model_assisted": False,
    })


def _worker_environment(database_url: str, settings) -> tuple[dict[str, str], list[str]]:
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": database_url,
        "LLM_PROVIDER": "groq",
        "GROQ_MODEL": settings.groq_model,
        "ORCHESTRATOR_PROVIDER": "openrouter",
        "ORCHESTRATOR_MODEL": FREE_PLANNER,
        "ORCHESTRATOR_KEY_SLOT": "0",
        "EXTRACTION_PROVIDER": "groq",
        "EXTRACTION_MODEL": settings.groq_model,
        "EXTRACTION_KEY_SLOT": "0",
        "SELECTION_PROVIDER": "groq",
        "SELECTION_MODEL": settings.groq_model,
        "SELECTION_KEY_SLOT": "0",
        "AGENT_HIERARCHY_ENABLED": "false",
        "ORCHESTRATOR_MODEL_ASSISTED": "false",
        "REPORT_MODEL_TIMEOUT_SECONDS": "90",
    })
    secret_values = []
    for name in SECRET_ENV_NAMES:
        value = getattr(settings, name.lower(), None)
        raw = value.get_secret_value() if value else None
        if raw:
            env[name] = raw
            secret_values.append(raw)
    # This rehearsal has no provider fallback. Fail before creating work if the
    # required Groq slot or model-assisted planner credential is unavailable.
    if not env.get("GROQ_API_KEY") or not env.get("OPENROUTER_API_KEY"):
        raise RuntimeError("Groq slot 0 and OpenRouter credentials are required")
    env["PYTHONPATH"] = str(BACKEND) + os.pathsep + env.get("PYTHONPATH", "")
    return env, secret_values


def _redact(text: str, secrets: list[str]) -> str:
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def _snapshot(sessions, project_id: UUID, job_ids: list[UUID], *, started_monotonic: float,
              terminal_observed: dict[str, float]) -> dict[str, Any]:
    elapsed = round(time.monotonic() - started_monotonic, 3)
    with sessions() as db:
        jobs = list(db.scalars(select(Job).where(Job.id.in_(job_ids)).order_by(Job.created_at)))
        rows = []
        for job in jobs:
            run = db.scalar(select(AgentRun).where(AgentRun.job_id == job.id))
            observations = int(db.scalar(select(func.count()).select_from(Observation).where(
                Observation.job_id == job.id)) or 0)
            proposals = int(db.scalar(select(func.count()).select_from(Proposal).join(
                Observation, Proposal.observation_id == Observation.id).where(
                    Observation.job_id == job.id)) or 0)
            rows.append({
                "job_id": str(job.id), "report_id": str(job.report_id), "state": job.state,
                "stage": job.stage, "attempts": job.attempts, "error_code": job.error_code,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
                "observed_elapsed_seconds": elapsed,
                "graph_version": run.graph_version if run else None,
                "run_state": run.state if run else None,
                "observation_count": observations, "proposal_count": proposals,
            })
            if job.state in TERMINAL_STATES:
                terminal_observed.setdefault(str(job.id), elapsed)
            rows[-1]["terminal_observed_elapsed_seconds"] = terminal_observed.get(str(job.id))
        ledger_count = int(db.scalar(select(func.count()).select_from(ProgressEvent).join(
            Proposal, ProgressEvent.proposal_id == Proposal.id).where(
                Proposal.project_id == project_id)) or 0)
        return {"captured_at": datetime.now(timezone.utc).isoformat(), "jobs": rows,
                "approved_progress_event_count": ledger_count}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def run(output_dir: Path, database_url: str, deadline_seconds: int, *, case_ids=CASE_IDS) -> int:
    if not case_ids or len(set(case_ids)) != len(case_ids) or not set(case_ids) <= set(CASE_IDS):
        raise ValueError("Choose unique rehearsal case identifiers from the bounded fixture")
    _validate_target(database_url)
    if os.path.lexists(output_dir):
        raise ValueError("--output-dir must be a new path")
    settings = _settings_for_rehearsal(database_url)
    worker_env, secrets = _worker_environment(database_url, settings)
    engine = create_engine(database_url, pool_pre_ping=True)
    _ensure_migrated(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as db:
        busy_jobs = db.scalar(select(func.count()).select_from(Job).where(Job.state.in_(("queued", "running"))))
        busy_tasks = db.scalar(select(func.count()).select_from(ConversationTask).where(ConversationTask.state.in_(("queued", "running"))))
        if busy_jobs or busy_tasks:
            raise RuntimeError("Rehearsal database contains pending work; isolate it before starting")

    output_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    project_id: UUID | None = None
    job_ids: list[UUID] = []
    report_ids: list[UUID] = []
    worker_processes: list[subprocess.Popen] = []
    worker_files: list[tuple[Path, Any, Any]] = []
    snapshots: list[dict[str, Any]] = []
    terminal_observed: dict[str, float] = {}
    exit_codes: list[int | None] = []
    failure: str | None = None
    timed_out = False

    # Open temporary captures outside the evidence directory; sanitized copies
    # are written to the new output directory in the finally block.
    try:
        cases = load_cases(case_ids=case_ids, dataset="seed")
        project_id, _schedule_id = seed(sessions, cases)
        report_ids = [UUID(str(case["report_id"])) for case in cases]

        # Enqueue the first two reports and pin their graph-v2 runs while the
        # hierarchy config is enabled. The child workers will start with both
        # runtime flags disabled; process_job_with_graph honors the persisted
        # run version and provider role snapshot.
        hierarchy_settings = settings.model_copy(update={
            "agent_hierarchy_enabled": True,
            "orchestrator_model_assisted": True,
        })
        for index, case in enumerate(cases):
            with sessions.begin() as db:
                project = db.get(Project, project_id)
                report = db.get(Report, UUID(str(case["report_id"])))
                job, _existing = enqueue_job(db, project, report)
                job_ids.append(job.id)
                if case["case_id"] in CASE_IDS[:2]:
                    prior_get_settings = runtime.get_settings
                    runtime.get_settings = lambda: hierarchy_settings
                    try:
                        run_record = runtime._create_or_load_run(db, job, clock=lambda: datetime.now(timezone.utc))
                        if run_record.graph_version != "report-analysis-v2":
                            raise RuntimeError("Failed to pin hierarchical run")
                    finally:
                        runtime.get_settings = prior_get_settings

        if len(job_ids) != len(case_ids):
            raise RuntimeError("Synthetic fixture did not create the requested jobs")

        _write_json(output_dir / "fixture.json", {
            "dataset": "seed", "case_ids": list(case_ids), "project_id": str(project_id),
            "report_ids": [str(value) for value in report_ids],
            "job_ids": [str(value) for value in job_ids],
            "pinned_graph_versions": ["report-analysis-v2" if c in CASE_IDS[:2] else "report-analysis-v1" for c in case_ids],
            "worker_runtime_flags": {"agent_hierarchy_enabled": False, "orchestrator_model_assisted": False},
            "provider_policy": {"v1": "groq slot 0", "v2 specialists": "groq slot 0",
                                "v2 planner": FREE_PLANNER},
        })

        for index in range(2):
            stdout_temp = tempfile.TemporaryFile(mode="w+b")
            stderr_temp = tempfile.TemporaryFile(mode="w+b")
            worker_files.append((output_dir / f"worker-{index + 1}.stdout.txt", stdout_temp, stderr_temp))
            worker_processes.append(subprocess.Popen(
                [sys.executable, str(WORKER), "--poll-seconds", "1"], cwd=ROOT,
                env=worker_env, stdout=stdout_temp, stderr=stderr_temp, close_fds=True,
            ))

        deadline = started + deadline_seconds
        while time.monotonic() < deadline:
            snapshot = _snapshot(sessions, project_id, job_ids,
                                 started_monotonic=started, terminal_observed=terminal_observed)
            snapshots.append(snapshot)
            _write_json(output_dir / "worker-snapshots.json", snapshots)
            if len(snapshot["jobs"]) == len(job_ids) and all(row["state"] in TERMINAL_STATES for row in snapshot["jobs"]):
                break
            if any(proc.poll() is not None for proc in worker_processes):
                failure = "Worker exited before all jobs completed"
                break
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        else:
            timed_out = True
        final_snapshot = _snapshot(sessions, project_id, job_ids,
                                   started_monotonic=started, terminal_observed=terminal_observed)
        snapshots.append(final_snapshot)
        _write_json(output_dir / "worker-snapshots.json", snapshots)
        for proc in worker_processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in worker_processes:
            try:
                exit_codes.append(proc.wait(timeout=8))
            except subprocess.TimeoutExpired:
                proc.kill()
                exit_codes.append(proc.wait(timeout=3))
        failed_rows = [row for row in final_snapshot["jobs"] if row["state"] not in {"ready_for_review"}]
        if failed_rows:
            failure = "One or more jobs did not reach ready_for_review"
    except KeyboardInterrupt:
        failure = "Rehearsal interrupted before completion"
    except Exception as exc:
        # Persist only an exception class and controlled message; never serialize
        # provider exception text, URLs, environment, or credential values.
        failure = f"{type(exc).__name__}: rehearsal setup or execution failed"
        try:
            if project_id is not None and job_ids:
                final_snapshot = _snapshot(sessions, project_id, job_ids,
                                           started_monotonic=started, terminal_observed=terminal_observed)
                snapshots.append(final_snapshot)
                _write_json(output_dir / "worker-snapshots.json", snapshots)
        except Exception:
            pass
    finally:
        for proc in worker_processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in worker_processes:
            if proc.poll() is None:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
        for name, stdout_temp, stderr_temp in worker_files:
            stdout_temp.seek(0)
            stderr_temp.seek(0)
            stdout_text = _redact(stdout_temp.read().decode("utf-8", errors="replace"), secrets)
            stderr_text = _redact(stderr_temp.read().decode("utf-8", errors="replace"), secrets)
            name.write_text(stdout_text)
            name.with_name(name.name.replace("stdout", "stderr")).write_text(stderr_text)
            stdout_temp.close()
            stderr_temp.close()
        final_snapshot = _snapshot(sessions, project_id, job_ids, started_monotonic=started,
                                   terminal_observed=terminal_observed) if project_id is not None and job_ids else {
            "jobs": [], "approved_progress_event_count": None}
        ledger_zero = final_snapshot.get("approved_progress_event_count") == 0
        if any(row["state"] != "ready_for_review" for row in final_snapshot.get("jobs", [])):
            failure = failure or "One or more jobs did not reach ready_for_review"
        if any(proc.returncode != 0 for proc in worker_processes):
            failure = failure or "Worker process did not exit cleanly"
        result = {
            "status": "timed_out" if timed_out else "failed" if failure else "completed",
            "started_at": datetime.fromtimestamp(time.time() - (time.monotonic() - started), timezone.utc).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "deadline_seconds": deadline_seconds,
            "worker_count": 2,
            "maximum_observed_running_jobs": max((sum(row["state"] == "running" for row in item["jobs"])
                                                   for item in snapshots), default=0),
            "worker_returncodes": exit_codes + [proc.returncode for proc in worker_processes[len(exit_codes):]],
            "fixture_project_id": str(project_id) if project_id else None,
            "report_ids": [str(value) for value in report_ids],
            "job_ids": [str(value) for value in job_ids],
            "jobs": final_snapshot.get("jobs", []),
            "approved_progress_event_count": final_snapshot.get("approved_progress_event_count"),
            "zero_approved_ledger_writes_assertion": ledger_zero,
            "failed_or_timeout_jobs": [row for row in final_snapshot.get("jobs", [])
                                       if row.get("state") not in {"ready_for_review"}],
            "failure": failure,
            "cleanup": "fixture intentionally retained; no fixture/database cleanup performed",
        }
        _write_json(output_dir / "result.json", result)
        engine.dispose()
    return 0 if not failure and not timed_out and ledger_zero else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--deadline-seconds", type=int, default=900)
    parser.add_argument("--case-ids", nargs="+", choices=CASE_IDS, default=list(CASE_IDS))
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""),
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.deadline_seconds <= 900:
        parser.error("--deadline-seconds must be between 1 and 900")
    if not args.database_url:
        parser.error("DATABASE_URL must target a migrated local progress_rehearsal_* database")
    try:
        return run(args.output_dir, args.database_url, args.deadline_seconds, case_ids=tuple(args.case_ids))
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
