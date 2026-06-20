"""align ops observability metric schema with current model

Revision ID: 0028_ops_metric_schema
Revises: 0027_provider_runs_schema
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0028_ops_metric_schema"
down_revision = "0027_provider_runs_schema"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _columns(table_name):
        op.add_column(table_name, column)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if index_name not in _indexes(table_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if not _table_exists("metric_events"):
        return

    existing_columns = _columns("metric_events")
    _add_column_if_missing("metric_events", sa.Column("metric_type", sa.String(length=50), nullable=True))
    _add_column_if_missing("metric_events", sa.Column("value", sa.Float(), nullable=True))
    _add_column_if_missing("metric_events", sa.Column("unit", sa.String(length=20), nullable=True))
    _add_column_if_missing(
        "metric_events",
        sa.Column("dimensions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    _add_column_if_missing("metric_events", sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing("metric_events", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    metric_value = "metric_value" if "metric_value" in existing_columns else "value"
    metric_labels = "metric_labels" if "metric_labels" in existing_columns else "dimensions"
    op.execute(
        f"""
        UPDATE metric_events
        SET
            metric_type = COALESCE(metric_type, 'system'),
            value = COALESCE(value, {metric_value}, 0),
            unit = COALESCE(unit, 'count'),
            dimensions = COALESCE(dimensions, {metric_labels}, '{{}}'::jsonb),
            recorded_at = COALESCE(recorded_at, created_at, now()),
            updated_at = COALESCE(updated_at, created_at, now())
        """
    )

    op.alter_column("metric_events", "metric_type", nullable=False)
    op.alter_column("metric_events", "value", nullable=False)
    op.alter_column("metric_events", "unit", nullable=False)
    op.alter_column("metric_events", "recorded_at", nullable=False)
    op.alter_column("metric_events", "updated_at", nullable=False)

    _create_index_if_missing("ix_metric_events_metric_type", "metric_events", ["metric_type"])
    _create_index_if_missing("ix_metric_events_recorded_at", "metric_events", ["recorded_at"])
    _create_index_if_missing(
        "ix_metric_events_tenant_type_name_recorded",
        "metric_events",
        ["tenant_id", "metric_type", "metric_name", "recorded_at"],
    )


def downgrade() -> None:
    if not _table_exists("metric_events"):
        return

    for index_name in (
        "ix_metric_events_tenant_type_name_recorded",
        "ix_metric_events_recorded_at",
        "ix_metric_events_metric_type",
    ):
        if index_name in _indexes("metric_events"):
            op.drop_index(index_name, table_name="metric_events")

    for column_name in (
        "updated_at",
        "recorded_at",
        "dimensions",
        "unit",
        "value",
        "metric_type",
    ):
        if column_name in _columns("metric_events"):
            op.drop_column("metric_events", column_name)
