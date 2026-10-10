"""Frozen v1.1 native schedule preview contract."""

from datetime import date
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any, Literal

from pydantic import Field, field_validator

from .common import StrictModel

RelationType = Literal["FS", "SS", "FF", "SF"]
Severity = Literal["error", "warning"]
SourceFormat = Literal["p6_xer", "p6_xml", "msp_xml", "msp_mpp", "gt10_xlsx"]


def _decimal_string(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("decimal values must be strings")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError("invalid decimal string") from None
    if not number.is_finite():
        raise ValueError("decimal must be finite")
    return value


def _json_finite(value: Any) -> Any:
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("JSON values must be finite")
    if isinstance(value, dict):
        return {key: _json_finite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_finite(item) for item in value]
    return value


class SourceProject(StrictModel):
    source_project_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class SourceWbs(StrictModel):
    source_wbs_id: str = Field(min_length=1)
    parent_source_wbs_id: str | None
    code: str | None
    name: str = Field(min_length=1)
    path: list[str]


class SourceTask(StrictModel):
    source_task_id: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source_wbs_id: str | None
    is_summary: bool
    is_milestone: bool
    planned_start: str | None
    planned_finish: str | None
    actual_start: str | None
    actual_finish: str | None
    source_fields: dict[str, Any]

    @field_validator("source_fields")
    @classmethod
    def finite_source_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _json_finite(value)


class SourceRelation(StrictModel):
    predecessor_source_task_id: str = Field(min_length=1)
    successor_source_task_id: str = Field(min_length=1)
    relation_type: RelationType
    lag_value: str | None
    lag_unit: str | None
    external_project_id: str | None
    source_fields: dict[str, Any] = Field(default_factory=dict)

    _validate_lag = field_validator("lag_value")(_decimal_string)


class ImportIssue(StrictModel):
    code: str = Field(min_length=1)
    severity: Severity
    source_task_id: str | None
    message: str = Field(min_length=1)


class SchedulePreview(StrictModel):
    source_format: SourceFormat
    source_sha256: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    projects: list[SourceProject]
    selected_project_id: str | None
    tasks: list[SourceTask]
    wbs: list[SourceWbs]
    relationships: list[SourceRelation]
    issues: list[ImportIssue]


class TaskOverride(StrictModel):
    discipline: str | None = None
    work_type: str | None = None
    area: str | None = None
    asset_tags: list[str] | None = None
    aliases: list[str] | None = None
    measurement_basis: (
        Literal["quantity_ratio", "manual_physical", "milestone", "unsupported"] | None
    ) = None
    planned_quantity: str | None = None
    unit: str | None = None
    baseline_quantity: str | None = None
    planned_start: date | None = None
    planned_finish: date | None = None
    actual_start: date | None = None
    actual_finish: date | None = None

    _planned_quantity = field_validator("planned_quantity")(_decimal_string)
    _baseline_quantity = field_validator("baseline_quantity")(_decimal_string)


class ReviewedScheduleMapping(StrictModel):
    baseline_date: date
    source_project_id: str = Field(min_length=1)
    task_overrides: dict[str, TaskOverride] = Field(default_factory=dict)
    reason: str = Field(min_length=1)


class NormalisedSchedule(StrictModel):
    canonical_csv: str
    task_metadata: dict[str, SourceTask]
    wbs: list[SourceWbs]
    relationships: list[SourceRelation]
    issues: list[ImportIssue]
