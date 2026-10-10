from datetime import date
from decimal import Decimal
from pydantic import Field, field_validator, model_validator
from .events import LifecycleEffect
from .common import (StrictModel, Discipline, WorkType, EventType, ObservedStatus, QuantityKind,
    DateBasis, Unit, Evidence, finite_nonnegative)


class Observation(StrictModel):
    discipline: Discipline
    work_type: WorkType
    event_type: EventType
    observed_status: ObservedStatus
    area: str | None = Field(max_length=200)
    asset_tags: list[str] = Field(max_length=50)
    explicit_activity_id: str | None = Field(max_length=200)
    work_date: date | None
    date_basis: DateBasis
    quantity: Decimal | None
    quantity_kind: QuantityKind
    unit: Unit | None
    raw_unit: str | None = Field(max_length=100)
    reported_percent: Decimal | None = Field(ge=0, le=100)
    actual_start: date | None
    actual_finish: date | None
    blocker: str | None = Field(max_length=2000)
    summary: str = Field(min_length=1, max_length=2000)
    evidence: list[Evidence] = Field(min_length=1, max_length=30)
    warnings: list[str] = Field(max_length=30)
    lifecycle_effects: list[LifecycleEffect] = Field(default_factory=list, max_length=2)

    _quantity = field_validator("quantity")(finite_nonnegative)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.actual_start and self.actual_finish and self.actual_start > self.actual_finish:
            raise ValueError("actual_start must not be after actual_finish")
        if self.unit is None and self.quantity is not None and self.quantity_kind not in (QuantityKind.none, QuantityKind.unknown):
            raise ValueError("unit is required for a measured quantity")
        return self


class ObservationBatch(StrictModel):
    observations: list[Observation] = Field(max_length=100)
