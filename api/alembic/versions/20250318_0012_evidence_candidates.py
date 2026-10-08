"""Add dedicated research evidence candidates."""
from alembic import op
import sqlalchemy as sa
revision = "20250318_0012"
down_revision = "20250317_0011"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "evidence_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hypothesis_id", sa.Integer(), sa.ForeignKey("hypotheses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="candidate"),
        sa.Column("verification_reason", sa.Text(), nullable=True),
        sa.Column("source_quality", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_cluster", sa.String(255), nullable=False, server_default="unknown"),
        sa.Column("observed_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('candidate','verified','rejected')", name="ck_evidence_candidates_status"),
    )
    op.create_index("ix_evidence_candidates_project_id", "evidence_candidates", ["project_id"])
    op.create_index("ix_evidence_candidates_hypothesis_id", "evidence_candidates", ["hypothesis_id"])

def downgrade():
    op.drop_index("ix_evidence_candidates_hypothesis_id", table_name="evidence_candidates")
    op.drop_index("ix_evidence_candidates_project_id", table_name="evidence_candidates")
    op.drop_table("evidence_candidates")
