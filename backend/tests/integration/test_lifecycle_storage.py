"""Precision and legacy compatibility against a migrated isolated PostgreSQL DB."""
from datetime import date, datetime, time, timezone
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.session import engine
from app.db.models import (Activity, ActivityState, Fragment, Job, Observation,
                           ProgressEvent, Project, Proposal, Report, ScheduleVersion, User)


def test_date_only_and_timed_endpoints_round_trip():
    with Session(engine) as db:
        project = Project(name=f"lifecycle-{uuid4().hex}")
        reviewer = User(username=f"lifecycle-{uuid4().hex}", password_hash="unused", role="reviewer")
        db.add_all([project, reviewer])
        db.flush()
        version = ScheduleVersion(project_id=project.id, version_number=1, content_sha256=uuid4().hex)
        db.add(version)
        db.flush()
        activity = Activity(schedule_version_id=version.id, external_id="A1", name="Excavation",
                            wbs="1", discipline="civil", work_type="excavation", is_leaf=True,
                            measurement_basis="unsupported", actual_start=date(2026, 10, 1))
        db.add(activity)
        db.flush()
        state = ActivityState(activity_id=activity.id, revision=0, completed_quantity=0,
                              observed_status="not_started", actual_start=date(2026, 10, 1),
                              actual_start_precision=None)
        db.add(state)
        report = Report(project_id=project.id, content_hash=uuid4().hex)
        db.add(report)
        db.flush()
        fragment = Fragment(report_id=report.id, ordinal=1, locator="p1",
                            original_text="Started and finished", normalised_text="Started and finished")
        job = Job(project_id=project.id, report_id=report.id, schedule_version_id=version.id)
        db.add_all([fragment, job])
        db.flush()
        events = []
        for ordinal, kind, day, clock, precision in (
            (1, "actual_start", 2, None, "date"),
            (2, "actual_finish", 3, time(17, 30), "minute"),
        ):
            observation = Observation(job_id=job.id, fragment_id=fragment.id, ordinal=ordinal,
                                      fields={}, field_evidence={})
            db.add(observation)
            db.flush()
            proposal = Proposal(observation_id=observation.id, revision=1, project_id=project.id,
                                chosen_activity_id=activity.id, candidates=[], mapping_state="suggested",
                                match_strength="review", review_state="approved", warnings=[],
                                proposed_effects={})
            db.add(proposal)
            db.flush()
            event = ProgressEvent(activity_id=activity.id, observation_id=observation.id,
                                  proposal_id=proposal.id, proposal_revision=1,
                                  approved_values={}, effect_kind=kind, effective_date=date(2026, 10, day),
                                  reviewer_id=reviewer.id, lifecycle_scope="whole_activity",
                                  endpoint_time=clock, endpoint_precision=precision,
                                  endpoint_timezone="Asia/Kolkata", endpoint_basis="explicit",
                                  endpoint_raw_expression=f"day {day}",
                                  endpoint_evidence=[{"fragment_id": str(fragment.id), "quote": "Started and finished"}],
                                  source_schedule_version_id=version.id,
                                  endpoint_instant=(datetime(2026, 10, day, 12, 0, tzinfo=timezone.utc)
                                                    if clock else None))
            db.add(event)
            db.flush()
            events.append(event.id)
        state.actual_start = date(2026, 10, 2)
        state.actual_start_precision = "date"
        state.actual_start_time = None
        state.actual_finish = date(2026, 10, 3)
        state.actual_finish_time = time(17, 30)
        state.actual_finish_precision = "minute"
        state.lifecycle_status = "completed"
        state.lifecycle_source_version_id = version.id
        state.lifecycle_start_event_id, state.lifecycle_finish_event_id = events
        db.flush()
        db.expire_all()
        loaded = db.get(ActivityState, activity.id)
        first, second = [db.get(ProgressEvent, event_id) for event_id in events]
        assert loaded.actual_start_precision == "date" and loaded.actual_start_time is None
        assert loaded.actual_finish_time == time(17, 30)
        assert first.endpoint_precision == "date" and first.endpoint_instant is None
        assert second.endpoint_precision == "minute" and second.endpoint_time == time(17, 30)
        assert db.get(Activity, activity.id).actual_start == date(2026, 10, 1)
        db.rollback()


def test_legacy_rows_keep_null_precision(monkeypatch):
    """Apply the additive migration to an in-memory pre-0010 schema.

    This deliberately avoids relying on a seeded developer database, and the
    in-memory SQLite database makes the migration check safe to run anywhere.
    Foreign-key DDL is recorded as a no-op because SQLite cannot add a foreign
    key to an existing table without rebuilding it; the tested behavior here is
    preservation of legacy date/quantity values and NULL precision metadata.
    """
    from importlib import import_module
    migration = import_module("backend.migrations.versions.0010_lifecycle_precision")
    isolated = create_engine("sqlite:///:memory:")
    with isolated.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE activities (id TEXT PRIMARY KEY, external_id TEXT)")
        connection.exec_driver_sql("CREATE TABLE activity_states (activity_id TEXT PRIMARY KEY, actual_start DATE, completed_quantity NUMERIC)")
        connection.exec_driver_sql("CREATE TABLE progress_events (activity_id TEXT, effect_kind TEXT)")
        connection.exec_driver_sql("INSERT INTO activities VALUES ('legacy-activity', 'LEG-1')")
        connection.exec_driver_sql("INSERT INTO activity_states VALUES ('legacy-activity', '2026-10-01', 2)")
        connection.exec_driver_sql("INSERT INTO progress_events VALUES ('legacy-activity', 'actual_progress')")

        class IsolatedMigrationOps:
            def add_column(self, table, column):
                sql_type = column.type.compile(dialect=connection.dialect)
                connection.exec_driver_sql(
                    f'ALTER TABLE "{table}" ADD COLUMN "{column.name}" {sql_type}'
                )

            def create_foreign_key(self, *args, **kwargs):
                pass

        monkeypatch.setattr(migration, "op", IsolatedMigrationOps())
        migration.upgrade()

        state = connection.exec_driver_sql(
            "SELECT actual_start, completed_quantity, actual_start_precision, actual_start_time "
            "FROM activity_states WHERE activity_id = 'legacy-activity'"
        ).one()
        assert state == ("2026-10-01", 2, None, None)
        event = connection.exec_driver_sql(
            "SELECT effect_kind, endpoint_precision FROM progress_events WHERE activity_id = 'legacy-activity'"
        ).one()
        assert event == ("actual_progress", None)
    isolated.dispose()
