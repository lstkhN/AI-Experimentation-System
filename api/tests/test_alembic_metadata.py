"""Integration check that Alembic imports the API ORM metadata."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migration_revision_ids_match_unique_file_prefixes():
    """Keep revision lookup unambiguous in source and packaged images."""
    repository_root = Path(__file__).resolve().parents[2]
    config = Config(str(repository_root / "alembic.ini"))
    revisions = list(ScriptDirectory.from_config(config).walk_revisions())

    assert len({revision.revision for revision in revisions}) == len(revisions)
    assert all(Path(revision.path).name.startswith(f"{revision.revision}_") for revision in revisions)


def test_alembic_metadata_matches_initial_schema(tmp_path, monkeypatch):
    """A migrated empty database must have no ORM metadata changes pending."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    repository_root = Path(__file__).resolve().parents[2]
    config = Config(str(repository_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'alembic.db'}")

    command.upgrade(config, "head")
    command.check(config)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.check(config)
