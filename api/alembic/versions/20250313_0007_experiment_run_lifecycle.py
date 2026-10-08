"""Add local experiment-run lifecycle records.

Revision ID: 20250313_0007
Revises: 20250312_0006
"""
from alembic import op
import sqlalchemy as sa

revision = "20250313_0007"
down_revision = "20250312_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("proposal_id", sa.Integer(), sa.ForeignKey("experiment_proposals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("forecast", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="proposed", nullable=False),
        sa.Column("evaluation", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('proposed', 'approved', 'running', 'completed', 'stopped')", name="ck_experiment_runs_status"),
    )
    op.create_index("ix_experiment_runs_project_id", "experiment_runs", ["project_id"])
    op.create_index("ix_experiment_runs_proposal_id", "experiment_runs", ["proposal_id"])
    op.create_table(
        "experiment_measurements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("experiment_run_id", sa.Integer(), sa.ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_experiment_measurements_experiment_run_id", "experiment_measurements", ["experiment_run_id"])
    op.create_index("ix_experiment_measurements_metric", "experiment_measurements", ["metric"])
    op.create_table(
        "experiment_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("experiment_run_id", sa.Integer(), sa.ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(length=20), server_default="approved", nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_experiment_approvals_experiment_run_id", "experiment_approvals", ["experiment_run_id"])
    op.create_table(
        "actual_vs_forecast",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("experiment_run_id", sa.Integer(), sa.ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("experiment_run_id", name="uq_actual_vs_forecast_run"),
    )


def downgrade() -> None:
    op.drop_table("actual_vs_forecast")
    op.drop_index("ix_experiment_approvals_experiment_run_id", table_name="experiment_approvals")
    op.drop_table("experiment_approvals")
    op.drop_index("ix_experiment_measurements_metric", table_name="experiment_measurements")
    op.drop_index("ix_experiment_measurements_experiment_run_id", table_name="experiment_measurements")
    op.drop_table("experiment_measurements")
    op.drop_index("ix_experiment_runs_proposal_id", table_name="experiment_runs")
    op.drop_index("ix_experiment_runs_project_id", table_name="experiment_runs")
    op.drop_table("experiment_runs")
