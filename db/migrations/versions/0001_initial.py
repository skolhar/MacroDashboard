"""Initial provenance, scores, alerts and event tables.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("indicator_definitions",
        sa.Column("id", sa.String(100), primary_key=True), sa.Column("display_name", sa.String(150), nullable=False),
        sa.Column("cycle", sa.String(30), nullable=False), sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("frequency", sa.String(40), nullable=False), sa.Column("direction_of_stress", sa.String(30), nullable=False),
        sa.Column("max_age_hours", sa.Integer(), nullable=False), sa.Column("publication_lag_days", sa.Integer(), nullable=False),
        sa.Column("transform", sa.String(50), nullable=False), sa.Column("required_for_score", sa.Boolean(), nullable=False),
        sa.Column("source_priority", sa.Text(), nullable=False))
    op.create_table("observations",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("indicator_id", sa.String(100), sa.ForeignKey("indicator_definitions.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False), sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(24, 8), nullable=False), sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False), sa.Column("source_url", sa.Text()),
        sa.Column("vintage_id", sa.String(100), nullable=False), sa.Column("quality", sa.String(30), nullable=False),
        sa.Column("is_revision", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("indicator_id", "period_start", "period_end", "provider", "vintage_id"))
    op.create_index("ix_observations_indicator_id", "observations", ["indicator_id"])
    op.create_index("ix_observations_published_at", "observations", ["published_at"])
    op.create_table("raw_snapshots", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("provider", sa.String(100), nullable=False), sa.Column("content_hash", sa.String(64), unique=True, nullable=False), sa.Column("received_at", sa.DateTime(timezone=True), nullable=False), sa.Column("source_url", sa.Text()))
    op.create_table("score_snapshots", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("as_of", sa.DateTime(timezone=True), nullable=False), sa.Column("ruleset_version", sa.String(40), nullable=False), sa.Column("total_score", sa.Numeric(6, 2)), sa.Column("coverage", sa.Numeric(5, 4), nullable=False), sa.Column("payload_json", sa.Text(), nullable=False))
    op.create_table("alert_events", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("rule_id", sa.String(100), nullable=False), sa.Column("ruleset_version", sa.String(40), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("severity", sa.String(30)), sa.Column("start_at", sa.DateTime(timezone=True), nullable=False), sa.Column("end_at", sa.DateTime(timezone=True)), sa.Column("fired_at", sa.DateTime(timezone=True)), sa.Column("confirmed_at", sa.DateTime(timezone=True)), sa.Column("evidence_json", sa.Text(), nullable=False), sa.Column("deduplication_key", sa.String(200), unique=True, nullable=False), sa.Column("acknowledged_at", sa.DateTime(timezone=True)))
    op.create_table("policy_events", sa.Column("id", sa.String(100), primary_key=True), sa.Column("event_at", sa.DateTime(timezone=True), nullable=False), sa.Column("type", sa.String(60), nullable=False), sa.Column("description", sa.Text(), nullable=False), sa.Column("source_url", sa.Text()), sa.Column("status", sa.String(20), nullable=False), sa.Column("affected_indicators_json", sa.Text(), nullable=False))

def downgrade():
    op.drop_table("policy_events")
    op.drop_table("alert_events")
    op.drop_table("score_snapshots")
    op.drop_table("raw_snapshots")
    op.drop_index("ix_observations_published_at", table_name="observations")
    op.drop_index("ix_observations_indicator_id", table_name="observations")
    op.drop_table("observations")
    op.drop_table("indicator_definitions")
