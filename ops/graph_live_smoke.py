"""Run one synthetic report through the configured live model and durable graph."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
from time import monotonic
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from app.agent.runtime import FRAMEWORK_VERSION, process_job_with_graph  # noqa: E402
from app.db.models import Activity, AgentRun, AgentStep, Job, ProgressEvent, Project, Proposal, Observation, ScheduleVersion  # noqa: E402
from app.db.session import session_factory  # noqa: E402
from app.ingest.reports import ingest_report  # noqa: E402
from app.jobs.service import enqueue_job, heartbeat  # noqa: E402
from app.jobs.worker import run_once  # noqa: E402
from app.llm.ollama import OllamaChatAdapter  # noqa: E402
from app.settings import get_settings  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Explicitly authorize a live model request")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    url = make_url(settings.database_url)
    if not args.run:
        parser.error("Pass --run to call the configured live model")
    if url.host not in {"127.0.0.1", "localhost"} or not (url.database or "").startswith("progress_graph_smoke_"):
        parser.error("Use a separate local progress_graph_smoke_* database")
    if args.output.exists():
        parser.error("Output exists; choose a new evidence path")
    health = OllamaChatAdapter(
        settings.ollama_base_url, settings.ollama_model, timeout=15, max_retries=0,
        bearer_token=settings.ollama_api_key.get_secret_value() if settings.ollama_api_key else None,
    ).health()
    if not health["ok"]:
        raise RuntimeError("Configured model is not available")
    text = "Installed 2 m of cable for activity GRAPH-CABLE-01 in Area A on 2026-10-12."
    with session_factory.begin() as db:
        project = Project(name=f"Synthetic live graph smoke {uuid4().hex[:8]}", timezone="Asia/Kolkata")
        db.add(project)
        db.flush()
        version = ScheduleVersion(project_id=project.id, version_number=1,
                                  content_sha256=uuid4().hex + uuid4().hex, state="active")
        db.add(version)
        db.flush()
        project.active_schedule_version_id = version.id
        db.add(Activity(schedule_version_id=version.id, external_id="GRAPH-CABLE-01",
                        name="Install cable in Area A", wbs="SMOKE/AREA-A", area="Area A",
                        discipline="electrical", work_type="cable_laying", is_leaf=True,
                        measurement_basis="quantity_ratio", planned_quantity=Decimal("100"),
                        baseline_quantity=Decimal("0"), baseline_date=date(2026, 10, 12), unit="m"))
        report, _ = ingest_report(db, project, text.encode(), filename="synthetic-graph-smoke.txt",
                                 report_date=date(2026, 10, 12), report_date_evidence="Explicit report text",
                                 source_label="Synthetic graph smoke")
        job, _ = enqueue_job(db, project, report)
        job.config_snapshot = {"execution_mode": "graph", "model": settings.ollama_model}
        job_id, project_id = job.id, project.id

    def beat(job, token):
        with session_factory.begin() as db:
            return heartbeat(db, job.id, token)

    def pipeline(db, job, *, token, should_stop, heartbeat_callback):
        if job.id != job_id:
            raise RuntimeError("Smoke database has unrelated queued work")
        return process_job_with_graph(db, job, token=token, session_factory=session_factory,
                                      database_url=settings.database_url, should_stop=should_stop,
                                      heartbeat_callback=heartbeat_callback)

    started = monotonic()
    with session_factory() as db:
        worked = run_once(db, pipeline, heartbeat_callback=beat)
    elapsed = round(monotonic() - started, 3)
    with session_factory() as db:
        job = db.get(Job, job_id)
        run = db.scalar(select(AgentRun).where(AgentRun.job_id == job_id))
        steps = list(db.scalars(select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.ordinal))) if run else []
        proposals = list(db.scalars(select(Proposal).join(Observation).where(Observation.job_id == job_id)))
        accepted = db.scalar(select(func.count()).select_from(ProgressEvent).join(Activity).where(Activity.schedule_version_id == job.schedule_version_id))
        evidence = {
            "recorded_at": datetime.now(timezone.utc).isoformat(), "kind": "synthetic_live_graph_smoke",
            "accuracy_benchmark": False, "model_health": health, "framework_version": FRAMEWORK_VERSION,
            "job_id": str(job_id), "project_id": str(project_id), "worked": worked,
            "state": job.state, "error_code": job.error_code, "elapsed_seconds": elapsed,
            "extracted_count": job.extracted_count, "proposal_count": job.proposal_count,
            "accepted_events": accepted, "model_metadata": run.model_metadata if run else {},
            "prompt_metadata": run.prompt_metadata if run else {}, "config_metadata": run.config_metadata if run else {},
            "steps": [{"node": step.node, "state": step.state, "attempt": step.attempt,
                       "duration_ms": step.duration_ms, "error_code": step.error_code} for step in steps],
            "proposals": [{"id": str(proposal.id), "review_state": proposal.review_state,
                           "chosen_activity_id": str(proposal.chosen_activity_id) if proposal.chosen_activity_id else None,
                           "mapping_state": proposal.mapping_state, "warnings": proposal.warnings,
                           "proposed_effects": proposal.proposed_effects} for proposal in proposals],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, default=str) + "\n")
    print(json.dumps({"state": evidence["state"], "elapsed_seconds": elapsed,
                      "proposals": len(proposals), "accepted_events": accepted,
                      "evidence": str(args.output)}))
    if not worked or evidence["state"] != "ready_for_review" or not proposals or accepted:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
