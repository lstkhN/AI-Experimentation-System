"""Regression coverage for the economics decision-contract migration."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _migration_module():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20250323_0018_economics_decision_contract.py"
    spec = spec_from_file_location("economics_decision_contract_migration", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_downgrade_normalizes_heuristic_rows_before_restoring_old_constraint():
    migration = _migration_module()
    events = []

    class Batch:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def drop_constraint(self, *args, **kwargs):
            events.append(("drop_constraint", args, kwargs))

        def create_check_constraint(self, *args, **kwargs):
            events.append(("create_check_constraint", args, kwargs))

    class Operations:
        def execute(self, statement):
            events.append(("execute", statement.text))

        def batch_alter_table(self, name):
            events.append(("batch_alter_table", name))
            return Batch()

        def drop_column(self, *args):
            events.append(("drop_column", args))

    migration.op = Operations()
    migration.downgrade()

    assert events[0] == (
        "execute",
        "UPDATE economics_models SET reliability = 'INSUFFICIENT_CRITICAL_INPUTS' WHERE reliability = 'HEURISTIC'",
    )
    assert events[1] == ("batch_alter_table", "economics_models")
