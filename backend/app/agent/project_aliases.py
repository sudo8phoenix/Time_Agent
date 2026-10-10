"""Reviewer-approved alias snapshots in the immutable audit ledger."""
from types import SimpleNamespace
from sqlalchemy import select
from app.db.models import AuditEvent


def alias_snapshot(db, project_id):
    event = db.scalar(select(AuditEvent).where(
        AuditEvent.target_id == project_id, AuditEvent.target_type == "project_aliases",
        AuditEvent.action == "approve_aliases",
    ).order_by(AuditEvent.after["revision"].as_integer().desc()))
    return event.after if event else {"revision": 0, "aliases": {}}


def with_project_aliases(db, project_id, activities):
    snapshot = alias_snapshot(db, project_id)
    result = []
    for row in activities:
        data = {column.key: getattr(row, column.key) for column in row.__table__.columns}
        approved = snapshot["aliases"].get(str(row.id), [])
        data["aliases"] = "; ".join(filter(None, [row.aliases, *approved])) or None
        result.append(SimpleNamespace(**data))
    return result
