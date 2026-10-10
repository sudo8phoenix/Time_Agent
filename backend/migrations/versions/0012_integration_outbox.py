"""Transactional mock PMIS deliveries."""
from alembic import op
import sqlalchemy as sa
revision = "0012_integration_outbox"
down_revision = "0011_conversations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("integration_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_id", sa.Uuid(), sa.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state_revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("receipt", sa.JSON()),
        sa.UniqueConstraint("activity_id", "state_revision"))
    op.create_index("ix_outbox_pending", "integration_outbox", ["status", "next_attempt_at"])


def downgrade():
    op.drop_table("integration_outbox")
