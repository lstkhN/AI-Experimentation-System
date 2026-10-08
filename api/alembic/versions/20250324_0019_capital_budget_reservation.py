"""Add an atomic capital budget reservation balance."""
from alembic import op
import sqlalchemy as sa

revision = "20250324_0019"
down_revision = "20250323_0018"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "capital_plans",
        sa.Column("reserved_budget", sa.Float(), nullable=False, server_default="0"),
    )
    # Preserve commitments made before the reservation balance existed.
    op.execute(
        sa.text(
            "UPDATE capital_plans SET reserved_budget = COALESCE("
            "(SELECT SUM(allocated_spend) FROM capital_allocations "
            "WHERE capital_allocations.capital_plan_id = capital_plans.id), 0)"
        )
    )


def downgrade():
    op.drop_column("capital_plans", "reserved_budget")
