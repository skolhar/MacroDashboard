"""Private exploratory evidence and human investigations.

Revision ID: research_1
Revises: market_data_1
"""
from alembic import op
from packages.domain.models import ResearchEvidence, CycleInvestigation

revision = "research_1"
down_revision = "market_data_1"
branch_labels = None
depends_on = None


def upgrade():
    ResearchEvidence.__table__.create(op.get_bind())
    CycleInvestigation.__table__.create(op.get_bind())


def downgrade():
    CycleInvestigation.__table__.drop(op.get_bind())
    ResearchEvidence.__table__.drop(op.get_bind())
