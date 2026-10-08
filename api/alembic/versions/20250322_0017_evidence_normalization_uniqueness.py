"""Enforce one normalized evidence record per hypothesis/source cluster.

Revision ID: 20250322_0017
Revises: 20250321_0016
"""
from alembic import op
import sqlalchemy as sa

revision = "20250322_0017"
down_revision = "20250321_0016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "evidence",
        sa.Column("normalization_hypothesis_id", sa.Integer(), sa.ForeignKey("hypotheses.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index(
        "uq_evidence_normalization_hypothesis_cluster",
        "evidence",
        ["normalization_hypothesis_id", "source_cluster"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_evidence_normalization_hypothesis_cluster", table_name="evidence")
    op.drop_column("evidence", "normalization_hypothesis_id")
