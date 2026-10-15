"""Add private durable conversation analysis tasks and model checkpoints."""
from alembic import op
import sqlalchemy as sa

revision = "0017_conversation_tasks"
down_revision = "0016_agent_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("conversation_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schedule_version_id", sa.Uuid(), sa.ForeignKey("schedule_versions.id"), nullable=False),
        sa.Column("input_revision", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("conversation_id", "input_revision"),
        sa.CheckConstraint("attempts >= 0 AND model_calls >= 0", name="ck_conversation_task_usage"),
        sa.CheckConstraint("state IN ('queued', 'running', 'succeeded', 'failed', 'stale', 'cancelled')", name="ck_conversation_task_state"))
    op.create_index("ix_conversation_tasks_pending", "conversation_tasks", ["state", "next_attempt_at"])
    op.create_table("conversation_task_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("conversation_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.UniqueConstraint("task_id", "ordinal"))


def downgrade():
    op.drop_table("conversation_task_calls")
    op.drop_index("ix_conversation_tasks_pending", table_name="conversation_tasks")
    op.drop_table("conversation_tasks")
