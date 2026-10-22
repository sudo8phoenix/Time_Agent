"""Share bounded login admission counters across API workers and restarts."""
from alembic import op
import sqlalchemy as sa

revision = '0019_login_throttle'
down_revision = '0018_hosted_admission'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('login_throttle_buckets',
        sa.Column('key_hash', sa.String(64), primary_key=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('attempts >= 0', name='login_throttle_nonnegative'))
    op.create_index('ix_login_throttle_expiry', 'login_throttle_buckets', ['expires_at'])


def downgrade():
    op.drop_table('login_throttle_buckets')
