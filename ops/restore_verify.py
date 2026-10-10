"""Restore a backup to a fresh, separate local database and verify its evidence.

Never restores over an existing database. Leaves the restored database for inspection.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import hashlib


def docker(*args, **kwargs):
    return subprocess.run(["docker", "compose", "exec", "-T", "db", *args], check=True, **kwargs)


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


RECOVERY_TABLES = {"agent_runs", "conversations", "conversation_turns", "integration_outbox",
                   "activity_states", "progress_events", "observations", "proposals",
                   "audit_events", "jobs"}
RECOVERY_PRIMARY_KEYS = {"activity_states": "activity_id"}


def recovery_digest(lines):
    digest = hashlib.sha256()
    for line in lines:
        record = json.loads(line)
        digest.update(json.dumps(record, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    parser.add_argument("--database", required=True, help="New name beginning progress_restore_")
    parser.add_argument("--uploads", type=Path, required=True, help="New empty destination")
    args = parser.parse_args()
    if not re.fullmatch(r"progress_restore_[a-z0-9_]{1,40}", args.database):
        parser.error("Use a distinct progress_restore_ database name")
    source = args.backup.resolve()
    manifest = json.loads((source / "manifest.json").read_text())
    dump = source / "database.dump"
    if sha(dump) != manifest["database_sha256"]:
        raise SystemExit("Database dump hash mismatch")
    for entry in manifest["files"]:
        original = (source / "uploads" / entry["storage_key"]).resolve()
        if source / "uploads" not in original.parents or sha(original) != entry["sha256"]:
            raise SystemExit("Original evidence hash mismatch")
    destination = args.uploads.resolve()
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    # createdb fails if the target already exists; no DROP, CLEAN or replacement.
    docker("createdb", "-U", "progress", args.database)
    with dump.open("rb") as handle:
        docker("pg_restore", "-U", "progress", "-d", args.database, "--exit-on-error", stdin=handle)
    for entry in manifest["files"]:
        target = destination / entry["storage_key"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / "uploads" / entry["storage_key"], target)
    for table, column, expected in [
        ("progress_events", "id", manifest["approved_event_ids"]),
        ("fragments", "id", manifest["approved_evidence_fragment_ids"]),
        ("schedule_source_metadata", "schedule_version_id", manifest["native_metadata_ids"]),
        ("files", "id", [entry["id"] for entry in manifest["files"]]),
    ]:
        result = docker("psql", "-U", "progress", "-d", args.database, "-Atc", f"SELECT {column} FROM {table} ORDER BY {column}", capture_output=True, text=True)
        if sorted(result.stdout.splitlines()) != sorted(expected):
            raise SystemExit(f"Restored {table} differs from backup manifest")
    for table, expected in manifest.get("recovery_rows", {}).items():
        if table not in RECOVERY_TABLES:
            raise SystemExit("Backup manifest contains an unsupported recovery table")
        primary_key = RECOVERY_PRIMARY_KEYS.get(table, "id")
        result = docker("psql", "-U", "progress", "-d", args.database, "-Atc",
                        f"SELECT row_to_json(t)::text FROM {table} t ORDER BY {primary_key}", capture_output=True, text=True)
        lines = result.stdout.splitlines()
        ids = [str(json.loads(line)[primary_key]) for line in lines]
        if sorted(ids) != sorted(expected["ids"]):
            raise SystemExit(f"Restored {table} differs from backup manifest")
        if recovery_digest(lines) != expected["sha256"]:
            raise SystemExit(f"Restored {table} content differs from backup manifest")
    print(json.dumps({"database": args.database, "uploads": str(destination), "verified": True,
                      "approved_events": len(manifest["approved_event_ids"]), "originals": len(manifest["files"]),
                      "recovery_rows": {name: len(row["ids"]) for name, row in manifest.get("recovery_rows", {}).items()}}))


if __name__ == "__main__":
    main()
