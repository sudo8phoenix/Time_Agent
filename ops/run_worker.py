"""Run the durable PostgreSQL-backed extraction/matching worker."""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db.session import session_factory  # noqa: E402
from app.jobs.pipeline import process_job  # noqa: E402
from app.jobs.service import heartbeat  # noqa: E402
from app.jobs.worker import run_loop, run_once  # noqa: E402
from app.settings import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Process durable report jobs with local Ollama")
    parser.add_argument("--once", action="store_true", help="claim and process at most one job")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")

    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    embedder = _load_embedder()
    settings = get_settings()

    def pipeline(db, job, *, token, should_stop, heartbeat_callback):
        if settings.agent_execution_mode == "graph":
            from app.agent.runtime import process_job_with_graph

            return process_job_with_graph(
                db,
                job,
                token=token,
                session_factory=session_factory,
                database_url=settings.database_url,
                should_stop=should_stop,
                heartbeat_callback=heartbeat_callback,
                embedder=embedder,
            )
        return process_job(db, job, lease_token=token, should_stop=should_stop,
                           heartbeat_callback=heartbeat_callback,
                           embed=embedder)

    def beat(job, token):
        with session_factory() as db:
            owned = heartbeat(db, job.id, token)
            db.commit()
            return owned

    def should_stop():
        return stopping
    if args.once:
        with session_factory() as db:
            return 0 if run_once(db, pipeline, should_stop=should_stop,
                                 heartbeat_callback=beat) else 3
    run_loop(session_factory, pipeline, should_stop=should_stop,
             poll_seconds=args.poll_seconds)
    return 0


def _load_embedder():
    try:
        from app.retrieval.rebuild import LocalEmbeddingModel
        return LocalEmbeddingModel()
    except RuntimeError as exc:
        print(f"Embedding retrieval unavailable; using lexical retrieval: {exc}", file=sys.stderr)
        return None


if __name__ == "__main__":
    raise SystemExit(main())
