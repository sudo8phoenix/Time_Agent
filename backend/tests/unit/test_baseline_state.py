from datetime import date
from decimal import Decimal
from uuid import uuid4
import pytest

from app.db.models import Activity
from app.progress.baseline import baseline_state


def test_baseline_preserves_quantity_and_date_only_lifecycle():
    activity = Activity(id=uuid4(), schedule_version_id=uuid4(),
                        measurement_basis="quantity_ratio", planned_quantity=Decimal("100"),
                        baseline_quantity=Decimal("20"), actual_start=date(2026, 10, 1))
    state = baseline_state(activity)
    assert state.revision == 0
    assert state.completed_quantity == Decimal("20")
    assert state.physical_percent == Decimal("20")
    assert state.actual_start == date(2026, 10, 1)
    assert state.actual_start_precision == "date"
    assert state.actual_start_time is None
    assert state.actual_finish is None
    assert state.lifecycle_status == "in_progress"


def test_unsupported_basis_does_not_invent_numeric_percent():
    state = baseline_state(Activity(id=uuid4(), schedule_version_id=uuid4(),
                                    measurement_basis="unsupported",
                                    actual_finish=date(2026, 10, 2)))
    assert state.completed_quantity == 0
    assert state.physical_percent is None
    assert state.actual_finish_precision == "date"
    assert state.lifecycle_status == "completed"


@pytest.mark.parametrize("planned", [None, Decimal("0"), Decimal("NaN")])
def test_incomplete_numeric_baseline_keeps_percent_unknown(planned):
    state = baseline_state(Activity(id=uuid4(), schedule_version_id=uuid4(),
                                    measurement_basis="quantity_ratio", planned_quantity=planned))
    assert state.completed_quantity == 0
    assert state.physical_percent is None
