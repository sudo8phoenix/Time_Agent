"""Install the pinned LangGraph PostgreSQL checkpoint schema.

Revision ID: 0009_langgraph_checkpoints
Revises: 0008_agent_runs

This snapshots checkpoint-postgres 3.1.2 migrations 0..9.  Ordinary workers
must not call ``PostgresSaver.setup()``.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_langgraph_checkpoints"
down_revision = "0008_agent_runs"
branch_labels = None
depends_on = None


def upgrade():
    migrations = op.create_table(
        "checkpoint_migrations",
        sa.Column("v", sa.Integer(), primary_key=True, autoincrement=False),
    )
    op.create_table(
        "checkpoints",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("parent_checkpoint_id", sa.Text()),
        sa.Column("type", sa.Text()),
        sa.Column("checkpoint", postgresql.JSONB(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id"),
    )
    op.create_table(
        "checkpoint_blobs",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), nullable=False, server_default=""),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("blob", sa.LargeBinary()),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "channel", "version"),
    )
    op.create_table(
        "checkpoint_writes",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("type", sa.Text()),
        sa.Column("blob", sa.LargeBinary(), nullable=False),
        sa.Column("task_path", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint(
            "thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"
        ),
    )
    # These are ordinary transactional indexes because all three tables are new
    # and empty.  The package's CREATE INDEX CONCURRENTLY statements cannot run
    # safely inside the repository's atomic Alembic revision.
    op.create_index("checkpoints_thread_id_idx", "checkpoints", ["thread_id"])
    op.create_index("checkpoint_blobs_thread_id_idx", "checkpoint_blobs", ["thread_id"])
    op.create_index("checkpoint_writes_thread_id_idx", "checkpoint_writes", ["thread_id"])
    op.bulk_insert(migrations, [{"v": value} for value in range(10)])


def downgrade():
    bind = op.get_bind()
    future_version = bind.execute(
        sa.text("SELECT max(v) FROM checkpoint_migrations")
    ).scalar_one_or_none()
    if future_version is not None and future_version > 9:
        raise RuntimeError("refusing to drop checkpoint tables owned by a newer saver")
    has_checkpoints = bind.execute(sa.text(
        "SELECT EXISTS ("
        "SELECT 1 FROM checkpoints UNION ALL "
        "SELECT 1 FROM checkpoint_blobs UNION ALL "
        "SELECT 1 FROM checkpoint_writes)"
    )).scalar_one()
    if has_checkpoints:
        raise RuntimeError("refusing to downgrade populated LangGraph checkpoint tables")
    nonterminal_runs = bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM agent_runs "
        "WHERE state IN ('created', 'running'))"
    )).scalar_one()
    if nonterminal_runs:
        raise RuntimeError("refusing to remove checkpoints while agent runs are active")
    op.drop_index("checkpoint_writes_thread_id_idx", table_name="checkpoint_writes")
    op.drop_index("checkpoint_blobs_thread_id_idx", table_name="checkpoint_blobs")
    op.drop_index("checkpoints_thread_id_idx", table_name="checkpoints")
    op.drop_table("checkpoint_writes")
    op.drop_table("checkpoint_blobs")
    op.drop_table("checkpoints")
    op.drop_table("checkpoint_migrations")
