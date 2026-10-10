"""Precision-preserving lifecycle state and accepted endpoint metadata.

Existing date values remain dates; no time or precision is backfilled.
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_lifecycle_precision"
down_revision = "0009_langgraph_checkpoints"
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in (
        ("actual_start_time", sa.Time()), ("actual_finish_time", sa.Time()),
        ("actual_start_precision", sa.String(10)), ("actual_finish_precision", sa.String(10)),
        ("lifecycle_status", sa.String(30)),
        ("lifecycle_source_version_id", sa.Uuid()),
        ("lifecycle_start_event_id", sa.Uuid()), ("lifecycle_finish_event_id", sa.Uuid()),
    ):
        op.add_column("activity_states", sa.Column(name, kind, nullable=True))
    op.create_foreign_key("fk_activity_states_lifecycle_source_version", "activity_states", "schedule_versions", ["lifecycle_source_version_id"], ["id"])
    op.create_foreign_key("fk_activity_states_lifecycle_start_event", "activity_states", "progress_events", ["lifecycle_start_event_id"], ["id"])
    op.create_foreign_key("fk_activity_states_lifecycle_finish_event", "activity_states", "progress_events", ["lifecycle_finish_event_id"], ["id"])
    for name, kind in (
        ("lifecycle_scope", sa.String(30)), ("endpoint_time", sa.Time()),
        ("endpoint_precision", sa.String(10)), ("endpoint_timezone", sa.String(64)),
        ("endpoint_basis", sa.String(40)), ("endpoint_raw_expression", sa.String(500)),
        ("endpoint_instant", sa.DateTime(timezone=True)), ("endpoint_evidence", sa.JSON()),
        ("source_schedule_version_id", sa.Uuid()),
    ):
        op.add_column("progress_events", sa.Column(name, kind, nullable=True))
    op.create_foreign_key("fk_progress_events_source_schedule_version", "progress_events", "schedule_versions", ["source_schedule_version_id"], ["id"])


def downgrade():
    op.drop_constraint("fk_progress_events_source_schedule_version", "progress_events", type_="foreignkey")
    for name in ("source_schedule_version_id", "endpoint_evidence", "endpoint_instant", "endpoint_raw_expression", "endpoint_basis", "endpoint_timezone", "endpoint_precision", "endpoint_time", "lifecycle_scope"):
        op.drop_column("progress_events", name)
    for name in ("lifecycle_finish_event", "lifecycle_start_event", "lifecycle_source_version"):
        op.drop_constraint(f"fk_activity_states_{name}", "activity_states", type_="foreignkey")
    for name in ("lifecycle_finish_event_id", "lifecycle_start_event_id", "lifecycle_source_version_id", "lifecycle_status", "actual_finish_precision", "actual_start_precision", "actual_finish_time", "actual_start_time"):
        op.drop_column("activity_states", name)
