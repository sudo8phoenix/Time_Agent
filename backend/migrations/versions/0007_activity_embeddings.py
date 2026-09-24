"""Persist local activity embeddings for hybrid retrieval."""

from alembic import op
import sqlalchemy as sa


revision = "0007_activity_embeddings"
down_revision = "0006_native_schedule_imports"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "activity_embeddings",
        sa.Column(
            "activity_id",
            sa.Uuid(),
            sa.ForeignKey("activities.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model_revision", sa.String(255), primary_key=True),
        sa.Column("composed_text_hash", sa.String(64), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade():
    op.drop_table("activity_embeddings")
