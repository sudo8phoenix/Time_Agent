"""Decision history for a pinned report job, including revisions and corrections."""
from sqlalchemy import select
from app.db.models import AuditEvent, Observation, Proposal, ProgressEvent


def decision_history(db, observation):
    if observation is None:
        return {"scope": "report_job", "proposals": [], "events": [], "decisions": []}
    observations = db.scalars(select(Observation).where(Observation.job_id == observation.job_id)).all()
    ids = [row.id for row in observations]
    proposals = db.scalars(select(Proposal).where(Proposal.observation_id.in_(ids))
                           .order_by(Proposal.revision, Proposal.id)).all()
    events = db.scalars(select(ProgressEvent).where(ProgressEvent.observation_id.in_(ids))
                        .order_by(ProgressEvent.approved_at, ProgressEvent.id)).all()
    targets = [row.id for row in proposals] + [row.id for row in events]
    audits = db.scalars(select(AuditEvent).where(AuditEvent.target_id.in_(targets),
                         AuditEvent.target_type.in_(["proposal", "event"]))
                       .order_by(AuditEvent.timestamp, AuditEvent.id)).all() if targets else []
    return {
        "scope": "report_job", "job_id": str(observation.job_id),
        "proposals": [{"id": str(row.id), "observation_id": str(row.observation_id),
                       "revision": row.revision, "state": row.review_state,
                       "chosen_activity_id": str(row.chosen_activity_id) if row.chosen_activity_id else None,
                       "effects": row.proposed_effects, "warnings": row.warnings,
                       "candidates": row.candidates} for row in proposals],
        "events": [{"id": str(row.id), "proposal_id": str(row.proposal_id),
                    "kind": row.effect_kind, "values": row.approved_values,
                    "supersedes_event_id": str(row.supersedes_event_id) if row.supersedes_event_id else None,
                    "actor_id": str(row.reviewer_id),
                    "timestamp": row.approved_at.isoformat() if row.approved_at else None} for row in events],
        "decisions": [{"id": str(row.id), "action": row.action, "target_type": row.target_type,
                       "target_id": str(row.target_id), "actor_id": str(row.actor_id),
                       "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                       "reason": row.reason, "before": row.before, "after": row.after}
                      for row in audits],
    }
