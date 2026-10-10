"""Adapt the GT10 P6 export to the reviewed native import contract.

The canonical activity table is date-only. Exact source cells, timestamp strings,
precision and lag-header evidence remain in ScheduleSourceMetadata after staging.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.ingest.native_schedule.runner import ParserRuntimeError
from app.ingest.schedule_datasets.gt10_xlsx import read_gt10
from app.schemas.native_schedule import SchedulePreview

PARSER_VERSION = "gt10-xlsx-v1"
PROJECT_ID = "GT10BLDG"
SELECTED_SHA256 = "b84946cc8c279e879979ed174539357b92ac6cb3011562d30a44e4cce2913953"


def _raw(value):
    return value.get("raw") if isinstance(value, dict) and "raw" in value else value


def read_schedule(path: Path, source_project_id: str | None = None) -> SchedulePreview:
    if source_project_id not in (None, PROJECT_ID):
        raise ParserRuntimeError("SCHEDULE_SOURCE_PROJECT_UNKNOWN", "GT10 has one source project.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != SELECTED_SHA256:
        raise ParserRuntimeError("SCHEDULE_SOURCE_VERSION_UNREVIEWED", "GT10 workbook does not match the selected source hash.")
    try:
        source = read_gt10(path, version="export")
    except (KeyError, ValueError, OSError) as exc:
        raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", f"Invalid GT10 export: {exc}") from exc
    tasks = []
    wbs_codes = set()
    for row in source["tasks"]:
        cells = row["cells"]
        code = str(cells["task_code"])
        wbs_code = str(cells.get("wbs_id") or "")
        if wbs_code:
            wbs_codes.add(wbs_code)
        name = str(cells.get("task_name") or "")
        if not name:
            raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", f"Unnamed task {code} at {row['locator']}")
        tasks.append({
            "source_task_id": code, "external_id": code, "name": name,
            "source_wbs_id": wbs_code or None, "is_summary": False, "is_milestone": False,
            "planned_start": _raw(cells.get("start_date")),
            "planned_finish": _raw(cells.get("end_date")),
            "actual_start": None, "actual_finish": None,
            "source_fields": {"locator": row["locator"], "raw_cells": cells,
                              "timestamp_basis": "source_datetime_timezone_unspecified",
                              "mapping_status": "unreviewed", "calendar_status": "incomplete_unreviewed"},
        })
    relations = []
    for row in source["relationships"]:
        cells = row["cells"]
        kind = str(cells.get("pred_type") or "")
        if kind not in {"FS", "SS", "FF", "SF"}:
            raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", f"Unsupported relationship {kind} at {row['locator']}")
        relations.append({
            "predecessor_source_task_id": str(cells["pred_task_id"]),
            "successor_source_task_id": str(cells["task_id"]),
            "relation_type": kind,
            "lag_value": str(_raw(cells.get("lag_hr_cnt"))) if cells.get("lag_hr_cnt") is not None else None,
            "lag_unit": "source_header_lag_hr_cnt_unverified",
            "external_project_id": None,
            "source_fields": {"locator": row["locator"], "raw_cells": cells,
                              "lag_source_header": "lag_hr_cnt", "lag_display_header": "Lag(h)",
                              "unit_interpretation": "unverified"},
        })
    wbs = [{"source_wbs_id": code, "parent_source_wbs_id": None,
            "code": code, "name": code, "path": [code]} for code in sorted(wbs_codes)]
    issues = [
        {"code": "GT10_F8_NAME_CONFLICT", "severity": "warning", "source_task_id": "SUP-F8-06",
         "message": "Export names F8 task as F9; input says F8. No correction applied."},
        {"code": "GT10_LOGIC_LAG_UNREVIEWED", "severity": "warning", "source_task_id": None,
         "message": "Relationship differences and lag units need planner review before duration calculations."},
        {"code": "GT10_WBS_CALENDAR_INCOMPLETE", "severity": "warning", "source_task_id": None,
         "message": "Export WBS is code-only here; full calendar intervals and timezone are unavailable."},
    ]
    return SchedulePreview.model_validate({
        "source_format": "gt10_xlsx", "source_sha256": digest,
        "parser_version": PARSER_VERSION,
        "projects": [{"source_project_id": PROJECT_ID, "name": "GT10BLDG simulated schedule"}],
        "selected_project_id": PROJECT_ID, "tasks": tasks, "wbs": wbs,
        "relationships": relations, "issues": issues,
    })
