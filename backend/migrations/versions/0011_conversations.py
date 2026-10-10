"""Persist project scoped text conversations and immutable turns."""
from alembic import op
import sqlalchemy as sa

revision = "0011_conversations"
down_revision = "0010_lifecycle_precision"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("creator_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("schedule_version_id", sa.Uuid(), sa.ForeignKey("schedule_versions.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("pending_question", sa.String(30)),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_conversations_project_id", "conversations", ["project_id"])
    op.create_index("ix_conversations_creator_id", "conversations", ["creator_id"])
    op.create_table("conversation_turns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("conversation_id", "ordinal"))
    op.create_index("ix_conversation_turns_conversation_id", "conversation_turns", ["conversation_id"])


def downgrade():
    op.drop_index("ix_conversation_turns_conversation_id", table_name="conversation_turns")
    op.drop_table("conversation_turns")
    op.drop_index("ix_conversations_creator_id", table_name="conversations")
    op.drop_index("ix_conversations_project_id", table_name="conversations")
    op.drop_table("conversations")
