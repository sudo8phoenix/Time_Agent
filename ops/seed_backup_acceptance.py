"""Seed one traceable approved event in the isolated integration database."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.db.models import (
    Activity,
    ActivityState,
    Fragment,
    Job,
    Observation,
    ProgressEvent,
    Project,
    Proposal,
    Report,
    ScheduleVersion,
    User,
)
from app.db.passwords import hash_password
from app.db.session import session_factory


NAME = "__backup_acceptance__"


def main() -> None:
    with session_factory.begin() as db:
        existing = db.scalar(select(Project).where(Project.name == NAME))
        if existing:
            print("Backup acceptance fixture already exists.")
            return
        reviewer = User(
            username=f"backup-acceptance-{uuid4().hex}",
            password_hash=hash_password(uuid4().hex),
            role="reviewer",
        )
        project = Project(name=NAME, timezone="Asia/Kolkata")
        db.add_all([reviewer, project])
        db.flush()
        version = ScheduleVersion(
            project_id=project.id,
            version_number=1,
            content_sha256=uuid4().hex + uuid4().hex,
            state="active",
        )
        db.add(version)
        db.flush()
        project.active_schedule_version_id = version.id
        activity = Activity(
            schedule_version_id=version.id,
            external_id="BACKUP-TRACE-01",
            name="Backup evidence fixture",
            wbs="ACCEPTANCE/BACKUP",
            discipline="other",
            work_type="other",
            is_leaf=True,
            measurement_basis="quantity_ratio",
            planned_quantity=Decimal("10"),
            baseline_quantity=Decimal("0"),
            baseline_date=date(2026, 9, 23),
            unit="each",
        )
        report = Report(
            project_id=project.id,
            content_hash=uuid4().hex + uuid4().hex,
            report_date=date(2026, 9, 23),
            report_date_evidence="explicit acceptance fixture date",
            source_label="backup acceptance fixture",
        )
        db.add_all([activity, report])
        db.flush()
        fragment = Fragment(
            report_id=report.id,
            ordinal=1,
            locator="paragraph:1",
            original_text="Completed 2 items for backup verification.",
            normalised_text="Completed 2 items for backup verification.",
        )
        job = Job(
            project_id=project.id,
            report_id=report.id,
            schedule_version_id=version.id,
            state="ready_for_review",
            stage="persist",
        )
        db.add_all([fragment, job])
        db.flush()
        observation = Observation(
            job_id=job.id,
            fragment_id=fragment.id,
            ordinal=1,
            fields={
                "summary": "Completed 2 items.",
                "quantity": "2",
                "unit": "each",
                "evidence": [{"fragment_id": str(fragment.id), "quote": fragment.original_text}],
            },
            field_evidence={},
        )
        db.add(observation)
        db.flush()
        proposal = Proposal(
            observation_id=observation.id,
            revision=1,
            project_id=project.id,
            chosen_activity_id=activity.id,
            candidates=[],
            mapping_state="suggested",
            match_strength="review",
            review_state="approved",
            warnings=[],
            proposed_effects={"quantity": "2", "unit": "each", "quantity_semantics": "delta"},
        )
        db.add(proposal)
        db.flush()
        db.add_all(
            [
                ProgressEvent(
                    activity_id=activity.id,
                    observation_id=observation.id,
                    proposal_id=proposal.id,
                    proposal_revision=1,
                    approved_values=proposal.proposed_effects,
                    effect_kind="actual_progress",
                    effective_date=date(2026, 9, 23),
                    reviewer_id=reviewer.id,
                    source_key=f"backup-acceptance:{proposal.id}",
                ),
                ActivityState(
                    activity_id=activity.id,
                    revision=1,
                    completed_quantity=Decimal("2"),
                    physical_percent=Decimal("20"),
                    observed_status="in_progress",
                    last_observed_date=date(2026, 9, 23),
                ),
            ]
        )
    print("Seeded one approved event with source evidence in the isolated database.")


if __name__ == "__main__":
    main()
