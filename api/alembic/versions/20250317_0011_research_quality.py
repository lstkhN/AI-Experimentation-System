"""Add reviewed-evidence lifecycle fields.

Revision ID: 20250317_0011
Revises: 20250316_0010
"""
from alembic import op
import sqlalchemy as sa

revision = "20250317_0011"
down_revision = "20250316_0010"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("evidence") as batch:
        batch.add_column(sa.Column("candidate_claim", sa.Text(), nullable=True))
        # Existing manually-created evidence predates candidates and remains reviewed.
        batch.add_column(sa.Column("evidence_status", sa.String(length=20), nullable=False, server_default="verified"))
        batch.add_column(sa.Column("verification_reason", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "ck_evidence_status", "evidence_status IN ('candidate', 'verified', 'rejected')"
        )


def downgrade():
    with op.batch_alter_table("evidence") as batch:
        batch.drop_constraint("ck_evidence_status", type_="check")
        batch.drop_column("verification_reason")
        batch.drop_column("evidence_status")
        batch.drop_column("candidate_claim")
