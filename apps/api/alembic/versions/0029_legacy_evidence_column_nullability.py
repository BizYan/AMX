"""relax legacy evidence columns after schema alignment

Revision ID: 0029_legacy_evidence_nullable
Revises: 0028_ops_metric_schema
"""

from alembic import op
import sqlalchemy as sa


revision = "0029_legacy_evidence_nullable"
down_revision = "0028_ops_metric_schema"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _relax_if_present(table_name: str, column_name: str, column_type) -> None:
    if _table_exists(table_name) and column_name in _columns(table_name):
        op.alter_column(table_name, column_name, existing_type=column_type, nullable=True)


def upgrade() -> None:
    _relax_if_present("metric_events", "metric_value", sa.Float())
    _relax_if_present("provider_runs", "provider", sa.String(length=50))


def downgrade() -> None:
    # Do not restore NOT NULL constraints on legacy columns. Current ORM writes
    # the aligned replacement columns, and re-tightening these legacy columns
    # would make forward-only production rollback unsafe.
    pass
