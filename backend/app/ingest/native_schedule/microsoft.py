"""Read Microsoft Project MSPDI/MPP schedules through the bounded MPXJ runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from app.ingest.native_schedule.runner import ParserRuntimeError, run_reader_module
from app.schemas.native_schedule import SchedulePreview

PARSER_VERSION = "mpxj-14.0.0"


def _text(value: object | None) -> str | None:
    return str(value) if value is not None else None


def _lag(value: object | None) -> tuple[str | None, str | None]:
    text = _text(value)
    if not text:
        return None, None
    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(.*)", text)
    if match is None:
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_FAILED", f"Unsupported Microsoft Project relationship lag: {text}"
        )
    return match.group(1), match.group(2) or None


def _child_read(path: Path, source_project_id: str | None) -> dict[str, object]:
    suffix = path.suffix.lower()
    if suffix not in {".xml", ".mpp"}:
        raise ParserRuntimeError(
            "SCHEDULE_FORMAT_UNSUPPORTED", "Microsoft reader supports MSPDI .xml and .mpp files."
        )
    header = path.read_bytes()[:16]
    if suffix == ".mpp" and not header.startswith(bytes.fromhex("D0 CF 11 E0 A1 B1 1A E1")):
        raise ParserRuntimeError(
            "SCHEDULE_FORMAT_MISMATCH", "The .mpp file does not have a Microsoft compound-file signature."
        )
    if suffix == ".xml" and b"<!doctype" in path.read_bytes().lower():
        raise ParserRuntimeError(
            "SCHEDULE_FORMAT_MISMATCH", "XML DTD and external entities are not accepted."
        )
    try:
        import mpxj

        mpxj.startJVM(convertStrings=True)
        from org.mpxj.reader import UniversalProjectReader
    except Exception as exc:
        raise ParserRuntimeError(
            "SCHEDULE_PARSER_UNAVAILABLE", f"MPXJ/Java is unavailable: {exc}"
        ) from exc
    try:
        project = UniversalProjectReader().read(str(path))
    except Exception as exc:
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_FAILED", f"MPXJ could not read {path.name}: {exc}"
        ) from exc
    if project is None:
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_FAILED", f"MPXJ returned no project for {path.name}."
        )
    properties = project.getProjectProperties()
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    project_id = _text(properties.getUniqueID()) or f"project-1:{file_hash[:16]}"
    name = _text(properties.getName()) or "Unnamed Microsoft Project"
    if source_project_id is not None and source_project_id != project_id:
        raise ParserRuntimeError(
            "SCHEDULE_SOURCE_PROJECT_UNKNOWN",
            "The requested Microsoft source project is not in this file.",
        )
    tasks, wbs, task_by_id, external_ids = [], [], {}, set()
    for task in project.getTasks():
        source_id = _text(task.getUniqueID())
        display_id = _text(task.getID())
        task_name = _text(task.getName())
        if not source_id or not task_name:
            raise ParserRuntimeError(
                "SCHEDULE_PARSE_FAILED", "Microsoft task UID or name is missing."
            )
        if source_id in external_ids:
            raise ParserRuntimeError(
                "SCHEDULE_PARSE_FAILED", f"Duplicate Microsoft Project task UID: {source_id}"
            )
        external_ids.add(source_id)
        parent_id = _text(task.getParentTaskUniqueID())
        is_summary = bool(task.getSummary())
        record = {
            "source_task_id": source_id,
            "external_id": source_id,
            "name": task_name,
            "source_wbs_id": parent_id,
            "is_summary": is_summary,
            "is_milestone": bool(task.getMilestone()),
            "planned_start": _text(task.getStart()),
            "planned_finish": _text(task.getFinish()),
            "actual_start": _text(task.getActualStart()),
            "actual_finish": _text(task.getActualFinish()),
            "source_fields": {
                "display_id": display_id,
                "outline_level": _text(task.getOutlineLevel()),
                "outline_number": _text(task.getOutlineNumber()),
                "wbs": _text(task.getWBS()),
                "calendar_id": _text(task.getCalendarUniqueID()),
                "scheduled_start_source": _text(task.getStart()),
                "scheduled_finish_source": _text(task.getFinish()),
                "baseline_start": _text(task.getBaselineStart()),
                "baseline_finish": _text(task.getBaselineFinish()),
            },
        }
        task_by_id[source_id] = record
        tasks.append(record)
        if is_summary:
            wbs.append(
                {
                    "source_wbs_id": source_id,
                    "parent_source_wbs_id": parent_id,
                    "code": _text(task.getWBS()),
                    "name": task_name,
                    "path": [
                        part
                        for part in str(task.getOutlineNumber() or source_id).split(".")
                        if part
                    ],
                }
            )
    if len([task for task in tasks if not task["is_summary"]]) > 500:
        raise ParserRuntimeError("SCHEDULE_TOO_LARGE", "Selected project exceeds 500 activities.")
    if len(wbs) > 500:
        raise ParserRuntimeError("SCHEDULE_TOO_LARGE", "Selected project exceeds 500 summary nodes.")
    relationships = []
    for relation in project.getRelations():
        predecessor = _text(relation.getPredecessorTask().getUniqueID())
        successor = _text(relation.getSuccessorTask().getUniqueID())
        if predecessor not in task_by_id or successor not in task_by_id:
            raise ParserRuntimeError(
                "SCHEDULE_PARSE_FAILED", "Microsoft relationship has a dangling local task."
            )
        relation_type = str(relation.getType())
        if relation_type not in {"FS", "SS", "FF", "SF"}:
            raise ParserRuntimeError(
                "SCHEDULE_PARSE_FAILED", f"Unsupported Microsoft relationship type: {relation_type}"
            )
        lag_value, lag_unit = _lag(relation.getLag())
        relationships.append(
            {
                "predecessor_source_task_id": predecessor,
                "successor_source_task_id": successor,
                "relation_type": relation_type,
                "lag_value": lag_value,
                "lag_unit": lag_unit,
                "external_project_id": None,
            }
        )
    if len(relationships) > 5000:
        raise ParserRuntimeError("SCHEDULE_TOO_LARGE", "Selected project exceeds 5,000 relationships.")
    return {
        "source_format": "msp_mpp" if suffix == ".mpp" else "msp_xml",
        "source_sha256": file_hash,
        "parser_version": PARSER_VERSION,
        "projects": [{"source_project_id": project_id, "name": name}],
        "selected_project_id": project_id,
        "tasks": tasks,
        "wbs": wbs,
        "relationships": relationships,
        "issues": [],
    }


def read_schedule(path: Path, source_project_id: str | None = None) -> SchedulePreview:
    payload = run_reader_module("app.ingest.native_schedule.microsoft", path, source_project_id)
    return SchedulePreview.model_validate(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source-project-id")
    args = parser.parse_args()
    if not args.child:
        parser.error("reader is only invoked by the bounded native-schedule runner")
    try:
        print(json.dumps(_child_read(args.input, args.source_project_id)))
        return 0
    except ParserRuntimeError as exc:
        print(json.dumps({"code": exc.code, "message": exc.message}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
