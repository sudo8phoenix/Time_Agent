"""Sequential approval regressions; SQLite does not exercise PostgreSQL locking."""
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.api.endpoints.review import ApprovalRequest, approve
from app.db.base import Base
from app.db.models import (
    Activity, ActivityState, Fragment, Job, Observation, ProgressEvent, Project,
    ProjectMembership, Proposal, Report, ScheduleVersion, User,
)
from app.progress.history import event_statuses


@pytest.fixture
def workspace():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    # Match the production partial index; SQLAlchemy ignores postgresql_where on SQLite.
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_progress_events_active_observation"))
        connection.execute(text(
            "CREATE UNIQUE INDEX uq_progress_events_active_observation "
            "ON progress_events (observation_id) WHERE supersedes_event_id IS NULL"))
    with Session(engine, expire_on_commit=False) as db:
        user = User(username="reviewer", password_hash="unused", role="reviewer")
        project = Project(name="Synthetic project", timezone="UTC")
        schedule = ScheduleVersion(project=project, version_number=1,
                                   content_sha256="a" * 64, state="active")
        activity = Activity(schedule_version=schedule, external_id="A1", name="Install",
                            wbs="1", discipline="mechanical", work_type="other",
                            is_leaf=True, measurement_basis="quantity_ratio",
                            planned_quantity=10, baseline_quantity=0, unit="spool",
                            baseline_date=date(2026, 1, 1))
        db.add_all([user, project, schedule, activity])
        db.flush()
        project.active_schedule_version_id = schedule.id
        db.add(ProjectMembership(project_id=project.id, user_id=user.id))
        db.add(ActivityState(activity_id=activity.id, revision=0, completed_quantity=0))
        report = Report(project_id=project.id, content_hash="b" * 64)
        db.add(report)
        db.flush()
        job = Job(project_id=project.id, report_id=report.id, schedule_version_id=schedule.id)
        db.add(job)
        db.flush()
        fragment = Fragment(report_id=report.id, ordinal=1, locator="paragraph:1",
                            original_text="Started on 2026-01-02. Finished on 2026-01-03.",
                            normalised_text="Started on 2026-01-02. Finished on 2026-01-03.")
        db.add(fragment)
        db.commit()
        yield db, user, activity, job, fragment
    engine.dispose()


def proposal_for(workspace, effects):
    db, _, activity, job, fragment = workspace
    ordinal = len(db.scalars(select(Observation).where(Observation.job_id == job.id)).all()) + 1
    observation = Observation(job_id=job.id, ordinal=ordinal, fragment_id=fragment.id,
                              fields={}, field_evidence={})
    db.add(observation)
    db.flush()
    proposal = Proposal(observation_id=observation.id, revision=1, project_id=job.project_id,
                        chosen_activity_id=activity.id, candidates=[], mapping_state="suggested",
                        match_strength="review", review_state="pending", warnings=[],
                        proposed_effects=effects)
    db.add(proposal)
    db.flush()
    return proposal


def accept(workspace, proposal):
    db, user, activity, _, _ = workspace
    result = approve(proposal.id, ApprovalRequest(expected_proposal_revision=1,
        expected_activity_revision=db.get(ActivityState, activity.id).revision,
        idempotency_key=str(proposal.id)), user, db)
    db.commit()
    return db.get(ProgressEvent, UUID(result["event_id"]))


def numeric_effects(quantity="2"):
    return {"quantity": quantity, "unit": "spool", "quantity_semantics": "delta",
            "event_type": "actual_progress", "effective_date": "2026-01-04"}


@pytest.mark.parametrize("kind", ["actual_start", "actual_finish", "lifecycle_retraction"])
def test_numeric_approval_ignores_lifecycle_history(workspace, kind):
    db, _, activity, _, fragment = workspace
    lifecycle = proposal_for(workspace, {
        "event_type": "actual_start" if kind == "lifecycle_retraction" else kind,
        "scope": "whole_activity", "effective_date": "2026-01-02",
        "endpoint": {"local_date": "2026-01-02", "precision": "date",
                     "basis": "explicit", "raw_expression": "2026-01-02"},
        "evidence": [{"fields": ["endpoint"], "fragment_id": str(fragment.id),
                      "quote": fragment.original_text}],
    })
    accepted = accept(workspace, lifecycle)
    if kind == "lifecycle_retraction":
        from app.api.endpoints.review import LifecycleRetractionRequest, retract_lifecycle
        retract_lifecycle(accepted.id, LifecycleRetractionRequest(expected_activity_revision=1,
            idempotency_key="retract", reason="Synthetic correction"), workspace[1], db)
        db.commit()
    accept(workspace, proposal_for(workspace, numeric_effects()))
    state = db.get(ActivityState, activity.id)
    assert state.physical_percent == Decimal("20")
    assert state.completed_quantity == Decimal("2")


@pytest.mark.parametrize("reference", ["correction_of", "supersedes_event_id", "both"])
def test_correction_totals_and_history_share_persisted_lineage(workspace, reference):
    db, _, activity, _, _ = workspace
    original = accept(workspace, proposal_for(workspace, numeric_effects()))
    effects = numeric_effects("1")
    for key in (["correction_of", "supersedes_event_id"] if reference == "both" else [reference]):
        effects[key] = str(original.id)
    correction = accept(workspace, proposal_for(workspace, effects))
    assert correction.supersedes_event_id == original.id
    assert correction.approved_values["supersedes_event_id"] == str(original.id)
    assert db.get(ActivityState, activity.id).completed_quantity == Decimal("1")
    assert event_statuses([original, correction]) == {
        original.id: "superseded", correction.id: "active"}
    assert original.approved_values["quantity"] == "2"


@pytest.mark.parametrize("references", [
    {"correction_of": "not-a-uuid"},
    {"correction_of": str(uuid4())},
    {"correction_of": str(uuid4()), "supersedes_event_id": str(uuid4())},
])
def test_invalid_correction_references_leave_progress_unchanged(workspace, references):
    db, _, activity, _, _ = workspace
    accept(workspace, proposal_for(workspace, numeric_effects()))
    proposal = proposal_for(workspace, {**numeric_effects("1"), **references})
    with pytest.raises(HTTPException) as error:
        accept(workspace, proposal)
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "INVALID_CORRECTION_REFERENCE"
    db.rollback()
    assert db.get(ActivityState, activity.id).completed_quantity == Decimal("2")
    assert len(db.scalars(select(ProgressEvent)).all()) == 1
