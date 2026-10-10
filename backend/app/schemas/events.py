"""Precision-preserving lifecycle contracts."""
from datetime import date, datetime, time
from enum import Enum
from uuid import UUID
from pydantic import Field, field_validator, model_validator
from .common import StrictModel, Evidence


class LifecycleKind(str, Enum):
    actual_start = "actual_start"
    actual_finish = "actual_finish"


class LifecycleScope(str, Enum):
    whole_activity = "whole_activity"
    subactivity = "subactivity"


class EndpointPrecision(str, Enum):
    date = "date"
    minute = "minute"
    second = "second"


class Endpoint(StrictModel):
    local_date: date
    local_time: time | None = None
    precision: EndpointPrecision
    timezone: str | None = Field(default=None, max_length=64)
    basis: str = Field(min_length=1, max_length=40)
    raw_expression: str = Field(min_length=1, max_length=500)
    normalized_instant: datetime | None = None

    @field_validator("local_time")
    @classmethod
    def local_time_has_no_zone(cls, value: time | None):
        if value is not None and value.tzinfo is not None:
            raise ValueError("local_time must be a clock time without timezone or Z suffix")
        return value

    @model_validator(mode="after")
    def check_precision(self):
        if (self.precision == EndpointPrecision.date) != (self.local_time is None):
            raise ValueError("date precision requires no time; timed precision requires time")
        if self.precision == EndpointPrecision.minute and (self.local_time.second or self.local_time.microsecond):
            raise ValueError("minute precision cannot contain seconds")
        if self.precision == EndpointPrecision.second and self.local_time and self.local_time.microsecond:
            raise ValueError("second precision cannot contain microseconds")
        if self.precision == EndpointPrecision.date and self.normalized_instant is not None:
            raise ValueError("date-only endpoint cannot have an instant")
        if self.normalized_instant is not None and self.normalized_instant.tzinfo is None:
            raise ValueError("normalized instant must be timezone aware")
        return self


class LifecycleEffect(StrictModel):
    kind: LifecycleKind
    scope: LifecycleScope
    endpoint: Endpoint
    evidence: list[Evidence] = Field(min_length=1, max_length=30)
    source_version_id: UUID | None = None
    observation_id: UUID | None = None
    proposal_id: UUID | None = None
    actor_id: UUID | None = None
    subactivity_key: str | None = Field(default=None, min_length=1, max_length=200)
    scheduled_parent_id: UUID | None = None

    @model_validator(mode="after")
    def check_scope(self):
        if self.scope == LifecycleScope.subactivity and not self.subactivity_key:
            raise ValueError("subactivity requires a subactivity key")
        if self.scope == LifecycleScope.whole_activity and (self.subactivity_key or self.scheduled_parent_id):
            raise ValueError("whole activity cannot carry subactivity mapping")
        return self
