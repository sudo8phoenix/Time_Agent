"""Native schedule import provenance records."""

from alembic import op
import sqlalchemy as sa

revision = "0006_native_schedule_imports"
down_revision = "0005_w13_active_application"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "schedule_imports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_id", sa.Uuid(), sa.ForeignKey("files.id"), nullable=False, unique=True),
        sa.Column("source_format", sa.String(20), nullable=False),
        sa.Column("parser_version", sa.String(100), nullable=False),
        sa.Column("selected_source_project_id", sa.String(255)),
        sa.Column("preview", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("creator_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_mapping", sa.JSON()),
        sa.Column("mapped_content_hash", sa.String(64)),
        sa.Column("staged_schedule_version_id", sa.Uuid(), sa.ForeignKey("schedule_versions.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_schedule_imports_project_id", "schedule_imports", ["project_id"])
    op.create_table(
        "schedule_source_metadata",
        sa.Column(
            "schedule_version_id",
            sa.Uuid(),
            sa.ForeignKey("schedule_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "schedule_import_id",
            sa.Uuid(),
            sa.ForeignKey("schedule_imports.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("source_project_id", sa.String(255), nullable=False),
        sa.Column("source_file_hash", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(100), nullable=False),
        sa.Column("reviewed_mapping", sa.JSON(), nullable=False),
        sa.Column("mapping_hash", sa.String(64), nullable=False),
        sa.Column("task_metadata", sa.JSON(), nullable=False),
        sa.Column("wbs", sa.JSON(), nullable=False),
        sa.Column("relationships", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("schedule_source_metadata")
    op.drop_index("ix_schedule_imports_project_id", table_name="schedule_imports")
    op.drop_table("schedule_imports")
