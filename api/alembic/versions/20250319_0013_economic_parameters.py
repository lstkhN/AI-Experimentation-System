"""Persist economics parameter provenance."""
from alembic import op
import sqlalchemy as sa
revision="20250319_0013"; down_revision="20250318_0012"; branch_labels=None; depends_on=None
def upgrade():
    op.create_table("economic_parameters",
      sa.Column("id",sa.Integer(),primary_key=True), sa.Column("economics_model_id",sa.Integer(),sa.ForeignKey("economics_models.id",ondelete="CASCADE"),nullable=False),
      sa.Column("name",sa.String(100),nullable=False), sa.Column("low",sa.Float()),sa.Column("base",sa.Float()),sa.Column("high",sa.Float()),
      sa.Column("source_type",sa.String(30),nullable=False,server_default="unknown"),sa.Column("source_id",sa.String(255)),sa.Column("confidence",sa.String(20),nullable=False,server_default="LOW"),
      sa.Column("user_supplied",sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column("observed",sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column("benchmark",sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column("inferred",sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_index("ix_economic_parameters_economics_model_id","economic_parameters",["economics_model_id"])
def downgrade():
    op.drop_index("ix_economic_parameters_economics_model_id",table_name="economic_parameters"); op.drop_table("economic_parameters")
