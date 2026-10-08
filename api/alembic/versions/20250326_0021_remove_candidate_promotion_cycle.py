"""Remove the redundant reverse candidate-promotion foreign key.

Evidence.candidate_id is the durable, unique promotion link.  Keeping a second
foreign key from evidence_candidates back to evidence made SQLAlchemy's schema
sort cyclic without adding integrity guarantees.
"""
from alembic import op
import sqlalchemy as sa

revision = "20250326_0021"
down_revision = "20250325_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("uq_evidence_candidates_promoted_evidence", table_name="evidence_candidates")
    # Batch mode recreates the table on SQLite and emits ALTER TABLE on PostgreSQL.
    with op.batch_alter_table("evidence_candidates") as batch_op:
        batch_op.drop_constraint("fk_evidence_candidates_promoted_evidence", type_="foreignkey")
        batch_op.drop_column("promoted_evidence_id")


def downgrade():
    with op.batch_alter_table("evidence_candidates") as batch_op:
        batch_op.add_column(sa.Column("promoted_evidence_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_evidence_candidates_promoted_evidence", "evidence",
            ["promoted_evidence_id"], ["id"], ondelete="SET NULL",
        )
    op.create_index(
        "uq_evidence_candidates_promoted_evidence",
        "evidence_candidates", ["promoted_evidence_id"], unique=True,
    )
    # Restore the legacy cache from the canonical unique evidence link.
    op.execute(
        "UPDATE evidence_candidates SET promoted_evidence_id = ("
        "SELECT evidence.id FROM evidence "
        "WHERE evidence.candidate_id = evidence_candidates.id)"
    )
