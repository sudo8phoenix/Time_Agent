"""Add bounded agent-run telemetry records.

Revision ID: 0008_agent_runs
Revises: 0007_activity_embeddings
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_agent_runs"
down_revision = "0007_activity_embeddings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("graph_version", sa.String(100), nullable=False),
        sa.Column("state_schema_version", sa.String(100), nullable=False),
        sa.Column("framework_version", sa.String(100), nullable=False),
        sa.Column("thread_id", sa.String(255), nullable=False),
        sa.Column("execution_mode", sa.String(16), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("current_node", sa.String(64)),
        sa.Column("counters", sa.JSON(), nullable=False),
        sa.Column("model_metadata", sa.JSON(), nullable=False),
        sa.Column("prompt_metadata", sa.JSON(), nullable=False),
        sa.Column("config_metadata", sa.JSON(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.String(1000)),
        sa.UniqueConstraint("job_id", name="uq_agent_runs_job_id"),
        sa.UniqueConstraint("thread_id", name="uq_agent_runs_thread_id"),
        sa.CheckConstraint(
            "state IN ('created', 'running', 'ready_for_review', 'failed', 'stale', "
            "'cancelled')",
            name="ck_agent_runs_state",
        ),
        sa.CheckConstraint(
            "execution_mode IN ('legacy', 'graph')", name="ck_agent_runs_execution_mode"
        ),
        sa.CheckConstraint(
            "state IN ('failed', 'stale', 'cancelled') "
            "OR (error_code IS NULL AND error_message IS NULL)",
            name="ck_agent_runs_error_state",
        ),
    )
    op.create_index("ix_agent_runs_job_id", "agent_runs", ["job_id"])

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("node", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("input_hash", sa.String(64)),
        sa.Column("output_hash", sa.String(64)),
        sa.Column("sanitized_summary", sa.JSON(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.String(1000)),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_agent_steps_run_ordinal"),
        sa.UniqueConstraint(
            "run_id", "node", "attempt", name="uq_agent_steps_run_node_attempt"
        ),
        sa.CheckConstraint("ordinal >= 1", name="ck_agent_steps_ordinal_positive"),
        sa.CheckConstraint("attempt >= 1", name="ck_agent_steps_attempt_positive"),
        sa.CheckConstraint(
            "state IN ('running', 'succeeded', 'failed', 'skipped')",
            name="ck_agent_steps_state",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_agent_steps_duration_nonnegative"
        ),
        sa.CheckConstraint(
            "state <> 'running' OR (finished_at IS NULL AND duration_ms IS NULL)",
            name="ck_agent_steps_running_unfinished",
        ),
        sa.CheckConstraint(
            "state = 'failed' OR (error_code IS NULL AND error_message IS NULL)",
            name="ck_agent_steps_error_state",
        ),
    )
    op.create_index("ix_agent_steps_run_ordinal", "agent_steps", ["run_id", "ordinal"])

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "step_id",
            sa.Uuid(),
            sa.ForeignKey("agent_steps.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("sanitized_input_summary", sa.JSON(), nullable=False),
        sa.Column("sanitized_output_summary", sa.JSON(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.String(1000)),
        sa.UniqueConstraint(
            "step_id", "tool_name", "attempt", name="uq_agent_tool_calls_attempt"
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_agent_tool_calls_attempt_positive"),
        sa.CheckConstraint(
            "state IN ('running', 'succeeded', 'failed', 'skipped')",
            name="ck_agent_tool_calls_state",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_agent_tool_calls_duration_nonnegative",
        ),
        sa.CheckConstraint(
            "state <> 'running' OR (finished_at IS NULL AND duration_ms IS NULL)",
            name="ck_agent_tool_calls_running_unfinished",
        ),
        sa.CheckConstraint(
            "state = 'failed' OR (error_code IS NULL AND error_message IS NULL)",
            name="ck_agent_tool_calls_error_state",
        ),
    )
    op.create_index("ix_agent_tool_calls_step_id", "agent_tool_calls", ["step_id"])


def downgrade():
    op.drop_index("ix_agent_tool_calls_step_id", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")
    op.drop_index("ix_agent_steps_run_ordinal", table_name="agent_steps")
    op.drop_table("agent_steps")
    op.drop_index("ix_agent_runs_job_id", table_name="agent_runs")
    op.drop_table("agent_runs")
