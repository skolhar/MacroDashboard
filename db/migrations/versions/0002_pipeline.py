"""Add provenance separation and ingestion/alert audit tables.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
from packages.domain.models import IngestionRun, AlertTransition

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("observations", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("observations", sa.Column("source_identifier", sa.String(100), nullable=True))
    op.add_column("observations", sa.Column("source_reference", sa.Text(), nullable=True))
    op.add_column("observations", sa.Column("content_hash", sa.String(64), nullable=True))
    op.execute("UPDATE observations SET is_demo = true WHERE quality = 'demo'")
    IngestionRun.__table__.create(op.get_bind())
    AlertTransition.__table__.create(op.get_bind())


def downgrade():
    AlertTransition.__table__.drop(op.get_bind())
    IngestionRun.__table__.drop(op.get_bind())
    op.drop_column("observations", "content_hash")
    op.drop_column("observations", "source_reference")
    op.drop_column("observations", "source_identifier")
    op.drop_column("observations", "is_demo")
