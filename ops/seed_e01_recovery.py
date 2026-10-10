"""Create synthetic recovery evidence only in a fresh progress_recovery_* database."""
from datetime import date, time
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.db.models import (Activity, ActivityState, AgentRun, Conversation, ConversationTurn,
                           Fragment, Job, Observation, ProgressEvent, Project, Proposal, User)
from app.db.session import session_factory
from app.ingest.reports import ingest_report
from app.integrations.outbox import enqueue
from app.jobs.service import enqueue_job, enqueue_reanalysis
from app.settings import get_settings
from ops.seed_backup_acceptance import main as seed_base, NAME


def main():
    settings = get_settings()
    url = make_url(settings.database_url)
    if url.host not in {"127.0.0.1", "localhost"} or not (url.database or "").startswith("progress_recovery_"):
        raise SystemExit("Recovery fixtures require a separate local progress_recovery_* database")
    seed_base()
    with session_factory.begin() as db:
        project = db.scalar(select(Project).where(Project.name == NAME))
        if db.scalar(select(Conversation.id).where(Conversation.project_id == project.id)):
            raise SystemExit("Recovery fixture already exists; use a fresh database")
        user = db.scalar(select(User).where(User.username.like("backup-acceptance-%")))
        activity = db.scalar(select(Activity).where(Activity.schedule_version_id == project.active_schedule_version_id))
        report, _ = ingest_report(db, project, b"Started backup evidence fixture on 2026-10-02 at 08:30.",
                               filename="synthetic-recovery.txt", report_date=date(2026, 10, 2))
        base, _ = enqueue_job(db, project, report)
        base.state = "ready_for_review"
        child, _ = enqueue_reanalysis(db, project, report, actor_id=user.id,
                                      reason="Synthetic recovery lineage fixture", idempotency_key=uuid4().hex)
        fragment = db.scalar(select(Fragment).where(Fragment.report_id == report.id))
        observation = Observation(job_id=base.id, fragment_id=fragment.id, ordinal=1,
                                  fields={"event_type": "actual_start"}, field_evidence={})
        db.add(observation); db.flush()
        endpoint = {"local_date": "2026-10-02", "local_time": "08:30:00", "precision": "minute",
                    "timezone": "Asia/Kolkata", "basis": "explicit"}
        proposal = Proposal(observation_id=observation.id, project_id=project.id, revision=1,
                            chosen_activity_id=activity.id, candidates=[], mapping_state="suggested",
                            match_strength="review", review_state="approved", warnings=[],
                            proposed_effects={"event_type": "actual_start", "endpoint": endpoint})
        db.add(proposal); db.flush()
        event = ProgressEvent(activity_id=activity.id, observation_id=observation.id,
                              proposal_id=proposal.id, proposal_revision=1, reviewer_id=user.id,
                              approved_values=proposal.proposed_effects, effect_kind="actual_start",
                              effective_date=date(2026, 10, 2), endpoint_time=time(8, 30),
                              endpoint_precision="minute", endpoint_timezone="Asia/Kolkata",
                              endpoint_basis="explicit", lifecycle_scope="whole_activity",
                              source_schedule_version_id=project.active_schedule_version_id,
                              endpoint_evidence=[{"fragment_id": str(fragment.id), "quote": fragment.original_text}])
        db.add(event); db.flush()
        state = db.get(ActivityState, activity.id)
        state.revision += 1
        state.actual_start = date(2026, 10, 2); state.actual_start_time = time(8, 30)
        state.actual_start_precision = "minute"
        state.lifecycle_start_event_id = event.id; state.lifecycle_status = "in_progress"
        enqueue(db, activity, state)
        conversation = Conversation(project_id=project.id, creator_id=user.id,
                                    schedule_version_id=project.active_schedule_version_id, job_id=base.id,
                                    draft={"synthetic": True}, status="confirmed")
        db.add(conversation); db.flush()
        db.add(ConversationTurn(conversation_id=conversation.id, ordinal=1, actor_id=user.id,
                                role="user", text=fragment.original_text))
        db.add(AgentRun(job_id=child.id, graph_version="recovery-fixture", state_schema_version="fixture",
                        framework_version="fixture", thread_id=f"recovery-{child.id}", state="created",
                        execution_mode="legacy", model_metadata={"synthetic": True}))
    print("Synthetic lifecycle, original, conversation, child run and pending outbox recovery fixture created.")


if __name__ == "__main__":
    main()
