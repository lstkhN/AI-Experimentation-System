"""Persist resumable research pipeline artifacts.

Revision ID: 20250321_0016
Revises: 20250320_0015
"""
from alembic import op
import sqlalchemy as sa

revision = "20250321_0016"
down_revision = "20250320_0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "research_stage_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("analysis_run_id", sa.Integer(), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("checkpoint", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="ck_research_stage_runs_status"),
        sa.UniqueConstraint("analysis_run_id", "stage", name="uq_research_stage_run_stage"),
    )
    op.create_index("ix_research_stage_runs_analysis_run_id", "research_stage_runs", ["analysis_run_id"])
    op.create_table(
        "research_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("analysis_run_id", sa.Integer(), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_run_id", sa.Integer(), sa.ForeignKey("research_stage_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True), sa.Column("url", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True), sa.Column("source_metadata", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("analysis_run_id", "url", name="uq_research_document_run_url"),
    )
    for column in ("project_id", "analysis_run_id", "stage_run_id"):
        op.create_index("ix_research_documents_" + column, "research_documents", [column])
    op.create_table(
        "research_claims",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("document_id", sa.Integer(), sa.ForeignKey("research_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False), sa.Column("status", sa.String(length=20), nullable=False, server_default="candidate"),
        sa.Column("source_cluster", sa.String(length=255), nullable=False, server_default="unknown"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "claim", name="uq_research_claim_document_claim"),
    )
    op.create_index("ix_research_claims_document_id", "research_claims", ["document_id"])
    op.create_table(
        "research_verifications",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("claim_id", sa.Integer(), sa.ForeignKey("research_claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False), sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("methodology_available", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("source_quality", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("claim_id", name="uq_research_verification_claim"),
    )
    op.create_index("ix_research_verifications_claim_id", "research_verifications", ["claim_id"])
    # SQLite cannot add a table-level UNIQUE constraint after table creation.
    # A unique index enforces the same invariant on every supported dialect.
    op.add_column("evidence_candidates", sa.Column("promoted_evidence_id", sa.Integer(), sa.ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True))
    op.create_index("uq_evidence_candidates_promoted_evidence", "evidence_candidates", ["promoted_evidence_id"], unique=True)
    op.add_column("evidence", sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("evidence_candidates.id", ondelete="SET NULL"), nullable=True))
    op.create_index("uq_evidence_candidate_id", "evidence", ["candidate_id"], unique=True)
    # A non-null hash key makes source promotion idempotent even when URL is NULL.
    op.add_column("evidence_sources", sa.Column("identity_key", sa.String(length=64), nullable=True))
    op.execute("UPDATE evidence_sources SET identity_key = 'legacy:' || id WHERE identity_key IS NULL")
    with op.batch_alter_table("evidence_sources") as batch_op:
        batch_op.alter_column("identity_key", nullable=False)
        batch_op.create_unique_constraint("uq_evidence_source_project_identity", ["project_id", "identity_key"])


def downgrade():
    with op.batch_alter_table("evidence_sources") as batch_op:
        batch_op.drop_constraint("uq_evidence_source_project_identity", type_="unique")
    op.drop_column("evidence_sources", "identity_key")
    op.drop_index("uq_evidence_candidate_id", table_name="evidence")
    op.drop_column("evidence", "candidate_id")
    op.drop_index("uq_evidence_candidates_promoted_evidence", table_name="evidence_candidates")
    op.drop_column("evidence_candidates", "promoted_evidence_id")
    op.drop_table("research_verifications")
    op.drop_table("research_claims")
    op.drop_table("research_documents")
    op.drop_table("research_stage_runs")
