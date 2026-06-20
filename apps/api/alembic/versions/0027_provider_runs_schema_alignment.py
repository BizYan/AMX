"""align provider runs schema with provider domain model

Revision ID: 0027_provider_runs_schema
Revises: 0026_conflict_risk
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0027_provider_runs_schema"
down_revision = "0026_conflict_risk"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


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
    if not _table_exists("provider_runs"):
        return

    existing_columns = _columns("provider_runs")
    _add_column_if_missing(
        "provider_runs",
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    _add_column_if_missing(
        "provider_runs",
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    _add_column_if_missing(
        "provider_runs",
        sa.Column("capability_type", sa.String(length=50), nullable=True),
    )
    _add_column_if_missing(
        "provider_runs",
        sa.Column("status", sa.String(length=20), nullable=True),
    )
    _add_column_if_missing(
        "provider_runs",
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "provider_runs",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    provider_value = "provider" if "provider" in existing_columns else "'unknown'"
    error_value = "error" if "error" in existing_columns else "NULL"
    op.execute(
        f"""
        UPDATE provider_runs
        SET
            capability_type = COALESCE(capability_type, {provider_value}, 'unknown'),
            status = COALESCE(status, CASE WHEN {error_value} IS NULL THEN 'success' ELSE 'failure' END),
            error_message = COALESCE(error_message, {error_value}),
            updated_at = COALESCE(updated_at, created_at, now())
        """
    )

    op.alter_column("provider_runs", "capability_type", nullable=False)
    op.alter_column("provider_runs", "status", nullable=False)
    op.alter_column("provider_runs", "updated_at", nullable=False)

    _create_index_if_missing("ix_provider_runs_provider_id", "provider_runs", ["provider_id"])
    _create_index_if_missing("ix_provider_runs_provider_status", "provider_runs", ["provider_id", "status"])
    _create_index_if_missing("ix_provider_runs_tenant_created", "provider_runs", ["tenant_id", "created_at"])


def downgrade() -> None:
    if not _table_exists("provider_runs"):
        return

    for index_name in (
        "ix_provider_runs_tenant_created",
        "ix_provider_runs_provider_status",
        "ix_provider_runs_provider_id",
    ):
        if index_name in _indexes("provider_runs"):
            op.drop_index(index_name, table_name="provider_runs")

    for column_name in (
        "updated_at",
        "error_message",
        "status",
        "capability_type",
        "version_id",
        "provider_id",
    ):
        if column_name in _columns("provider_runs"):
            op.drop_column("provider_runs", column_name)
