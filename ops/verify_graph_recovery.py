"""Seed or resume injected-model checkpoints in a separate recovery database."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/tests/integration/agent"))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from app.db.models import AgentRun, Job, Observation, Proposal  # noqa: E402
from app.db.session import session_factory  # noqa: E402
from app.jobs.worker import WorkerShutdown  # noqa: E402
from app.settings import get_settings  # noqa: E402
from test_agent_runtime import RuntimeFixture, _stop_on_check  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "resume"))
    parser.add_argument("metadata", type=Path)
    args = parser.parse_args()
    url = make_url(get_settings().database_url)
    if url.host not in {"127.0.0.1", "localhost"} or not (url.database or "").startswith(
        ("progress_recovery_", "progress_restore_")
    ):
        parser.error("Use a separate local recovery/restore database")
    if args.action == "seed":
        if args.metadata.exists():
            parser.error("Seed metadata already exists; use a new path")
        fixture = RuntimeFixture()
        try:
            fixture.run(should_stop=_stop_on_check(5))
        except WorkerShutdown:
            pass
        else:
            raise RuntimeError("Expected interruption after durable extraction")
        fields = ("project_id", "schedule_id", "report_id", "fragment_id", "activity_id", "job_id")
        metadata = {name: str(getattr(fixture, name)) for name in fields}
        metadata["fixture_kind"] = "injected_model_graph_recovery"
        metadata["completed_model_calls"] = list(fixture.calls)
        args.metadata.parent.mkdir(parents=True, exist_ok=True)
        args.metadata.write_text(json.dumps(metadata, indent=2) + "\n")
        print(json.dumps({"seeded": True, "job_id": metadata["job_id"],
                          "completed_model_calls": fixture.calls}))
        return
    metadata = json.loads(args.metadata.read_text())
    fixture = RuntimeFixture.__new__(RuntimeFixture)
    for name in ("project_id", "schedule_id", "report_id", "fragment_id", "activity_id", "job_id"):
        setattr(fixture, name, UUID(metadata[name]))
    fixture.token, fixture.calls, fixture.lifecycle = uuid4().hex, [], False
    with session_factory.begin() as db:
        job = db.get(Job, fixture.job_id)
        if job is None or job.state != "running":
            raise RuntimeError("Expected an interrupted restored graph job")
        job.lease_token = fixture.token
        job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        job.heartbeat_at = datetime.now(timezone.utc)
    result = fixture.run()
    if result["state"] != "ready_for_review" or "extraction" in fixture.calls:
        raise RuntimeError("Restored graph failed to resume without re-extracting")
    with session_factory() as db:
        runs = db.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.job_id == fixture.job_id))
        observations = db.scalar(select(func.count()).select_from(Observation).where(Observation.job_id == fixture.job_id))
        proposals = db.scalar(select(func.count()).select_from(Proposal).join(Observation).where(Observation.job_id == fixture.job_id))
    if (runs, observations, proposals) != (1, 1, 1):
        raise RuntimeError("Restored graph produced duplicate or missing output")
    print(json.dumps({"resumed": True, "result": result, "additional_model_calls": fixture.calls,
                      "runs": runs, "observations": observations, "proposals": proposals}))


if __name__ == "__main__":
    main()
