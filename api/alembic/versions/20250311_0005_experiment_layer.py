"""Add deterministic experiment templates and project proposals.

Revision ID: 20250311_0005
Revises: 20250310_0004
"""
from alembic import op
import sqlalchemy as sa

# Migration data is intentionally immutable. Do not import the application
# catalog here: later catalog edits must not change this historical upgrade.
_TEMPLATE_ROWS = (
    {"template_key": "problem_interviews_v1", "name": "Problem interviews", "category": "problem", "description": "Validate that a painful recurring problem exists.", "rules": {"target": {"metric": "participants reporting recurring pain", "unit": "interviews"}, "sample": {"minimum": 10, "unit": "interviews"}, "pass_rule": {"operator": ">=", "threshold": "7 of 10"}, "partial_rule": {"range": "4-6 of 10"}, "fail_rule": {"range": "0-3 of 10"}, "stop_rule": "Stop after 10 completed interviews or after 3 consecutive interviews show no pain."}, "version": 1},
    {"template_key": "landing_page_v1", "name": "Landing page demand test", "category": "demand", "description": "Measure qualified intent from a concise value proposition.", "rules": {"target": {"metric": "qualified conversion rate", "unit": "unique visitors"}, "sample": {"minimum": 200, "unit": "unique visitors"}, "pass_rule": {"operator": ">=", "threshold": "10%"}, "partial_rule": {"range": "5%-9.99%"}, "fail_rule": {"range": "<5%"}, "stop_rule": "Stop at 300 unique visitors or when either pass/fail boundary is conclusive after 200."}, "version": 1},
    {"template_key": "fake_door_v1", "name": "Fake-door feature test", "category": "solution", "description": "Measure demand for a not-yet-built feature entry point.", "rules": {"target": {"metric": "feature-click rate", "unit": "eligible users"}, "sample": {"minimum": 200, "unit": "eligible users"}, "pass_rule": {"operator": ">=", "threshold": "8%"}, "partial_rule": {"range": "4%-7.99%"}, "fail_rule": {"range": "<4%"}, "stop_rule": "Stop at 300 eligible users or when either boundary is conclusive after 200."}, "version": 1},
    {"template_key": "concierge_v1", "name": "Concierge pilot", "category": "solution", "description": "Deliver the proposed outcome manually before automating it.", "rules": {"target": {"metric": "participants completing the workflow", "unit": "pilot customers"}, "sample": {"minimum": 10, "unit": "pilot customers"}, "pass_rule": {"operator": ">=", "threshold": "5 of 10"}, "partial_rule": {"range": "3-4 of 10"}, "fail_rule": {"range": "0-2 of 10"}, "stop_rule": "Stop after 10 pilots or after 3 consecutive failed completions."}, "version": 1},
    {"template_key": "preorder_v1", "name": "Pre-order test", "category": "willingness_to_pay", "description": "Validate payment intent with a refundable or real pre-order.", "rules": {"target": {"metric": "paid or refundable commitments", "unit": "qualified prospects"}, "sample": {"minimum": 100, "unit": "qualified prospects"}, "pass_rule": {"operator": ">=", "threshold": "10 commitments"}, "partial_rule": {"range": "5-9 commitments"}, "fail_rule": {"range": "0-4 commitments"}, "stop_rule": "Stop at 100 qualified prospects or after 10 commitments."}, "version": 1},
    {"template_key": "pricing_interviews_v1", "name": "Pricing interview", "category": "pricing", "description": "Test whether buyers accept a stated price and purchase process.", "rules": {"target": {"metric": "buyers accepting target price", "unit": "qualified buyer interviews"}, "sample": {"minimum": 20, "unit": "qualified buyer interviews"}, "pass_rule": {"operator": ">=", "threshold": "8 of 20"}, "partial_rule": {"range": "4-7 of 20"}, "fail_rule": {"range": "0-3 of 20"}, "stop_rule": "Stop after 20 interviews or after 5 explicit price rejections."}, "version": 1},
)

revision = "20250311_0005"
down_revision = "20250310_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("template_key"),
    )
    op.create_index("ix_experiment_templates_category", "experiment_templates", ["category"])
    op.bulk_insert(sa.table(
        "experiment_templates",
        sa.column("template_key", sa.String()), sa.column("name", sa.String()), sa.column("category", sa.String()),
        sa.column("description", sa.Text()), sa.column("rules", sa.JSON()), sa.column("version", sa.Integer()),
    ), list(_TEMPLATE_ROWS))
    op.create_table(
        "experiment_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hypothesis_id", sa.Integer(), sa.ForeignKey("hypotheses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("template_key", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="proposed", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('proposed', 'accepted', 'rejected', 'completed')", name="ck_experiment_proposals_status"),
    )
    op.create_index("ix_experiment_proposals_project_id", "experiment_proposals", ["project_id"])
    op.create_index("ix_experiment_proposals_hypothesis_id", "experiment_proposals", ["hypothesis_id"])
    op.create_index("ix_experiment_proposals_template_key", "experiment_proposals", ["template_key"])


def downgrade() -> None:
    op.drop_index("ix_experiment_proposals_template_key", table_name="experiment_proposals")
    op.drop_index("ix_experiment_proposals_hypothesis_id", table_name="experiment_proposals")
    op.drop_index("ix_experiment_proposals_project_id", table_name="experiment_proposals")
    op.drop_table("experiment_proposals")
    op.drop_index("ix_experiment_templates_category", table_name="experiment_templates")
    op.drop_table("experiment_templates")
