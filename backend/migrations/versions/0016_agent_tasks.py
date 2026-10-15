"""Add durable child task identity and sanitized result records."""
from alembic import op
import sqlalchemy as sa


revision = "0016_agent_tasks"
down_revision = "0015_schedule_source_metadata"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_task_id", sa.Uuid(), sa.ForeignKey("agent_tasks.id", ondelete="CASCADE")),
        sa.Column("agent_role", sa.String(32), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_version_id", sa.Uuid(), sa.ForeignKey("schedule_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observation_key", sa.String(100)),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.String(80), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_references", sa.JSON(), nullable=False),
        sa.Column("output_references", sa.JSON(), nullable=False),
        sa.Column("evidence_references", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("actual_usage", sa.JSON(), nullable=False),
        sa.Column("safe_summary", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(32)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "parent_task_id", "agent_role", "attempt", "observation_key",
                            name="uq_agent_tasks_identity"),
        sa.CheckConstraint("attempt >= 1", name="ck_agent_tasks_attempt_positive"),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'failed', 'skipped')", name="ck_agent_tasks_status"),
        sa.CheckConstraint("status = 'running' OR finished_at IS NOT NULL", name="ck_agent_tasks_finished_state"),
    )
    op.create_index("ix_agent_tasks_run_parent", "agent_tasks", ["run_id", "parent_task_id"])
    op.create_index("ix_agent_tasks_run_role", "agent_tasks", ["run_id", "agent_role"])


def downgrade():
    op.drop_index("ix_agent_tasks_run_role", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_run_parent", table_name="agent_tasks")
    op.drop_table("agent_tasks")
