"""Add immutable project verdict snapshots.

Revision ID: 20250310_0004
Revises: 20250309_0003
"""
from alembic import op
import sqlalchemy as sa

revision = "20250310_0004"
down_revision = "20250309_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_verdicts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("economics_model_id", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.String(length=50), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["economics_model_id"], ["economics_models.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_verdicts_project_id", "project_verdicts", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_project_verdicts_project_id", table_name="project_verdicts")
    op.drop_table("project_verdicts")
