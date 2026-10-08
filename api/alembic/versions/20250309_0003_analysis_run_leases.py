"""Add ownership and retry scheduling fields for durable run workers.

Revision ID: 20250309_0003
Revises: 20250308_0002
"""
from alembic import op
import sqlalchemy as sa

revision = "20250309_0003"
down_revision = "20250308_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("analysis_runs") as batch_op:
        batch_op.add_column(sa.Column("lease_token", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("available_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE analysis_runs SET available_at = queued_at WHERE available_at IS NULL")
    with op.batch_alter_table("analysis_runs") as batch_op:
        batch_op.alter_column("available_at", nullable=False)
        batch_op.create_index("ix_analysis_runs_lease_token", ["lease_token"], unique=False)
        batch_op.create_index("ix_analysis_runs_available_at", ["available_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("analysis_runs") as batch_op:
        batch_op.drop_index("ix_analysis_runs_available_at")
        batch_op.drop_index("ix_analysis_runs_lease_token")
        batch_op.drop_column("available_at")
        batch_op.drop_column("heartbeat_at")
        batch_op.drop_column("lease_token")
