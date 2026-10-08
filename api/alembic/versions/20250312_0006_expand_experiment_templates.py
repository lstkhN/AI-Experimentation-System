"""Expand the immutable experiment-template seed catalog to twelve.

Revision ID: 20250312_0006
Revises: 20250311_0005
"""
from alembic import op
import sqlalchemy as sa

revision = "20250312_0006"
down_revision = "20250311_0005"
branch_labels = None
depends_on = None


def _rules(metric, unit, minimum, passed, partial, failed, stop):
    return {"target": {"metric": metric, "unit": unit}, "sample": {"minimum": minimum, "unit": unit}, "pass_rule": {"operator": ">=", "threshold": passed}, "partial_rule": {"range": partial}, "fail_rule": {"range": failed}, "stop_rule": stop}


_ROWS = (
    ("problem_survey_v1", "Problem survey", "problem", "Quantify problem prevalence in a defined segment.", _rules("respondents reporting the problem", "qualified responses", 100, "60%", "30%-59.99%", "<30%", "Stop at 100 qualified responses or when 95% confidence excludes the partial band.")),
    ("smoke_test_v1", "Smoke test", "demand", "Test acquisition-channel demand before building the product.", _rules("qualified lead rate", "ad clicks", 150, "12%", "6%-11.99%", "<6%", "Stop at 250 clicks or when 20 qualified leads are collected.")),
    ("prototype_usability_v1", "Prototype usability test", "solution", "Check whether target users can complete the core workflow.", _rules("participants completing the core task", "usability sessions", 8, "6 of 8", "4-5 of 8", "0-3 of 8", "Stop after 8 sessions or 3 consecutive task failures.")),
    ("wizard_of_oz_v1", "Wizard-of-Oz test", "solution", "Simulate the product behind the scenes to validate the promised outcome.", _rules("customers receiving the promised outcome", "pilot customers", 10, "6 of 10", "3-5 of 10", "0-2 of 10", "Stop after 10 pilots or when delivery cannot meet the promise 3 times.")),
    ("mvp_pilot_v1", "MVP pilot", "retention", "Validate repeated use of a minimum viable product.", _rules("customers active in week four", "activated pilot customers", 20, "50%", "25%-49.99%", "<25%", "Stop after 20 activations or when 10 customers churn before week four.")),
    ("paid_pilot_v1", "Paid pilot", "willingness_to_pay", "Validate a paid delivery and renewal path with real buyers.", _rules("customers paying for a pilot", "qualified opportunities", 20, "4 of 20", "2-3 of 20", "0-1 of 20", "Stop after 20 opportunities or 4 paid pilots.")),
)


def upgrade():
    table = sa.table("experiment_templates", sa.column("template_key", sa.String()), sa.column("name", sa.String()), sa.column("category", sa.String()), sa.column("description", sa.Text()), sa.column("rules", sa.JSON()), sa.column("version", sa.Integer()))
    op.bulk_insert(table, [{"template_key": key, "name": name, "category": category, "description": description, "rules": rules, "version": 1} for key, name, category, description, rules in _ROWS])


def downgrade():
    table = sa.table("experiment_templates", sa.column("template_key", sa.String()))
    op.execute(sa.delete(table).where(table.c.template_key.in_([row[0] for row in _ROWS])))
