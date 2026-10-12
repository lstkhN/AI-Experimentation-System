"""Add durable decision-quality research artifacts.

Revision ID: 20250327_0022
Revises: 20250326_0021
"""
from alembic import op
import sqlalchemy as sa

revision = "20250327_0022"
down_revision = "20250326_0021"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("research_stage_runs", sa.Column("output", sa.JSON(), nullable=True))
    op.add_column("research_verifications", sa.Column("freshness_score", sa.Float(), nullable=False, server_default="1"))
    op.add_column("research_verifications", sa.Column("independence_score", sa.Float(), nullable=False, server_default="0"))
    op.add_column("research_verifications", sa.Column("provenance", sa.JSON(), nullable=True))
    op.create_table(
        "research_verification_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("research_claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("verification_id", sa.Integer(), sa.ForeignKey("research_verifications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_cluster", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("freshness_score", sa.Float(), nullable=False),
        sa.Column("independence_score", sa.Float(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("claim_id", "source_cluster", name="uq_research_verification_attempt_claim_cluster"),
    )
    op.create_index("ix_research_verification_attempts_claim_id", "research_verification_attempts", ["claim_id"])
    op.create_table(
        "research_claim_contradictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("research_claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contradicts_claim_id", sa.Integer(), sa.ForeignKey("research_claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("claim_id < contradicts_claim_id", name="ck_research_claim_contradictions_order"),
        sa.UniqueConstraint("claim_id", "contradicts_claim_id", name="uq_research_claim_contradiction_pair"),
    )
    op.create_index("ix_research_claim_contradictions_claim_id", "research_claim_contradictions", ["claim_id"])


def downgrade():
    op.drop_table("research_claim_contradictions")
    op.drop_table("research_verification_attempts")
    op.drop_column("research_verifications", "provenance")
    op.drop_column("research_verifications", "independence_score")
    op.drop_column("research_verifications", "freshness_score")
    op.drop_column("research_stage_runs", "output")
