"""Add durable capital plans, gates, and allocations.

Revision ID: 20250316_0010
Revises: 20250315_0009
"""
from alembic import op
import sqlalchemy as sa

revision = "20250316_0010"
down_revision = "20250315_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("capital_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("available_budget", sa.Float(), nullable=False),
        sa.Column("recommended_spend", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_capital_plans_project_id", "capital_plans", ["project_id"])
    op.create_table("capital_gates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("capital_plan_id", sa.Integer(), sa.ForeignKey("capital_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("recommended_spend", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unlock_condition", sa.JSON(), nullable=True), sa.Column("status", sa.String(length=20), nullable=False, server_default="LOCKED"),
        sa.Column("evaluation", sa.JSON(), nullable=True), sa.UniqueConstraint("capital_plan_id", "sequence", name="uq_capital_gate_plan_sequence"),
    )
    op.create_index("ix_capital_gates_capital_plan_id", "capital_gates", ["capital_plan_id"])
    op.create_table("capital_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("capital_plan_id", sa.Integer(), sa.ForeignKey("capital_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capital_gate_id", sa.Integer(), sa.ForeignKey("capital_gates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("requested_spend", sa.Float(), nullable=False), sa.Column("allocated_spend", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False), sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_capital_allocations_capital_plan_id", "capital_allocations", ["capital_plan_id"])
    op.create_index("ix_capital_allocations_capital_gate_id", "capital_allocations", ["capital_gate_id"])


def downgrade():
    op.drop_index("ix_capital_allocations_capital_gate_id", table_name="capital_allocations")
    op.drop_index("ix_capital_allocations_capital_plan_id", table_name="capital_allocations")
    op.drop_table("capital_allocations")
    op.drop_index("ix_capital_gates_capital_plan_id", table_name="capital_gates")
    op.drop_table("capital_gates")
    op.drop_index("ix_capital_plans_project_id", table_name="capital_plans")
    op.drop_table("capital_plans")
