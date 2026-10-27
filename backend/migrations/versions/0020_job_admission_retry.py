"""Defer cooled reports without blocking the shared queue."""
from alembic import op
import sqlalchemy as sa

revision = "0020_job_admission_retry"
down_revision = "0019_login_throttle"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("admission_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_jobs_admission", "jobs", ["state", "admission_retry_at", "created_at"])


def downgrade():
    op.drop_index("ix_jobs_admission", table_name="jobs")
    op.drop_column("jobs", "admission_retry_at")
