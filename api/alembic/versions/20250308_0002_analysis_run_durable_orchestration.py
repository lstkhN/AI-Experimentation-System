"""Add durable orchestration fields to analysis runs.

Revision ID: 20250308_0002
Revises: 20250220_0001
Create Date: 2025-03-08 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20250308_0002"
down_revision: Union[str, None] = "20250220_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUS_CHECK = "status IN ('queued', 'running', 'completed', 'failed')"


def upgrade() -> None:
    # batch_alter_table keeps this migration portable to SQLite, which cannot
    # alter a column or add a check constraint in place.
    with op.batch_alter_table("analysis_runs") as batch_op:
        batch_op.add_column(sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("attempt", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False))
        batch_op.add_column(sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_error", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=255), nullable=True))

    # Preserve existing runs while changing the old pending state to queued.
    op.execute("UPDATE analysis_runs SET queued_at = created_at WHERE queued_at IS NULL")
    op.execute("UPDATE analysis_runs SET status = 'queued' WHERE status = 'pending'")

    with op.batch_alter_table("analysis_runs") as batch_op:
        batch_op.alter_column("queued_at", nullable=False)
        batch_op.alter_column("status", server_default="queued", existing_type=sa.String(length=50))
        batch_op.create_check_constraint("ck_analysis_runs_status", _STATUS_CHECK)
        batch_op.create_unique_constraint(
            "uq_analysis_runs_project_idempotency_key", ["project_id", "idempotency_key"]
        )
        batch_op.create_index("ix_analysis_runs_idempotency_key", ["idempotency_key"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("analysis_runs") as batch_op:
        batch_op.drop_index("ix_analysis_runs_idempotency_key")
        batch_op.drop_constraint("uq_analysis_runs_project_idempotency_key", type_="unique")
        batch_op.drop_constraint("ck_analysis_runs_status", type_="check")
        batch_op.alter_column("status", server_default=None, existing_type=sa.String(length=50))
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("last_error")
        batch_op.drop_column("lease_until")
        batch_op.drop_column("max_attempts")
        batch_op.drop_column("attempt")
        batch_op.drop_column("started_at")
        batch_op.drop_column("queued_at")
