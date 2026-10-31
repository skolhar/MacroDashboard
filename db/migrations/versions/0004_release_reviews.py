"""Durable reviewed source releases and observation linkage.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa
from packages.domain.models import SourceReleaseReview

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    SourceReleaseReview.__table__.create(op.get_bind())
    with op.batch_alter_table("observations") as batch:
        batch.add_column(sa.Column("release_review_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rate_kind", sa.String(length=60), nullable=True))
        batch.create_foreign_key("fk_observations_release_review", "source_release_reviews", ["release_review_id"], ["id"])
        batch.create_index("ix_observations_release_review_id", ["release_review_id"])


def downgrade():
    with op.batch_alter_table("observations") as batch:
        batch.drop_index("ix_observations_release_review_id")
        batch.drop_constraint("fk_observations_release_review", type_="foreignkey")
        batch.drop_column("rate_kind")
        batch.drop_column("release_review_id")
    SourceReleaseReview.__table__.drop(op.get_bind())
