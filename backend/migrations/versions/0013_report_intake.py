"""Revisioned report mappings and immutable intake provenance."""
from alembic import op
import sqlalchemy as sa
revision = '0013_report_intake'
down_revision = '0012_integration_outbox'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('reports', sa.Column('ingestion_metadata', sa.JSON(), nullable=True))
    op.create_table('report_mappings',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('template', sa.String(100), nullable=False),
        sa.Column('header_signature', sa.String(64), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('spec', sa.JSON(), nullable=False),
        sa.Column('actor_id', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('project_id', 'template', 'header_signature', 'revision'))


def downgrade():
    op.drop_table('report_mappings')
    op.drop_column('reports', 'ingestion_metadata')
