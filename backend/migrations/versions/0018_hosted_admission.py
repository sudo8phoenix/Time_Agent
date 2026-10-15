"""Persist shared hosted-provider quota admission and crash-recoverable leases."""
from alembic import op
import sqlalchemy as sa

revision = "0018_hosted_admission"
down_revision = "0017_conversation_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("hosted_provider_admission",
        sa.Column("provider", sa.String(20), primary_key=True),
        sa.Column("owner", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("state", sa.JSON(), nullable=False))


def downgrade():
    op.drop_table("hosted_provider_admission")
