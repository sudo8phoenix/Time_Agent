"""The timeline projects imported dates without changing accepted progress."""
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.endpoints.progress import progress_view
from app.db.base import Base
from app.db.models import Activity, ActivityState, Project, ScheduleVersion, User


def test_progress_exposes_imported_planned_dates_and_preserves_nulls():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="viewer", password_hash="unused", role="viewer")
        project = Project(name="Schedule read", timezone="UTC")
        version = ScheduleVersion(project=project, version_number=1,
                                  content_sha256="a" * 64, state="active")
        dated = Activity(schedule_version=version, external_id="A1", name="Piping",
                         wbs="North", discipline="piping", work_type="other",
                         is_leaf=True, measurement_basis="unsupported",
                         planned_start=date(2026, 10, 1), planned_finish=date(2026, 11, 2))
        undated = Activity(schedule_version=version, external_id="A2", name="Equipment",
                           wbs="South", discipline="mechanical", work_type="other",
                           is_leaf=True, measurement_basis="unsupported")
        db.add_all([user, project, version, dated, undated])
        db.flush()
        project.active_schedule_version_id = version.id
        db.commit()
        result = progress_view(version=None, project=project, _user=user, db=db)
        assert result["items"][0]["planned_start"] == "2026-10-01"
        assert result["items"][0]["planned_finish"] == "2026-11-02"
        assert result["items"][1]["planned_start"] is None
        assert result["items"][1]["planned_finish"] is None
        assert result["items"][0]["physical_percent"] is None
        assert db.get(ActivityState, dated.id) is None
        assert not db.new and not db.dirty
    engine.dispose()
