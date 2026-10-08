"""Persist immutable decision provenance."""
from alembic import op
import sqlalchemy as sa
revision="20250320_0014"; down_revision="20250319_0013"; branch_labels=None; depends_on=None
def upgrade(): op.add_column("project_verdicts", sa.Column("provenance_snapshot", sa.JSON(), nullable=True))
def downgrade(): op.drop_column("project_verdicts", "provenance_snapshot")
