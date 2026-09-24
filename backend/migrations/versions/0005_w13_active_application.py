"""W-13 integrity constraint for one active application per observation."""
from alembic import op

revision = "0005_w13_active_application"
down_revision = "0004_review"
branch_labels = None
depends_on = None

def upgrade():
    op.create_index(
        "uq_progress_events_active_observation", "progress_events", ["observation_id"],
        unique=True, postgresql_where="supersedes_event_id IS NULL"
    )

def downgrade():
    op.drop_index("uq_progress_events_active_observation", table_name="progress_events")
