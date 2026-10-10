from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Discipline(str, Enum):
    civil = "civil"; structural = "structural"; piping = "piping"; mechanical = "mechanical"
    electrical = "electrical"; instrumentation = "instrumentation"; other = "other"; unknown = "unknown"


class WorkType(str, Enum):
    excavation = "excavation"; backfill = "backfill"; rebar_installation = "rebar_installation"
    formwork = "formwork"; concrete_pour = "concrete_pour"; curing = "curing"
    structural_erection = "structural_erection"; pipe_spool_erection = "pipe_spool_erection"
    welding = "welding"; weld_inspection = "weld_inspection"; hydrotest = "hydrotest"
    cable_laying = "cable_laying"; cable_termination = "cable_termination"
    equipment_installation = "equipment_installation"; other = "other"; unknown = "unknown"


class EventType(str, Enum):
    actual_progress = "actual_progress"; planned_work = "planned_work"; no_work = "no_work"
    blocker = "blocker"; inspection = "inspection"; material_delivery = "material_delivery"
    correction = "correction"; actual_start = "actual_start"; actual_finish = "actual_finish"; unknown = "unknown"


class ObservedStatus(str, Enum):
    not_started = "not_started"; in_progress = "in_progress"; completed = "completed"
    blocked = "blocked"; unknown = "unknown"


class QuantityKind(str, Enum):
    delta = "delta"; cumulative = "cumulative"; none = "none"; unknown = "unknown"


class DateBasis(str, Enum):
    explicit = "explicit"; report_context = "report_context"; relative_resolved = "relative_resolved"
    unknown = "unknown"; conflicting = "conflicting"


class MeasurementBasis(str, Enum):
    quantity_ratio = "quantity_ratio"; manual_physical = "manual_physical"
    milestone = "milestone"; unsupported = "unsupported"


class MappingState(str, Enum):
    suggested = "suggested"; ambiguous = "ambiguous"; unmatched = "unmatched"


class MatchStrength(str, Enum):
    strong = "strong"; review = "review"; unresolved = "unresolved"


class ReviewState(str, Enum):
    pending = "pending"; approved = "approved"; rejected = "rejected"
    superseded = "superseded"; stale = "stale"


class Unit(str, Enum):
    m = "m"; m2 = "m2"; m3 = "m3"; kg = "kg"; t = "t"; spool = "spool"
    joint = "joint"; point = "point"; each = "each"


class Evidence(StrictModel):
    fields: list[str] = Field(min_length=1, max_length=30)
    fragment_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=2000)


class ErrorBody(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    details: dict[str, Any]


class ErrorEnvelope(StrictModel):
    error: ErrorBody
    request_id: UUID | str = Field(min_length=1)


T = TypeVar("T")
class ResponseEnvelope(StrictModel, Generic[T]):
    data: T
    request_id: UUID | str = Field(min_length=1)


def finite_nonnegative(value: Decimal | None) -> Decimal | None:
    if value is not None and (not value.is_finite() or value < 0):
        raise ValueError("quantity must be finite and non-negative")
    return value
