from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="0002_reports"; down_revision="0001_persistence_foundation"; branch_labels=None; depends_on=None
UUID=postgresql.UUID(as_uuid=True)
def upgrade():
    op.create_table("files",sa.Column("id",UUID,primary_key=True),sa.Column("project_id",UUID,sa.ForeignKey("projects.id",ondelete="CASCADE"),nullable=False),sa.Column("original_filename",sa.String(255),nullable=False),sa.Column("storage_key",sa.String(255),nullable=False,unique=True),sa.Column("sha256",sa.String(64),nullable=False),sa.Column("mime_type",sa.String(120),nullable=False),sa.Column("size",sa.Integer,nullable=False),sa.Column("source_kind",sa.String(30),nullable=False),sa.Column("uploader_id",UUID,sa.ForeignKey("users.id")))
    op.create_table("reports",sa.Column("id",UUID,primary_key=True),sa.Column("project_id",UUID,sa.ForeignKey("projects.id",ondelete="CASCADE"),nullable=False),sa.Column("file_id",UUID,sa.ForeignKey("files.id")),sa.Column("report_date",sa.Date),sa.Column("report_date_evidence",sa.Text),sa.Column("source_label",sa.String(255)),sa.Column("source_revision",sa.String(100)),sa.Column("content_hash",sa.String(64),nullable=False),sa.Column("parsing_warnings",sa.Text),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now()),sa.UniqueConstraint("project_id","content_hash"))
    op.create_table("fragments",sa.Column("id",UUID,primary_key=True),sa.Column("report_id",UUID,sa.ForeignKey("reports.id",ondelete="CASCADE"),nullable=False),sa.Column("ordinal",sa.Integer,nullable=False),sa.Column("locator",sa.String(255),nullable=False),sa.Column("original_text",sa.Text,nullable=False),sa.Column("normalised_text",sa.Text,nullable=False),sa.Column("normalisation_version",sa.String(30),nullable=False),sa.Column("ocr_status",sa.String(30),nullable=False),sa.UniqueConstraint("report_id","ordinal"))
def downgrade():
    op.drop_table("fragments"); op.drop_table("reports"); op.drop_table("files")
