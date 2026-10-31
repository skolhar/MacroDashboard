"""Operator identities, administrative audit and shared rate counters.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
from packages.domain.models import OperatorCredential, AdminAudit, RateLimitCounter, AlertEvaluation

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for model in (OperatorCredential, AdminAudit, RateLimitCounter, AlertEvaluation):
        model.__table__.create(bind)


def downgrade():
    bind = op.get_bind()
    for model in (AlertEvaluation, RateLimitCounter, AdminAudit, OperatorCredential):
        model.__table__.drop(bind)
