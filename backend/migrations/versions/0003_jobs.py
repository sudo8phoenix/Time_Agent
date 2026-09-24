from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_jobs"
down_revision = "0002_reports"
branch_labels = None
depends_on = None
UUID = postgresql.UUID(as_uuid=True)

def upgrade():
    op.create_table("jobs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", UUID, sa.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schedule_version_id", UUID, sa.ForeignKey("schedule_versions.id"), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(32)), sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("lease_token", sa.String(64)), sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)), sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.Text), sa.Column("model_version", sa.String(200)),
        sa.Column("prompt_version", sa.String(200)), sa.Column("config_version", sa.String(200)),
        sa.Column("extracted_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("proposal_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "report_id", name="uq_jobs_project_report"))
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"])
    op.create_index("ix_jobs_report_id", "jobs", ["report_id"])
    op.create_index("ix_jobs_state", "jobs", ["state"])
    op.create_index("ix_jobs_lease_token", "jobs", ["lease_token"])
    op.create_index("ix_jobs_lease_expires_at", "jobs", ["lease_expires_at"])

def downgrade():
    op.drop_table("jobs")
