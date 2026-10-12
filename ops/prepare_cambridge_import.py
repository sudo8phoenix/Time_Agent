#!/usr/bin/env python3
"""Derive one bounded Cambridge project snapshot from the large source JSON."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.ingest.schedule_datasets.cambridge import _projects  # noqa: E402

MAX_BYTES = 10 * 1024 * 1024


def sha256_stream(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare(source: Path, project_id: str, output: Path) -> dict:
    if not source.is_file():
        raise ValueError("Cambridge source file does not exist")
    source = source.resolve()
    output = output.resolve()
    if output == source:
        raise ValueError("output path must not be the Cambridge parent source")
    if output.exists():
        raise ValueError("output path already exists; choose a new snapshot path")
    parent_hash = sha256_stream(source)
    extras: dict = {}
    selected = None
    for pid, project in _projects(source, extras):
        if pid == project_id:
            selected = project
    if selected is None:
        raise ValueError(f"Cambridge project {project_id!r} was not found")
    if not isinstance(selected, dict) or not isinstance(selected.get("Activities"), dict):
        raise ValueError("selected Cambridge project has malformed Activities")
    activities = selected["Activities"]
    calendar_records = extras.get("Calendars", {})
    if not isinstance(calendar_records, dict):
        raise ValueError("Cambridge root Calendars must be an object")
    calendar_ids = {str(row.get("Calendar_ID")) for row in activities.values()
                    if isinstance(row, dict) and row.get("Calendar_ID") is not None}
    calendars = {str(key): value for key, value in calendar_records.items() if str(key) in calendar_ids}
    payload = {"_cambridge_snapshot": {
        "kind": "derived_project_snapshot", "derived_from_parent": True,
        "parent_source_sha256": parent_hash, "parent_source_locator": f"$.Projects[{json.dumps(project_id)}]",
        "parent_sha256_status": "computed_from_local_parent_bytes",
        "snapshot_project_id": project_id, "upstream_identity_verified": False,
        "upstream_identity_verification": "not_performed",
        "snapshot_tool": "ops/prepare_cambridge_import.py",
    }, "Projects": {project_id: selected}, "Calendars": calendars}
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            handle.write("\n")
        size = temporary.stat().st_size
        if size > MAX_BYTES:
            raise ValueError(f"derived snapshot is {size} bytes; maximum is {MAX_BYTES}")
        # Hard-link creation is atomic and fails rather than replacing an existing destination.
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return {"project_id": project_id, "activities": len(activities), "calendars": len(calendars),
            "snapshot_bytes": size, "parent_source_sha256": parent_hash, "output": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("project_id")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.source, args.project_id, args.output), indent=2))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
