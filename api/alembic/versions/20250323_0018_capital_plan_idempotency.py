"""add capital plan idempotency key

Revision ID: 20250323_0018_capital
Revises: 20250322_0017
Create Date: 2025-03-23
"""
from alembic import op
import sqlalchemy as sa

revision = "20250323_0018_capital"
down_revision = "20250322_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("capital_plans") as batch_op:
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=255), nullable=True))
        batch_op.create_unique_constraint("uq_capital_plan_project_idempotency", ["project_id", "idempotency_key"])


def downgrade() -> None:
    with op.batch_alter_table("capital_plans") as batch_op:
        batch_op.drop_constraint("uq_capital_plan_project_idempotency", type_="unique")
        batch_op.drop_column("idempotency_key")
