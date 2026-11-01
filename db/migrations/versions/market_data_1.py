"""Separate, append-only secondary market OHLCV and fetch status.

Revision ID: market_data_1
Revises: 0004

Independent from open Phase 5 revision 0005. Merge heads after PR ordering is
decided; do not silently conflate these different observation types.
"""
from alembic import op
from packages.domain.models import MarketBar, MarketFetchRun

revision = "market_data_1"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    MarketBar.__table__.create(op.get_bind())
    MarketFetchRun.__table__.create(op.get_bind())


def downgrade():
    MarketFetchRun.__table__.drop(op.get_bind())
    MarketBar.__table__.drop(op.get_bind())
