"""Snapshot PostgreSQL and all referenced immutable originals into a new directory.

Stop intake and the worker before running to ensure a consistent DB/file pair.
The default uses this project's private PostgreSQL container, never a remote service.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app.db.models import (ActivityState, AgentRun, AuditEvent, Conversation, ConversationTurn,
                           FileRecord, Fragment, IntegrationOutbox, Observation, ProgressEvent,
                           Job, Proposal, ScheduleSourceMetadata)
from app.db.session import session_factory
from app.settings import get_settings


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


RECOVERY_TABLES = {
    "agent_runs": AgentRun, "conversations": Conversation,
    "conversation_turns": ConversationTurn, "integration_outbox": IntegrationOutbox,
    "activity_states": ActivityState, "progress_events": ProgressEvent,
    "observations": Observation, "proposals": Proposal, "audit_events": AuditEvent,
    "jobs": Job,
}


def table_digest(db, model):
    digest = hashlib.sha256()
    table = model.__tablename__
    primary_key = model.__mapper__.primary_key[0].name
    for raw in db.execute(text(f"SELECT row_to_json(t)::text FROM {table} t ORDER BY {primary_key}")).scalars():
        record = json.loads(raw)
        digest.update(json.dumps(record, sort_keys=True, separators=(",", ":"), default=str).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--quiesced", action="store_true", help="Confirm intake and worker are stopped")
    args = parser.parse_args()
    if not args.quiesced:
        parser.error("Stop intake/worker and pass --quiesced before creating a snapshot")
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    settings = get_settings()
    upload_root = Path(settings.upload_dir).resolve()
    with session_factory() as db:
        records = db.scalars(select(FileRecord)).all()
        events = [str(value) for value in db.scalars(select(ProgressEvent.id))]
        evidence = [
            str(value)
            for value in db.scalars(
                select(Fragment.id)
                .join(Observation, Observation.fragment_id == Fragment.id)
                .join(ProgressEvent, ProgressEvent.observation_id == Observation.id)
                .distinct()
            )
        ]
        native = [str(value) for value in db.scalars(select(ScheduleSourceMetadata.schedule_version_id))]
        recovery_rows = {table: {"ids": [str(value) for value in db.scalars(select(getattr(model, model.__mapper__.primary_key[0].name)))],
                                 "sha256": table_digest(db, model)}
                         for table, model in RECOVERY_TABLES.items()}
        files = []
        for record in records:
            source = (upload_root / record.storage_key).resolve()
            if upload_root not in source.parents or not source.is_file() or sha(source) != record.sha256:
                raise SystemExit(f"Original missing or hash mismatch: {record.id}; snapshot incomplete")
            target = destination / "uploads" / record.storage_key
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            os.chmod(target, 0o600)
            files.append({"id": str(record.id), "storage_key": record.storage_key, "sha256": record.sha256})
    database_url = make_url(settings.database_url)
    database = database_url.database or ""
    username = database_url.username or ""
    if not database.replace("_", "").isalnum() or not username.replace("_", "").isalnum():
        raise SystemExit("Backup supports only a named local database and user")
    dump = destination / "database.dump"
    with dump.open("xb") as handle:
        subprocess.run(["docker", "compose", "exec", "-T", "db", "pg_dump", "-U", username, "-d", database, "-Fc"], stdout=handle, check=True)
    os.chmod(dump, 0o600)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "database_sha256": sha(dump),
                "files": files, "approved_event_ids": events,
                "approved_evidence_fragment_ids": evidence, "native_metadata_ids": native,
                "recovery_rows": recovery_rows}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Backup created: {destination}; {len(files)} originals, {len(events)} approved events, {len(evidence)} evidence fragments")


if __name__ == "__main__":
    main()
