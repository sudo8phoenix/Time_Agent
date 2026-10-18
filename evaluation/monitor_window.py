"""Read-only bounded rollout monitoring; records stop criteria, never enables flags."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from time import monotonic, sleep

from sqlalchemy import text

from app.db.session import engine
from app.settings import get_settings
from evaluation.deployment_rehearsal import _validate_target
from ops.runtime_status import build_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()
    if args.output_dir.exists() or not 30 <= args.seconds <= 600:
        parser.error("Use a new directory and a 30–600 second bounded window")
    settings = get_settings()
    _validate_target(settings.database_url)
    args.output_dir.mkdir(parents=True)
    start = monotonic()
    baseline_events = None
    baseline_failures = None
    baseline_conversation_failures = None
    reasons = set()
    samples = 0
    while True:
        with engine.connect() as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            report = build_report(db, settings)
            events = db.execute(text("SELECT COUNT(*) FROM progress_events")).scalar_one()
            failures = report["jobs"]["by_state"].get("failed", 0)
            conversation_failures = report["conversation_tasks"]["by_state"].get("failed", 0)
            long_running = db.execute(text("SELECT COUNT(*) FROM jobs WHERE state='running' AND created_at < CURRENT_TIMESTAMP - interval '120 seconds'")).scalar_one()
            old_conversations = db.execute(text("SELECT COUNT(*) FROM conversation_tasks WHERE state IN ('queued','running') AND created_at < CURRENT_TIMESTAMP - interval '120 seconds'")).scalar_one()
            expired_conversations = db.execute(text("SELECT COUNT(*) FROM conversation_tasks WHERE state='running' AND lease_expires_at < CURRENT_TIMESTAMP")).scalar_one()
        if baseline_events is None:
            baseline_events, baseline_failures = events, failures
            baseline_conversation_failures = conversation_failures
        if events != baseline_events:
            reasons.add("UNEXPECTED_APPROVED_PROGRESS_WRITE")
        if failures > baseline_failures:
            reasons.add("NEW_FAILED_REPORT")
        if conversation_failures > baseline_conversation_failures:
            reasons.add("NEW_FAILED_CONVERSATION")
        if old_conversations:
            reasons.add("CONVERSATION_READINESS_EXCEEDS_120_SECONDS")
        if expired_conversations:
            reasons.add("EXPIRED_CONVERSATION_OWNERSHIP")
        if report["jobs"]["expired_running_ownership_count"]:
            reasons.add("EXPIRED_WORKER_OWNERSHIP")
        if long_running:
            reasons.add("REPORT_READINESS_EXCEEDS_120_SECONDS")
        if any(report["rollout_configuration"][key] for key in ("agent_hierarchy_enabled", "orchestrator_model_assisted")):
            reasons.add("UNEXPECTED_ROLLOUT_FLAG")
        if any((row.get("cooldown_remaining_seconds") or 0) > 90
               for row in report["hosted_provider_admission"].values()):
            reasons.add("PROVIDER_COOLDOWN_EXCEEDS_CAPTURE_REQUEST_BUDGET")
        sample = {"elapsed_seconds": round(monotonic()-start, 3), "long_running_reports": long_running,
            "over_budget_conversations": old_conversations, "expired_conversations": expired_conversations,
            "approved_progress_event_count": events, "runtime": report, "stop_reasons": sorted(reasons)}
        with (args.output_dir/"samples.jsonl").open("a") as stream:
            stream.write(json.dumps(sample)+"\n")
        samples += 1
        if monotonic()-start >= args.seconds:
            break
        sleep(max(0, min(5, args.seconds-(monotonic()-start))))
    result = {"finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "stop_criteria_observed" if reasons else "bounded_baseline_window_completed",
        "duration_seconds": round(monotonic()-start, 3), "sample_count": samples,
        "stop_reasons": sorted(reasons), "rollout_flags_enabled": False,
        "action": "Do not advance rollout; retain bounded diagnostic capture" if reasons else "Retain baseline evidence; no rollout enablement authorized by this monitor",
        "limitations": [f"A {args.seconds}-second local monitoring window alone does not establish sustained deployment acceptance.",
            "Monitor is read-only; it does not kill workers or accept progress.",
            "Conversation rollback/recovery has separate populated-state evidence."]}
    (args.output_dir/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
