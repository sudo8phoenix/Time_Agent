"""Read-only, allow-listed runtime and rollout status report.

Run from the repository root with ``PYTHONPATH=backend python ops/runtime_status.py``.
Only aggregates and explicitly selected safe fields are emitted.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import bindparam, text

from app.db.session import engine
from app.settings import get_settings


TABLES = {
    "jobs": "jobs",
    "agent_runs": "agent_runs",
    "conversation_tasks": "conversation_tasks",
    "hosted_provider_admission": "hosted_provider_admission",
}
SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
SAFE_STATE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
KNOWN_STATES = {
    "jobs": {"queued", "running", "ready_for_review", "needs_transcription", "failed", "cancelled", "stale"},
    "agent_runs": {"created", "running", "ready_for_review", "failed", "stale", "cancelled"},
    "conversation_tasks": {"queued", "running", "succeeded", "failed", "stale", "cancelled"},
}


def _safe_code(value):
    """Return a bounded application error code, never an arbitrary DB string."""
    if isinstance(value, str) and SAFE_CODE.fullmatch(value):
        return value
    return "OTHER" if value else "NONE"


def _count_by(db, table, column):
    rows = db.execute(text(
        f'SELECT "{column}" AS state, COUNT(*) AS count FROM "{table}" '
        f'GROUP BY "{column}" ORDER BY "{column}"'
    )).mappings()
    allowed = KNOWN_STATES.get(table, set())
    result = {}
    for row in rows:
        state = row["state"]
        label = state if isinstance(state, str) and state in allowed and SAFE_STATE.fullmatch(state) else "other"
        result[label] = result.get(label, 0) + int(row["count"])
    return result


def _errors_by(db, table):
    rows = db.execute(text(
        f'SELECT error_code, COUNT(*) AS count FROM "{table}" '
        'WHERE error_code IS NOT NULL GROUP BY error_code ORDER BY error_code'
    )).mappings()
    result = {}
    for row in rows:
        code = _safe_code(row["error_code"])
        result[code] = result.get(code, 0) + int(row["count"])
    return result


def _pending_age(db, table, timestamp_column, pending_states):
    stmt = text(
        f'SELECT MIN("{timestamp_column}") FROM "{table}" '
        'WHERE state IN :states'
    ).bindparams(bindparam("states", expanding=True))
    oldest = db.execute(stmt, {"states": tuple(pending_states)}).scalar_one_or_none()
    if oldest is None:
        return None
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - oldest.astimezone(timezone.utc)).total_seconds()))


def _seconds_remaining(value, now):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((value.astimezone(timezone.utc) - now).total_seconds()))


def _numeric_state(raw, now):
    """Whitelist numeric provider pacing fields; omit all unknown state/header data."""
    state = raw if isinstance(raw, dict) else {}
    safe = {}
    for key in ("remaining_requests", "remaining_tokens"):
        value = state.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            safe[key] = value
    for key, output_key in (("request_reset", "request_reset_remaining_seconds"),
                            ("token_reset", "token_reset_remaining_seconds"),
                            ("cooldown", "cooldown_remaining_seconds")):
        value = state.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            safe[output_key] = max(0, int(value - now.timestamp()))
    # next_request is a monotonic clock value and has no meaningful wall-clock
    # conversion after a process restart; deliberately do not expose it.
    return safe


def build_report(db, settings, *, now=None):
    now = now or datetime.now(timezone.utc)
    tables = set(db.execute(text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
    )).scalars())
    revision = None
    if "alembic_version" in tables:
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    available = {key: name in tables for key, name in TABLES.items()}
    report = {
        "captured_at": now.isoformat(),
        "schema_revision": revision,
        "rollout_configuration": {
            "agent_hierarchy_enabled": bool(settings.agent_hierarchy_enabled),
            "orchestrator_model_assisted": bool(settings.orchestrator_model_assisted),
            "meaning": "configured values only; does not attest running processes",
        },
        "unavailable_tables": [name for key, name in TABLES.items() if not available[key]],
        "jobs": None,
        "agent_runs": None,
        "conversation_tasks": None,
        "hosted_provider_admission": None,
    }
    if available["jobs"]:
        report["jobs"] = {
            "by_state": _count_by(db, "jobs", "state"),
            "errors_by_code": _errors_by(db, "jobs"),
            "oldest_queued_age_seconds": _pending_age(db, "jobs", "created_at", ("queued",)),
            "expired_running_ownership_count": int(db.execute(text(
                "SELECT COUNT(*) FROM jobs WHERE state='running' AND "
                "(lease_expires_at IS NULL OR lease_expires_at <= CURRENT_TIMESTAMP)"
            )).scalar_one()),
        }
    if available["agent_runs"]:
        report["agent_runs"] = {"by_state": _count_by(db, "agent_runs", "state"),
                                 "errors_by_code": _errors_by(db, "agent_runs")}
    if available["conversation_tasks"]:
        report["conversation_tasks"] = {
            "by_state": _count_by(db, "conversation_tasks", "state"),
            "errors_by_code": _errors_by(db, "conversation_tasks"),
            "oldest_queued_age_seconds": _pending_age(db, "conversation_tasks", "created_at", ("queued",)),
            "expired_running_ownership_count": int(db.execute(text(
                "SELECT COUNT(*) FROM conversation_tasks WHERE state='running' AND "
                "(lease_expires_at IS NULL OR lease_expires_at <= CURRENT_TIMESTAMP)"
            )).scalar_one()),
        }
    if available["hosted_provider_admission"]:
        providers = {}
        rows = db.execute(text(
            "SELECT provider, lease_expires_at, state FROM hosted_provider_admission ORDER BY provider"
        )).mappings()
        for row in rows:
            # Provider names are fixed category labels. Unknown values are suppressed.
            provider = row["provider"] if row["provider"] in ("groq", "openrouter") else "other"
            provider_state = _numeric_state(row["state"], now)
            providers[provider] = {
                **provider_state,
                "cooldown_remaining_seconds": provider_state.get("cooldown_remaining_seconds"),
                "lease_remaining_seconds": _seconds_remaining(row["lease_expires_at"], now),
            }
        report["hosted_provider_admission"] = providers
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write JSON to a new file (refuses overwrite)")
    args = parser.parse_args(argv)
    if args.output and args.output.exists():
        parser.error("--output path already exists; refusing to overwrite")
    settings = get_settings()
    try:
        with engine.connect() as db:
            report = build_report(db, settings)
    except Exception as exc:
        # Error text may contain SQL, hostnames, or credentials; expose only its type.
        print(json.dumps({"error": type(exc).__name__}), file=sys.stderr)
        return 1
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        # Exclusive creation closes the race between the preflight and write.
        try:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
        except FileExistsError:
            parser.error("--output path already exists; refusing to overwrite")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
