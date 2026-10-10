"""One-project-at-a-time Cambridge reader with raw values and issue records."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _projects(path: Path, extras: dict | None = None) -> Iterator[tuple[str, dict]]:
    decoder = json.JSONDecoder(object_pairs_hook=_unique)
    with path.open(encoding="utf-8-sig") as handle:
        buffer, eof = "", False
        def peek():
            nonlocal buffer, eof
            buffer = buffer.lstrip()
            while not buffer and not eof:
                chunk = handle.read(1024 * 1024)
                eof = not chunk
                buffer += chunk
                buffer = buffer.lstrip()
            return buffer[:1]
        def take():
            nonlocal buffer, eof
            peek()
            while True:
                try:
                    value, end = decoder.raw_decode(buffer)
                    buffer = buffer[end:]
                    return value
                except json.JSONDecodeError:
                    if eof:
                        raise
                    chunk = handle.read(max(1024 * 1024, len(buffer)))
                    eof = not chunk
                    buffer += chunk
        def expect(char):
            nonlocal buffer
            if peek() != char:
                raise ValueError(f"expected {char!r}, got {peek()!r}")
            buffer = buffer[1:]
        expect("{")
        if take() != "Projects":
            raise ValueError("unexpected root key")
        expect(":")
        expect("{")
        seen = set()
        while peek() != "}":
            project_id = take()
            if project_id in seen:
                raise ValueError(f"duplicate project: {project_id}")
            seen.add(project_id)
            expect(":")
            yield project_id, take()
            if peek() == ",":
                expect(",")
            else:
                break
        expect("}")
        # Root metadata is kept separate from project rows to avoid duplicating calendars.
        while peek() == ",":
            expect(",")
            key = take()
            expect(":")
            value = take()
            if extras is not None:
                extras[key] = value
        expect("}")
        if peek():
            raise ValueError("trailing JSON content")


def read_cambridge(path: str | Path, *, project_id: str | None = None) -> Iterator[dict]:
    for pid, source in _projects(Path(path)):
        if project_id is not None and pid != project_id:
            continue
        activities = source.get("Activities", {})
        if not isinstance(activities, dict):
            raise ValueError(f"invalid Activities in {pid}")
        issues = []
        rows = []
        for task_id, raw in activities.items():
            locator = f"$.Projects[{json.dumps(pid)}].Activities[{json.dumps(task_id)}]"
            if str(raw.get("Task_ID")) != task_id:
                issues.append({"code": "task_id_mismatch", "locator": locator})
            relations = raw.get("Activity_Relationships", {})
            if relations == "null":
                relations = {}
            elif not isinstance(relations, dict):
                issues.append({"code": "invalid_relationship_container", "locator": locator})
                relations = {}
            for rel_id, rel in relations.items():
                pred = str(rel.get("Predecessor_ID"))
                if pred not in activities:
                    issues.append({"code": "external_or_unresolved_predecessor", "locator": locator,
                                   "predecessor": pred, "relationship_key": rel_id})
            rows.append({"identity": ["cambridge", pid, task_id], "locator": locator,
                         "raw": raw, "relationships": relations,
                         "timestamp_basis": "source_string_timezone_unspecified"})
        yield {"source": "cambridge", "project_id": pid, "project_metadata":
               {key: value for key, value in source.items() if key not in {"Activities", "Work_Breakdown_Structure"}},
               "wbs": source.get("Work_Breakdown_Structure", {}), "activities": rows,
               "issues": issues, "review_status": "unreviewed"}


def read_cambridge_calendars(path: str | Path) -> dict:
    """Read unmodified root calendar metadata; semantics remain unreviewed."""
    extras: dict = {}
    for _ in _projects(Path(path), extras):
        pass
    calendars = extras.get("Calendars", {})
    if not isinstance(calendars, dict):
        raise ValueError("invalid Calendars root")
    return {"calendars": calendars, "working_duration_status": "unavailable_unreviewed",
            "timezone_basis": "unspecified"}
