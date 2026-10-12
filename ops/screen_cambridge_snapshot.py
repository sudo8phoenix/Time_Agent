"""Record row-level development exclusions without altering Cambridge sources."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


def _date(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def screen(path: Path) -> dict:
    raw = path.read_bytes()
    source = json.loads(raw)
    pid, project = next(iter(source["Projects"].items()))
    tasks, calendars = project["Activities"], source["Calendars"]
    status = _date(project.get("Status_Data_Date"))
    rows = []
    for task_id, task in tasks.items():
        flags = []
        start, finish, actual_start, actual_finish = [
            _date(task.get(key)) for key in (
                "Planned_Start_Date", "Planned_Finish_Date",
                "Actual_Start_Date", "Actual_Finish_Date",
            )
        ]
        if start and finish and finish < start:
            flags.append("planned_finish_before_start")
        if actual_start and actual_finish and actual_finish < actual_start:
            flags.append("actual_finish_before_start")
        if status and any(value and value > status for value in (actual_start, actual_finish)):
            flags.append("actual_after_status_date")
        if "XXXXX" in str(task.get("Activity_Description", "")):
            flags.append("redacted_activity_description")
        if str(task.get("Calendar_ID")) not in calendars:
            flags.append("calendar_record_missing")
        relationships = task.get("Activity_Relationships", {})
        relationships = {} if relationships in (None, "null") else relationships
        external = [str(edge.get("Predecessor_ID")) for edge in relationships.values()
                    if str(edge.get("Predecessor_ID")) not in tasks]
        if external:
            flags.append("external_or_unresolved_predecessor")
        rows.append({
            "task_id": task_id,
            "locator": f"$.Projects[{json.dumps(pid)}].Activities[{json.dumps(task_id)}]",
            "flags": flags, "external_predecessors": external,
            "development_field_policy": {
                "identity": "project_id_plus_task_key",
                "dates": "exclude_conflicting_fields" if any(
                    "before" in flag or "status" in flag for flag in flags
                ) else "retain_source_precision_unreviewed",
                "calendar_and_weather": "excluded_from_duration_and_label_claims",
                "relationships": "local_supported_types_only_lag_units_unreviewed",
            },
        })
    return {
        "schema_version": 1, "project_id": pid, "review_kind": "technical_subset_screening",
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "parent_provenance": source["_cambridge_snapshot"], "activity_count": len(rows),
        "status_data_date": project.get("Status_Data_Date"),
        "flag_counts": {flag: sum(flag in row["flags"] for row in rows)
                        for flag in sorted({flag for row in rows for flag in row["flags"]})},
        "rows": rows, "independent_planner_acceptance": "pending",
        "source_rows_modified": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = screen(args.snapshot)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"activities": result["activity_count"], "flags": result["flag_counts"]}))
