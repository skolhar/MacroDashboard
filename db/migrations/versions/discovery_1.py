"""Private anomaly discovery snapshots and provisional hypotheses.

Revision ID: discovery_1
Revises: research_2
"""
from alembic import op
from packages.domain.models import DiscoverySnapshot, DiscoveryHypothesis

revision = "discovery_1"
down_revision = "research_2"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    DiscoverySnapshot.__table__.create(bind)
    DiscoveryHypothesis.__table__.create(bind)


def downgrade():
    raise RuntimeError("discovery_1 downgrade would erase private research provenance; restore from reviewed backup")
