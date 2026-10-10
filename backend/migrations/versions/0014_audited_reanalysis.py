"""Add immutable child job lineage for explicit report reanalysis."""
from alembic import op
import sqlalchemy as sa

revision = "0014_audited_reanalysis"
down_revision = "0013_report_intake"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_jobs_project_report", "jobs", type_="unique")
    op.add_column("jobs", sa.Column("parent_job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), nullable=True))
    op.add_column("jobs", sa.Column("reanalysis_key", sa.String(200), nullable=True))
    op.add_column("jobs", sa.Column("reanalysis_actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("jobs", sa.Column("reanalysis_reason", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("config_snapshot", sa.JSON(), nullable=True))
    op.create_index("ix_jobs_parent_job_id", "jobs", ["parent_job_id"])
    op.create_index("uq_jobs_project_report_base", "jobs", ["project_id", "report_id"], unique=True,
                    postgresql_where=sa.text("parent_job_id IS NULL"))
    op.create_unique_constraint("uq_jobs_reanalysis_key", "jobs", ["reanalysis_key"])


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM jobs WHERE parent_job_id IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade audited reanalysis while child runs exist; preserve their lineage")
    op.drop_constraint("uq_jobs_reanalysis_key", "jobs", type_="unique")
    op.drop_index("uq_jobs_project_report_base", table_name="jobs")
    op.drop_index("ix_jobs_parent_job_id", table_name="jobs")
    op.drop_column("jobs", "config_snapshot")
    op.drop_column("jobs", "reanalysis_reason")
    op.drop_column("jobs", "reanalysis_actor_id")
    op.drop_column("jobs", "reanalysis_key")
    op.drop_column("jobs", "parent_job_id")
    op.create_unique_constraint("uq_jobs_project_report", "jobs", ["project_id", "report_id"])
