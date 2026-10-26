"""Initial activity projection shared by reads and the first approval."""
from decimal import Decimal

from ..db.models import Activity, ActivityState
from .ledger import quantity_ratio


def baseline_state(activity: Activity) -> ActivityState:
    quantity = activity.baseline_quantity if activity.baseline_quantity is not None else Decimal("0")
    percent = None
    if activity.measurement_basis == "quantity_ratio":
        try:
            percent = quantity_ratio(quantity, activity.planned_quantity)
        except ValueError:
            # Older/incomplete schedules can still receive blockers and
            # lifecycle events. Missing numeric inputs mean unknown percent.
            pass
    return ActivityState(
        activity_id=activity.id,
        revision=0,
        completed_quantity=quantity,
        physical_percent=percent,
        actual_start=activity.actual_start,
        actual_finish=activity.actual_finish,
        actual_start_precision="date" if activity.actual_start else None,
        actual_finish_precision="date" if activity.actual_finish else None,
        lifecycle_status=("completed" if activity.actual_finish else
                          "in_progress" if activity.actual_start else "not_started"),
        lifecycle_source_version_id=activity.schedule_version_id,
    )
