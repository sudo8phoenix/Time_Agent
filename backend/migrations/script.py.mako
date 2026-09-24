"""${message}"""
from alembic import op
import sqlalchemy as sa
${upgrades if upgrades else ""}

def upgrade():
    ${upgrades or "pass"}

def downgrade():
    ${downgrades or "pass"}
