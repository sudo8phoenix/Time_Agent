"""Read locally stored Primavera schedules through the bounded MPXJ child runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
            "SCHEDULE_PARSE_FAILED", f"Unsupported Primavera relationship lag: {text}"
        )
    return match.group(1), match.group(2) or None


def _child_read(path: Path, source_project_id: str | None) -> dict[str, object]:
    if path.suffix.lower() not in {".xer", ".xml"}:
        raise ParserRuntimeError(
            "SCHEDULE_FORMAT_UNSUPPORTED", "Primavera reader supports .xer and P6 PMXML .xml files."
        )
    try:
        import mpxj

        mpxj.startJVM(convertStrings=True)
        from java.io import FileInputStream
        from org.mpxj.primavera import PrimaveraPMFileReader, PrimaveraXERFileReader
    except Exception as exc:
        if isinstance(exc, ParserRuntimeError):
            raise
        raise ParserRuntimeError(
            "SCHEDULE_PARSER_UNAVAILABLE", f"MPXJ/Java is unavailable: {exc}"
        ) from exc
    try:
        xer = path.suffix.lower() == ".xer"
        reader = PrimaveraXERFileReader() if xer else PrimaveraPMFileReader()
        with FileInputStream(str(path)) as stream:
            raw_projects = reader.listProjects(stream)
        projects = {str(key): str(value) for key, value in raw_projects.items()}
        if not projects:
            raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", "No Primavera project was found.")
        if source_project_id is None and len(projects) > 1:
            return {
                "source_format": "p6_xer" if xer else "p6_xml",
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "parser_version": PARSER_VERSION,
                "projects": [
                    {"source_project_id": key, "name": name}
                    for key, name in projects.items()
                ],
                "selected_project_id": None,
                "tasks": [], "wbs": [], "relationships": [], "issues": [],
            }
        selected = source_project_id or next(iter(projects))
        if selected not in projects:
            raise ParserRuntimeError(
                "SCHEDULE_SOURCE_PROJECT_UNKNOWN",
                "The requested Primavera source project is not in this file.",
            )
        reader.setProjectID(int(selected))
        with FileInputStream(str(path)) as stream:
            project = reader.read(stream)
    except Exception as exc:
        if isinstance(exc, ParserRuntimeError):
            raise
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_FAILED", f"MPXJ could not read {path.name}: {exc}"
        ) from exc
    if project is None:
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_FAILED", f"MPXJ returned no project for {path.name}."
        )
    properties = project.getProjectProperties()
    project_id = str(properties.getUniqueID() or "")
    name = str(properties.getName() or "")
    if not project_id or not name:
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_FAILED", "Primavera project identity or name is missing."
        )
    if source_project_id is not None and source_project_id != project_id:
        raise ParserRuntimeError(
            "SCHEDULE_SOURCE_PROJECT_UNKNOWN",
            "The requested Primavera source project is not in this file.",
        )
    tasks, wbs, task_by_id, external_ids = [], [], {}, set()
    for task in project.getTasks():
        source_id = str(task.getUniqueID() or "")
        external_id = str(task.getActivityID() or task.getID() or "")
        task_name = str(task.getName() or "")
        if not source_id or not external_id or not task_name:
            raise ParserRuntimeError(
                "SCHEDULE_PARSE_FAILED", "Primavera task identity or name is missing."
            )
        if external_id in external_ids:
            raise ParserRuntimeError(
                "SCHEDULE_PARSE_FAILED", f"Duplicate Primavera activity ID: {external_id}"
            )
        external_ids.add(external_id)
        parent_id = _text(task.getParentTaskUniqueID())
        is_summary = bool(task.getSummary())
        source_fields = {
            "display_id": external_id,
            "wbs": _text(task.getWBS()),
            "outline_number": _text(task.getOutlineNumber()),
            "calendar_id": _text(task.getCalendarUniqueID()),
            "planned_start_source": _text(task.getStart()),
            "planned_finish_source": _text(task.getFinish()),
        }
        record = {
            "source_task_id": source_id,
            "external_id": external_id,
            "name": task_name,
            "source_wbs_id": parent_id if is_summary else _text(task.getParentTaskUniqueID()),
            "is_summary": is_summary,
                "is_milestone": bool(task.getMilestone()),
            "planned_start": _text(task.getStart()),
            "planned_finish": _text(task.getFinish()),
            "actual_start": _text(task.getActualStart()),
            "actual_finish": _text(task.getActualFinish()),
            "source_fields": source_fields,
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
                    "path": [part for part in str(task.getWBS() or name).split(".") if part],
                }
            )
    relationships = []
    for relation in project.getRelations():
        predecessor = str(relation.getPredecessorTask().getUniqueID() or "")
        successor = str(relation.getSuccessorTask().getUniqueID() or "")
        if predecessor not in task_by_id or successor not in task_by_id:
            raise ParserRuntimeError(
                "SCHEDULE_PARSE_FAILED", "Primavera relationship has a dangling local task."
            )
        relation_type = str(relation.getType())
        if relation_type not in {"FS", "SS", "FF", "SF"}:
            raise ParserRuntimeError(
                "SCHEDULE_PARSE_FAILED", f"Unsupported Primavera relationship type: {relation_type}"
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
    if len([task for task in tasks if not task["is_summary"]]) > 500:
        raise ParserRuntimeError("SCHEDULE_TOO_LARGE", "Selected project exceeds 500 activities.")
    if len(wbs) > 500:
        raise ParserRuntimeError("SCHEDULE_TOO_LARGE", "Selected project exceeds 500 WBS nodes.")
    if len(relationships) > 5000:
        raise ParserRuntimeError("SCHEDULE_TOO_LARGE", "Selected project exceeds 5,000 relationships.")
    return {
        "source_format": "p6_xer" if path.suffix.lower() == ".xer" else "p6_xml",
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "parser_version": PARSER_VERSION,
        "projects": [{"source_project_id": project_id, "name": name}],
        "selected_project_id": project_id,
        "tasks": tasks,
        "wbs": wbs,
        "relationships": relationships,
        "issues": [],
    }


def read_schedule(path: Path, source_project_id: str | None = None) -> SchedulePreview:
    payload = run_reader_module("app.ingest.native_schedule.primavera", path, source_project_id)
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
