"""Persist typed economic distributions and heuristic reliability."""
from alembic import op
import sqlalchemy as sa

revision = "20250323_0018"
down_revision = "20250322_0017"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("economic_parameters", sa.Column("scenario_name", sa.String(100), nullable=False, server_default="base"))
    op.add_column("economic_parameters", sa.Column("distribution", sa.JSON(), nullable=True))
    # SQLite cannot alter CHECK constraints; batch mode makes this portable.
    with op.batch_alter_table("economics_models") as batch:
        batch.drop_constraint("ck_economics_models_reliability", type_="check")
        batch.create_check_constraint(
            "ck_economics_models_reliability",
            "reliability IN ('RELIABLE', 'HEURISTIC', 'INSUFFICIENT_CRITICAL_INPUTS')",
        )


def downgrade():
    # The prior constraint has no HEURISTIC state. Normalize rows before the
    # constraint is recreated so downgrade succeeds on populated databases.
    op.execute(
        sa.text(
            "UPDATE economics_models "
            "SET reliability = 'INSUFFICIENT_CRITICAL_INPUTS' "
            "WHERE reliability = 'HEURISTIC'"
        )
    )
    with op.batch_alter_table("economics_models") as batch:
        batch.drop_constraint("ck_economics_models_reliability", type_="check")
        batch.create_check_constraint(
            "ck_economics_models_reliability",
            "reliability IN ('RELIABLE', 'INSUFFICIENT_CRITICAL_INPUTS')",
        )
    op.drop_column("economic_parameters", "distribution")
    op.drop_column("economic_parameters", "scenario_name")
