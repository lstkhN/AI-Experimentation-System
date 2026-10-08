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
    # SQLite requires table recreation to add a foreign key.
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.add_column(sa.Column("normalization_hypothesis_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_evidence_normalization_hypothesis", "hypotheses",
            ["normalization_hypothesis_id"], ["id"], ondelete="CASCADE",
        )
    op.create_index(
        "uq_evidence_normalization_hypothesis_cluster",
        "evidence",
        ["normalization_hypothesis_id", "source_cluster"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_evidence_normalization_hypothesis_cluster", table_name="evidence")
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.drop_constraint("fk_evidence_normalization_hypothesis", type_="foreignkey")
        batch_op.drop_column("normalization_hypothesis_id")
