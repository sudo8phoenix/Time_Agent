"""Store format-specific schedule source provenance."""
from alembic import op
import sqlalchemy as sa

revision = "0015_schedule_source_metadata"
down_revision = "0014_audited_reanalysis"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("schedule_source_metadata", sa.Column("source_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.alter_column("schedule_source_metadata", "source_metadata", server_default=None)


def downgrade():
    op.drop_column("schedule_source_metadata", "source_metadata")
