"""Add capital allocation idempotency."""
from alembic import op
import sqlalchemy as sa
revision="20250320_0015"; down_revision="20250320_0014"; branch_labels=None; depends_on=None
def upgrade():
    op.add_column("capital_allocations", sa.Column("idempotency_key", sa.String(length=120), nullable=True))
    op.create_index("uq_capital_allocations_plan_idempotency", "capital_allocations", ["capital_plan_id", "idempotency_key"], unique=True)
def downgrade():
    op.drop_index("uq_capital_allocations_plan_idempotency", table_name="capital_allocations")
    op.drop_column("capital_allocations", "idempotency_key")
