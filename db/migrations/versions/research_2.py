"""Separate raw research facts from causal interpretations and freeze assessments.

Revision ID: research_2
Revises: research_1
"""
from datetime import datetime, timezone
import json
import sqlalchemy as sa
from alembic import op
from packages.domain.models import ResearchInterpretation, CycleAssessmentSnapshot

revision = "research_2"
down_revision = "research_1"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    op.add_column("research_evidence", sa.Column("indicator_key", sa.String(100), nullable=True))
    op.add_column("research_evidence", sa.Column("frequency", sa.String(20), nullable=True))
    op.add_column("research_evidence", sa.Column("revision_id", sa.String(80), nullable=True))
    old = bind.execute(sa.text("SELECT id, cycle_id, mechanism_id, stance, entered_by FROM research_evidence")).mappings().all()
    for row in old:
        bind.execute(sa.text("UPDATE research_evidence SET indicator_key=:key, frequency='event', revision_id='legacy-v1' WHERE id=:id"), {"key": f"legacy_observation_{row['id']}", "id": row["id"]})
    ResearchInterpretation.__table__.create(bind)
    CycleAssessmentSnapshot.__table__.create(bind)
    now = datetime.now(timezone.utc)
    for row in old:
        bind.execute(ResearchInterpretation.__table__.insert().values(
            observation_id=row["id"], related_observation_id=None, cycle_id=row["cycle_id"],
            mechanism_id=row["mechanism_id"], evidence_type="trend", stance=row["stance"],
            rationale="Legacy PR #16 stance lacked a documented causal rationale; retained for audit, never a feedback link.",
            alternatives_json=json.dumps(["Legacy alternative explanations were not recorded"]),
            interpretation_key=f"legacy_pr16_{row['id']}", revision_id="legacy-v1",
            supersedes_id=None, assessed_at=now, entered_by=row["entered_by"],
        ))
    with op.batch_alter_table("research_evidence") as batch:
        batch.alter_column("indicator_key", existing_type=sa.String(100), nullable=False)
        batch.alter_column("frequency", existing_type=sa.String(20), nullable=False)
        batch.alter_column("revision_id", existing_type=sa.String(80), nullable=False)
        batch.drop_index("ix_research_evidence_cycle_id")
        batch.drop_column("cycle_id")
        batch.drop_column("mechanism_id")
        batch.drop_column("stance")
        batch.create_index("ix_research_evidence_indicator_key", ["indicator_key"])


def downgrade():
    raise RuntimeError("research_2 downgrade would erase interpretation provenance; export and restore from a reviewed backup")
