"""Add decision-critical hypothesis and economics fields.

Revision ID: 20250315_0009
Revises: 20250314_0008
"""
from alembic import op
import sqlalchemy as sa

revision = "20250315_0009"
down_revision = "20250314_0008"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("hypotheses") as batch:
        batch.add_column(sa.Column("criticality", sa.String(length=10), nullable=False, server_default="NORMAL"))
        batch.add_column(sa.Column("is_blocking", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_check_constraint("ck_hypotheses_criticality", "criticality IN ('LOW', 'NORMAL', 'HIGH', 'FATAL')")
    with op.batch_alter_table("economics_models") as batch:
        batch.add_column(sa.Column("reliability", sa.String(length=40), nullable=False, server_default="INSUFFICIENT_CRITICAL_INPUTS"))
        batch.create_check_constraint("ck_economics_models_reliability", "reliability IN ('RELIABLE', 'INSUFFICIENT_CRITICAL_INPUTS')")
    with op.batch_alter_table("project_verdicts") as batch:
        batch.add_column(sa.Column("decision", sa.String(length=20), nullable=False, server_default="VALIDATE"))
        batch.create_check_constraint("ck_project_verdicts_decision", "decision IN ('GO', 'VALIDATE', 'NO_GO')")


def downgrade():
    with op.batch_alter_table("project_verdicts") as batch:
        batch.drop_constraint("ck_project_verdicts_decision", type_="check")
        batch.drop_column("decision")
    with op.batch_alter_table("economics_models") as batch:
        batch.drop_constraint("ck_economics_models_reliability", type_="check")
        batch.drop_column("reliability")
    with op.batch_alter_table("hypotheses") as batch:
        batch.drop_constraint("ck_hypotheses_criticality", type_="check")
        batch.drop_column("is_blocking")
        batch.drop_column("criticality")
