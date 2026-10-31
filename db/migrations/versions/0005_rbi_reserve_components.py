"""Keep reported RBI WSS USD-million components alongside normalized reserves.

Revision ID: 0005
Revises: 0004
"""
from alembic import op
from packages.domain.models import RBIReserveComponent

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    RBIReserveComponent.__table__.create(op.get_bind())


def downgrade():
    RBIReserveComponent.__table__.drop(op.get_bind())
