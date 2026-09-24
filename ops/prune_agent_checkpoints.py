"""Safely prune durable checkpoints for old, non-resumable terminal graph runs."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path

from sqlalchemy import MetaData, Table, and_, delete, func, or_, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db.models import (  # noqa: E402
    AgentRun,
    AgentStep,
    AgentToolCall,
    Job,
    Observation,
    Proposal,
)
from app.db.session import engine, session_factory  # noqa: E402
from app.jobs.service import MAX_ATTEMPTS  # noqa: E402


def _counts(db, table: Table, thread_ids: list[str]) -> int:
    if not thread_ids:
        return 0
    return int(db.scalar(select(func.count()).select_from(table).where(
        table.c.thread_id.in_(thread_ids)
    )) or 0)


def prune(*, age: timedelta, execute: bool, limit: int = 100) -> dict:
    if age.total_seconds() <= 0:
        raise ValueError("age must be positive")
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    cutoff = datetime.now(timezone.utc) - age
    metadata = MetaData()
    writes = Table("checkpoint_writes", metadata, autoload_with=engine)
    checkpoints = Table("checkpoints", metadata, autoload_with=engine)
    blobs = Table("checkpoint_blobs", metadata, autoload_with=engine)

    with session_factory.begin() as db:
        retry_exhausted = and_(
            AgentRun.state.in_(("failed", "stale")),
            Job.state == AgentRun.state,
            Job.attempts >= MAX_ATTEMPTS,
        )
        ready = and_(
            AgentRun.state == "ready_for_review",
            Job.state == "ready_for_review",
        )
        candidates = list(db.execute(select(AgentRun, Job).join(
            Job, AgentRun.job_id == Job.id
        ).where(
            AgentRun.completed_at.is_not(None),
            AgentRun.completed_at <= cutoff,
            Job.lease_token.is_(None),
            Job.lease_expires_at.is_(None),
            or_(ready, retry_exhausted),
        ).order_by(AgentRun.completed_at, AgentRun.id).limit(limit).with_for_update()).all())

        eligible: list[str] = []
        run_ids: list[str] = []
        for run, job in candidates:
            running_steps = int(db.scalar(select(func.count()).select_from(AgentStep).where(
                AgentStep.run_id == run.id,
                AgentStep.state == "running",
            )) or 0)
            running_tools = int(db.scalar(select(func.count()).select_from(AgentToolCall).join(
                AgentStep, AgentToolCall.step_id == AgentStep.id
            ).where(
                AgentStep.run_id == run.id,
                AgentToolCall.state == "running",
            )) or 0)
            observation_count = int(db.scalar(select(func.count()).select_from(Observation).where(
                Observation.job_id == job.id
            )) or 0)
            proposal_count = int(db.scalar(select(func.count()).select_from(Proposal).join(
                Observation, Proposal.observation_id == Observation.id
            ).where(Observation.job_id == job.id)) or 0)
            terminal_node = "finalize" if run.state == "ready_for_review" else "record_failure"
            terminal_trace = int(db.scalar(select(func.count()).select_from(AgentStep).where(
                AgentStep.run_id == run.id,
                AgentStep.node == terminal_node,
                AgentStep.state == "succeeded",
            )) or 0)
            if running_steps or running_tools or terminal_trace != 1:
                continue
            if run.state == "ready_for_review":
                if (
                    observation_count != job.extracted_count
                    or proposal_count != job.proposal_count
                ):
                    continue
            elif observation_count or proposal_count:
                continue
            if run.thread_id != str(run.id):
                continue
            eligible.append(run.thread_id)
            run_ids.append(str(run.id))

        before = {
            "checkpoint_writes": _counts(db, writes, eligible),
            "checkpoints": _counts(db, checkpoints, eligible),
            "checkpoint_blobs": _counts(db, blobs, eligible),
        }
        deleted = {key: 0 for key in before}
        if execute and eligible:
            # One transaction and dependent-first ordering.  Application/domain
            # records and the migration ledger are never touched.
            deleted["checkpoint_writes"] = int(db.execute(delete(writes).where(
                writes.c.thread_id.in_(eligible)
            )).rowcount or 0)
            deleted["checkpoints"] = int(db.execute(delete(checkpoints).where(
                checkpoints.c.thread_id.in_(eligible)
            )).rowcount or 0)
            deleted["checkpoint_blobs"] = int(db.execute(delete(blobs).where(
                blobs.c.thread_id.in_(eligible)
            )).rowcount or 0)
            if deleted != before:
                raise RuntimeError("checkpoint deletion count changed during the locked prune")
        return {
            "mode": "execute" if execute else "dry-run",
            "cutoff": cutoff.isoformat(),
            "run_ids": run_ids,
            "thread_ids": eligible,
            "checkpoint_rows": before,
            "deleted_rows": deleted,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--age-hours", type=float, required=True)
    parser.add_argument("--limit", type=int, default=100)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.age_hours <= 0:
        parser.error("--age-hours must be positive")
    result = prune(
        age=timedelta(hours=args.age_hours),
        execute=bool(args.execute),
        limit=args.limit,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
