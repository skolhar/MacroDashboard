"""Initial provenance, scores, alerts and event tables.

Revision ID: 0001
Revises:
"""
from alembic import op
from packages.domain.models import Base
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    Base.metadata.create_all(op.get_bind())

def downgrade():
    Base.metadata.drop_all(op.get_bind())
