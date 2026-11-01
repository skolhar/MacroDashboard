"""Original PR #16 research schema, pinned for forward migration compatibility.

Revision ID: research_1
Revises: market_data_1
"""
import sqlalchemy as sa
from alembic import op
from packages.domain.models import CycleInvestigation

revision = "research_1"
down_revision = "market_data_1"
branch_labels = None
depends_on = None

legacy_research = sa.Table(
    "research_evidence", sa.MetaData(),
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("cycle_id", sa.String(40), nullable=False, index=True),
    sa.Column("mechanism_id", sa.String(80), nullable=False),
    sa.Column("indicator_or_claim", sa.String(160), nullable=False),
    sa.Column("value_text", sa.Text, nullable=True),
    sa.Column("value_numeric", sa.Numeric(24, 8), nullable=True),
    sa.Column("unit", sa.String(40), nullable=True),
    sa.Column("period_start", sa.Date, nullable=False),
    sa.Column("period_end", sa.Date, nullable=False),
    sa.Column("source_name", sa.String(100), nullable=False),
    sa.Column("source_reference", sa.Text, nullable=False),
    sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("reliability_note", sa.Text, nullable=False),
    sa.Column("usage_basis", sa.Text, nullable=False),
    sa.Column("quality", sa.String(30), nullable=False),
    sa.Column("stance", sa.String(20), nullable=False),
    sa.Column("observation_key", sa.String(160), nullable=False, unique=True),
    sa.Column("entered_by", sa.String(100), nullable=False),
)


def upgrade():
    legacy_research.create(op.get_bind())
    CycleInvestigation.__table__.create(op.get_bind())


def downgrade():
    CycleInvestigation.__table__.drop(op.get_bind())
    legacy_research.drop(op.get_bind())
