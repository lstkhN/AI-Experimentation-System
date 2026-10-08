"""Add manual, attributable market and strategy context.

Revision ID: 20250314_0008
Revises: 20250313_0007
"""
from alembic import op
import sqlalchemy as sa
revision = "20250314_0008"
down_revision = "20250313_0007"
branch_labels = None
depends_on = None


def _table(name, columns):
    op.create_table(name, sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        *columns, sa.Column("provenance", sa.String(length=20), server_default="manual", nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("provenance = 'manual'", name=f"ck_{name}_manual_provenance"))
    op.create_index(f"ix_{name}_project_id", name, ["project_id"])


def upgrade():
    _table("market_entities", [sa.Column("name", sa.String(255), nullable=False), sa.Column("entity_type", sa.String(100), nullable=False), sa.Column("claim", sa.Text(), nullable=False), sa.Column("verification_status", sa.String(20), server_default="verified", nullable=False)])
    _table("competitors", [sa.Column("name", sa.String(255), nullable=False), sa.Column("competitor_type", sa.String(100), nullable=False), sa.Column("positioning", sa.Text(), nullable=True)])
    _table("icp_segments", [sa.Column("name", sa.String(255), nullable=False), sa.Column("profile", sa.Text(), nullable=False), sa.Column("job_to_be_done", sa.Text(), nullable=True), sa.Column("priority", sa.Integer(), server_default="3", nullable=False)])
    _table("monetization_assumptions", [sa.Column("name", sa.String(255), nullable=False), sa.Column("assumption", sa.Text(), nullable=False), sa.Column("value", sa.String(255), nullable=True), sa.Column("currency", sa.String(3), nullable=True)])
    _table("risk_map_entries", [sa.Column("title", sa.String(255), nullable=False), sa.Column("description", sa.Text(), nullable=False), sa.Column("probability", sa.Integer(), nullable=False), sa.Column("impact", sa.Integer(), nullable=False), sa.Column("mitigation", sa.Text(), nullable=True), sa.Column("owner", sa.String(255), nullable=True)])


def downgrade():
    for name in ("risk_map_entries", "monetization_assumptions", "icp_segments", "competitors", "market_entities"):
        op.drop_index(f"ix_{name}_project_id", table_name=name)
        op.drop_table(name)
