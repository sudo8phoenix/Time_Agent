"""Reviewer-controlled native preview conversion to the canonical CSV contract."""

from __future__ import annotations

import csv
import io

from app.ingest.schedules import REQUIRED, parse_schedule_csv
from app.schemas.native_schedule import NormalisedSchedule, ReviewedScheduleMapping, SchedulePreview


class MappingError(ValueError):
    pass


def _csv_date(value: object | None) -> str:
    return (
        value.isoformat()
        if value is not None and hasattr(value, "isoformat")
        else str(value or "")[:10]
    )


def normalise_schedule(
    preview: SchedulePreview, mapping: ReviewedScheduleMapping
) -> NormalisedSchedule:
    if preview.selected_project_id != mapping.source_project_id:
        raise MappingError("SCHEDULE_SOURCE_PROJECT_UNKNOWN")
    source_ids = {task.source_task_id for task in preview.tasks}
    unknown = set(mapping.task_overrides) - source_ids
    if unknown:
        raise MappingError("SCHEDULE_MAPPING_INVALID: override contains unknown source task IDs")
    wbs_by_id = {node.source_wbs_id: node for node in preview.wbs}
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=REQUIRED, lineterminator="\n")
    writer.writeheader()
    metadata = {}
    seen_external_ids = set()
    for task in preview.tasks:
        if task.is_summary:
            continue
        override = mapping.task_overrides.get(task.source_task_id)
        values = override.model_dump(exclude_none=True) if override else {}
        basis = values.get("measurement_basis", "milestone" if task.is_milestone else "unsupported")
        if basis == "milestone":
            values.pop("planned_quantity", None)
            values.pop("baseline_quantity", None)
            values.pop("unit", None)
        wbs = wbs_by_id.get(task.source_wbs_id) if task.source_wbs_id else None
        external_id = task.external_id
        if external_id in seen_external_ids:
            raise MappingError("SCHEDULE_MAPPING_INVALID: duplicate external activity ID")
        seen_external_ids.add(external_id)
        writer.writerow(
            {
                "activity_id": external_id,
                "activity_name": task.name,
                "wbs_path": "/".join(wbs.path) if wbs and wbs.path else preview.projects[0].name,
                "discipline": values.get("discipline", "unknown"),
                "work_type": values.get("work_type", "unknown"),
                "area": values.get("area", ""),
                "asset_tags": ";".join(values.get("asset_tags", [])),
                "is_leaf": "true",
                "measurement_basis": basis,
                "planned_quantity": values.get("planned_quantity", ""),
                "unit": values.get("unit", ""),
                "planned_start": _csv_date(values.get("planned_start", task.planned_start)),
                "planned_finish": _csv_date(values.get("planned_finish", task.planned_finish)),
                "baseline_date": mapping.baseline_date.isoformat(),
                "baseline_quantity": values.get("baseline_quantity", ""),
                "actual_start": _csv_date(values.get("actual_start", task.actual_start)),
                "actual_finish": _csv_date(values.get("actual_finish", task.actual_finish)),
                "aliases": ";".join(values.get("aliases", [])),
            }
        )
        metadata[external_id] = task
    canonical_csv = output.getvalue()
    parsed, _, errors = parse_schedule_csv(canonical_csv)
    if parsed is None or errors:
        raise MappingError(f"SCHEDULE_MAPPING_INVALID: {errors}")
    return NormalisedSchedule(
        canonical_csv=canonical_csv,
        task_metadata=metadata,
        wbs=preview.wbs,
        relationships=preview.relationships,
        issues=preview.issues,
    )
