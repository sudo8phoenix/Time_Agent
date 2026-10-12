"""Preview bounded, locally derived Cambridge project snapshots."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

from app.ingest.native_schedule.runner import ParserRuntimeError
from app.ingest.schedule_datasets.cambridge import _unique
from app.schemas.native_schedule import SchedulePreview

PARSER_VERSION = "cambridge-snapshot-v1"
MAX_BYTES = 10 * 1024 * 1024


def _date(value):
    if value in (None, ""):
        return None, False
    text = str(value)
    try:
        date.fromisoformat(text[:10])
        if len(text) == 10:
            pass
        elif len(text) > 10 and text[10] in ("T", " "):
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            raise ValueError
        return text, False
    except ValueError:
        return None, True


def _timestamp(value):
    if value in (None, ""):
        return None, None
    text = str(value)
    try:
        parsed_date = date.fromisoformat(text[:10])
        if len(text) == 10:
            return parsed_date, "date"
        if len(text) > 10 and text[10] in ("T", " "):
            return datetime.fromisoformat(text.replace("Z", "+00:00")), "datetime"
    except ValueError:
        pass
    return None, "invalid"


def _reject_json_constant(value):
    raise ValueError(f"invalid JSON constant {value}")


def read_schedule(path: Path, source_project_id: str | None = None) -> SchedulePreview:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", "Cambridge snapshot cannot be read.") from exc
    if size > MAX_BYTES:
        raise ParserRuntimeError("SCHEDULE_TOO_LARGE", "Cambridge snapshots are limited to 10 MiB.")
    raw_bytes = path.read_bytes()
    try:
        payload = json.loads(raw_bytes, object_pairs_hook=_unique, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", "Cambridge snapshot JSON is invalid.") from exc
    provenance = payload.get("_cambridge_snapshot") if isinstance(payload, dict) else None
    projects = payload.get("Projects") if isinstance(payload, dict) else None
    calendars = payload.get("Calendars", {}) if isinstance(payload, dict) else None
    if not isinstance(provenance, dict) or provenance.get("kind") != "derived_project_snapshot":
        raise ParserRuntimeError("SCHEDULE_FORMAT_MISMATCH", "JSON is not a derived Cambridge snapshot.")
    if not isinstance(projects, dict) or len(projects) != 1 or not isinstance(calendars, dict):
        raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", "Cambridge snapshot containers are malformed.")
    pid, project = next(iter(projects.items()))
    parent_hash = provenance.get("parent_source_sha256")
    expected_locator = f"$.Projects[{json.dumps(pid)}]"
    if (provenance.get("derived_from_parent") is not True
            or provenance.get("snapshot_project_id") != pid
            or provenance.get("parent_source_locator") != expected_locator
            or not isinstance(parent_hash, str) or re.fullmatch(r"[0-9a-fA-F]{64}", parent_hash) is None
            or provenance.get("parent_sha256_status") != "computed_from_local_parent_bytes"
            or provenance.get("upstream_identity_verified") is not False
            or provenance.get("upstream_identity_verification") != "not_performed"):
        raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", "Cambridge snapshot provenance fields are malformed or inconsistent.")
    if source_project_id not in (None, pid):
        raise ParserRuntimeError("SCHEDULE_SOURCE_PROJECT_UNKNOWN", "Requested Cambridge project is not in this snapshot.")
    if not isinstance(project, dict) or not isinstance(project.get("Activities"), dict):
        raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", "Cambridge snapshot Activities are malformed.")
    tasks, relations, issues = [], [], []
    activities = project["Activities"]
    status_date, status_date_bad = _date(project.get("Status_Data_Date"))
    if status_date_bad:
        issues.append({"code": "invalid_status_data_date", "severity": "warning", "source_task_id": None,
                       "message": "Raw Status_Data_Date is invalid; no actual-date cutoff was applied."})
    status_cutoff = date.fromisoformat(status_date[:10]) if status_date else None
    for task_id, row in activities.items():
        if not isinstance(row, dict):
            raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", f"Invalid Cambridge task {task_id}.")
        locator = f"$.Projects[{json.dumps(pid)}].Activities[{json.dumps(task_id)}]"
        name = row.get("Activity_Description")
        if not isinstance(name, str) or not name.strip():
            name = str(task_id)
            issues.append({"code": "missing_task_name", "severity": "warning", "source_task_id": str(task_id), "message": f"Missing task name at {locator}; source ID used for display."})
        dates, date_objects, precisions = {}, {}, {}
        for field, raw_field in (("planned_start", "Planned_Start_Date"), ("planned_finish", "Planned_Finish_Date"),
                                 ("actual_start", "Actual_Start_Date"), ("actual_finish", "Actual_Finish_Date")):
            dates[field], bad = _date(row.get(raw_field))
            date_objects[field], precisions[field] = _timestamp(row.get(raw_field))
            if bad:
                issues.append({"code": "invalid_source_date", "severity": "warning", "source_task_id": str(task_id), "message": f"Unparseable {raw_field} retained in source_fields at {locator}."})
        for start_field, finish_field, label in (("planned_start", "planned_finish", "planned"),
                                                  ("actual_start", "actual_finish", "actual")):
            start, finish = date_objects.get(start_field), date_objects.get(finish_field)
            if start is not None and finish is not None:
                if precisions[start_field] == precisions[finish_field] == "datetime":
                    comparable = start.tzinfo is None and finish.tzinfo is None or start.tzinfo is not None and finish.tzinfo is not None
                    reverse = comparable and start > finish
                elif precisions[start_field] == precisions[finish_field] == "date":
                    comparable, reverse = True, start > finish
                else:
                    comparable, reverse = False, False
                if reverse:
                    dates[start_field] = dates[finish_field] = None
                    issues.append({"code": "invalid_date_chronology", "severity": "warning", "source_task_id": str(task_id),
                                   "message": f"{label} start follows finish at {locator}; both canonical dates omitted and raw values retained."})
                elif not comparable:
                    dates[start_field] = dates[finish_field] = None
                    issues.append({"code": "date_precision_incomparable", "severity": "warning", "source_task_id": str(task_id),
                                   "message": f"{label} dates have mixed precision or timezone basis at {locator}; both canonical dates omitted and raw values retained."})
        if status_cutoff is not None:
            for field, raw_field in (("actual_start", "Actual_Start_Date"), ("actual_finish", "Actual_Finish_Date")):
                actual = date_objects.get(field)
                actual_day = actual.date() if isinstance(actual, datetime) else actual
                if actual_day is not None and actual_day > status_cutoff:
                    dates[field] = None
                    issues.append({"code": "actual_after_status_date", "severity": "warning", "source_task_id": str(task_id),
                                   "message": f"{raw_field} is after raw Status_Data_Date; canonical endpoint omitted, raw values retained."})
        wbs_id = row.get("WBS_ID")
        if str(row.get("Task_ID")) != str(task_id):
            issues.append({"code": "task_id_mismatch", "severity": "warning", "source_task_id": str(task_id), "message": f"Activity key and raw Task_ID differ at {locator}."})
        task = {"source_task_id": str(task_id), "external_id": str(task_id), "name": name,
                "source_wbs_id": str(wbs_id) if wbs_id not in (None, "") else None,
                "is_summary": False, "is_milestone": False, **dates,
                "source_fields": {"locator": locator, "composite_source_identity": ["cambridge", str(pid), str(task_id)], "raw_fields": row,
                                  "timestamp_basis": "source_string_timezone_unspecified",
                                  "calendar_id": row.get("Calendar_ID"),
                                  "calendar_status": "unreviewed"}}
        tasks.append(task)
        rels = row.get("Activity_Relationships", {})
        if rels in (None, "null"):
            rels = {}
        if not isinstance(rels, dict):
            raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", f"Malformed relationships at {locator}.")
        for rel_key, rel in rels.items():
            if not isinstance(rel, dict):
                raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", f"Malformed relationship at {locator}.")
            raw_kind = str(rel.get("Relationship_Type", ""))
            kind = {"PR_FS": "FS", "PR_SS": "SS", "PR_FF": "FF", "PR_SF": "SF"}.get(raw_kind)
            pred = str(rel.get("Predecessor_ID", ""))
            if kind is None:
                issues.append({"code": "unknown_relationship_type", "severity": "warning", "source_task_id": str(task_id), "message": f"Relationship {rel_key} type {raw_kind!r} retained in task raw fields; no edge inferred."})
                continue
            if pred not in activities:
                issues.append({"code": "unresolved_predecessor", "severity": "warning", "source_task_id": str(task_id), "message": f"Relationship {rel_key} predecessor {pred!r} is not local."})
                continue
            relations.append({"predecessor_source_task_id": pred, "successor_source_task_id": str(task_id),
                              "relation_type": kind, "lag_value": str(rel["Lag"]) if rel.get("Lag") not in (None, "") else None,
                              "lag_unit": "unknown_unreviewed", "external_project_id": None,
                              "source_fields": {"locator": locator, "relationship_key": str(rel_key),
                                                "raw": rel, "raw_relationship_type": raw_kind,
                                                "lag_unit_status": "unknown_unreviewed"}})
    wbs_data = project.get("Work_Breakdown_Structure", {})
    wbs_records = {}
    if isinstance(wbs_data, dict):
        values = wbs_data.items()
    elif isinstance(wbs_data, list):
        values = ((value.get("WBS_ID", index), value) for index, value in enumerate(wbs_data)
                  if isinstance(value, dict))
        if any(not isinstance(value, dict) for value in wbs_data):
            raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", "Cambridge WBS list contains non-object records.")
    else:
        raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", "Cambridge WBS container is malformed.")
    for key, value in values:
        if not isinstance(value, dict):
            raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", f"Cambridge WBS record {key!r} is malformed.")
        source_id = str(value.get("WBS_ID", key))
        parent = value.get("WBS_Parent_ID", value.get("Parent_WBS_ID"))
        parent_id = str(parent) if parent not in (None, "", "null") else None
        wbs_records[source_id] = {"source_wbs_id": source_id, "parent_source_wbs_id": parent_id,
            "code": str(value.get("WBS_Code") or source_id),
            "name": str(value.get("WBS_Description") or value.get("Name") or source_id), "path": []}
    wbs = []
    for source_id, node in wbs_records.items():
        chain, visited, current = [], set(), source_id
        while current in wbs_records and current not in visited:
            visited.add(current)
            chain.append(wbs_records[current]["code"])
            current = wbs_records[current]["parent_source_wbs_id"]
        if current in visited:
            issues.append({"code": "wbs_parent_cycle", "severity": "warning", "source_task_id": None,
                           "message": f"WBS parent cycle includes {current}; raw WBS is retained."})
        elif current is not None:
            issues.append({"code": "wbs_parent_unresolved", "severity": "warning", "source_task_id": None,
                           "message": f"WBS parent {current} is absent; raw WBS is retained."})
        node["path"] = list(reversed(chain))
        wbs.append(node)
    referenced = {str(task["source_fields"].get("calendar_id")) for task in tasks if task["source_fields"].get("calendar_id") is not None}
    known_calendars = set(map(str, calendars))
    for missing in sorted(referenced - known_calendars):
        issues.append({"code": "calendar_record_missing", "severity": "warning", "source_task_id": None, "message": f"Calendar {missing} is not present in the snapshot."})
    issues.append({"code": "cambridge_calendar_semantics_unreviewed", "severity": "warning", "source_task_id": None,
                   "message": "Raw calendar records are retained, but working-time semantics and timezone are not interpreted."})
    if relations:
        issues.append({"code": "cambridge_lag_units_unreviewed", "severity": "warning", "source_task_id": None,
                       "message": "Relationship lag values are retained with unknown units; no duration conversion is applied."})
    issues.append({"code": "cambridge_provenance_unverified", "severity": "warning", "source_task_id": None,
                   "message": "This is a locally derived snapshot; upstream byte identity and source semantics are unverified."})
    project_name = str(project.get("Project_Name") or project.get("Project_ID") or f"Cambridge project {pid}")
    return SchedulePreview.model_validate({"source_format": "cambridge_json", "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "parser_version": PARSER_VERSION, "projects": [{"source_project_id": str(pid), "name": project_name}],
        "selected_project_id": str(pid), "tasks": tasks, "wbs": wbs, "relationships": relations, "issues": issues,
        "source_metadata": {**provenance, "project_metadata": {k:v for k,v in project.items() if k not in {"Activities", "Work_Breakdown_Structure"}},
                             "raw_wbs": project.get("Work_Breakdown_Structure", {}),
                             "calendars": calendars, "calendar_semantics": "unreviewed", "timezone_basis": "unspecified"}})
