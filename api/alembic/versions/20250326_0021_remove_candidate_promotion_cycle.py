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


def _defer_sqlite_foreign_keys() -> None:
    """Defer enforcement while SQLite batch-recreates the populated FK cycle."""
    if op.get_bind().dialect.name == "sqlite":
        # Unlike foreign_keys=OFF, this retains enforcement and works inside
        # Alembic's transaction. SQLite validates the final schema at commit.
        op.execute("PRAGMA defer_foreign_keys=ON")


def _drop_evidence_candidate_fk() -> None:
    # evidence is dependent on evidence_candidates.  Rebuild/drop this FK before
    # replacing evidence_candidates, then restore it after the replacement.
    op.drop_index("uq_evidence_candidate_id", table_name="evidence")
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.drop_constraint("fk_evidence_candidate", type_="foreignkey")


def _restore_evidence_candidate_fk() -> None:
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.create_foreign_key(
            "fk_evidence_candidate", "evidence_candidates", ["candidate_id"], ["id"], ondelete="SET NULL"
        )
    op.create_index("uq_evidence_candidate_id", "evidence", ["candidate_id"], unique=True)


def _reconcile_promoted_evidence_links() -> None:
    """Make the legacy reverse link canonical before removing it.

    A populated pre-0021 database can contain a valid link only in
    ``promoted_evidence_id``.  Copy that link to ``evidence.candidate_id``.
    A different existing candidate on that evidence is irreconcilable: choosing
    either side would silently discard a promotion, so fail before DDL runs.
    """
    bind = op.get_bind()
    conflicts = bind.execute(sa.text("""
        SELECT candidates.id AS candidate_id, candidates.promoted_evidence_id AS evidence_id,
               evidence.candidate_id AS canonical_candidate_id
        FROM evidence_candidates AS candidates
        JOIN evidence ON evidence.id = candidates.promoted_evidence_id
        WHERE candidates.promoted_evidence_id IS NOT NULL
          AND evidence.candidate_id IS NOT NULL
          AND evidence.candidate_id <> candidates.id
    """)).mappings().all()
    if conflicts:
        conflict = conflicts[0]
        raise RuntimeError(
            "Cannot remove promoted_evidence_id: contradictory promotion mapping "
            f"for evidence {conflict['evidence_id']}; legacy candidate "
            f"{conflict['candidate_id']} conflicts with canonical candidate "
            f"{conflict['canonical_candidate_id']}."
        )

    bind.execute(sa.text("""
        UPDATE evidence
        SET candidate_id = (
            SELECT candidates.id
            FROM evidence_candidates AS candidates
            WHERE candidates.promoted_evidence_id = evidence.id
        )
        WHERE candidate_id IS NULL
          AND EXISTS (
            SELECT 1
            FROM evidence_candidates AS candidates
            WHERE candidates.promoted_evidence_id = evidence.id
        )
    """))


def upgrade():
    _reconcile_promoted_evidence_links()
    # Defer validation while replacing the populated cycle, retaining
    # foreign_keys=ON for the migration connection.
    _defer_sqlite_foreign_keys()
    _drop_evidence_candidate_fk()
    op.drop_index("uq_evidence_candidates_promoted_evidence", table_name="evidence_candidates")
    with op.batch_alter_table("evidence_candidates") as batch_op:
        batch_op.drop_constraint("fk_evidence_candidates_promoted_evidence", type_="foreignkey")
        batch_op.drop_column("promoted_evidence_id")
    _restore_evidence_candidate_fk()


def downgrade():
    _defer_sqlite_foreign_keys()
    _drop_evidence_candidate_fk()
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
    _restore_evidence_candidate_fk()
    # Restore the legacy cache only after both SQLite table replacements: a
    # temporary drop of evidence would otherwise apply SET NULL immediately.
    op.execute(
        "UPDATE evidence_candidates SET promoted_evidence_id = ("
        "SELECT evidence.id FROM evidence "
        "WHERE evidence.candidate_id = evidence_candidates.id)"
    )
