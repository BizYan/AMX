"""add integration project sync

Revision ID: 0016_integration_project_sync
Revises: 0015_project_delivery_plans
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016_integration_project_sync"
down_revision = "0015_project_delivery_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_project_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("integration_provider_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("scope_json", postgresql.JSONB(), nullable=False),
        sa.Column("field_mapping_json", postgresql.JSONB(), nullable=False),
        sa.Column("cursor_json", postgresql.JSONB(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("last_sync_status", sa.String(length=20), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["integration_provider_id"], ["integration_providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("integration_provider_id", "project_id", "name", name="uq_integration_project_bindings_scope"),
    )
    op.create_index("ix_integration_project_bindings_tenant_project", "integration_project_bindings", ["tenant_id", "project_id"])
    op.create_index("ix_integration_project_bindings_integration_provider_id", "integration_project_bindings", ["integration_provider_id"])
    op.create_index("ix_integration_project_bindings_project_id", "integration_project_bindings", ["project_id"])
    op.create_index("ix_integration_project_bindings_is_enabled", "integration_project_bindings", ["is_enabled"])

    op.create_table(
        "integration_sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("binding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("cursor_before_json", postgresql.JSONB(), nullable=False),
        sa.Column("cursor_after_json", postgresql.JSONB(), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("details_json", postgresql.JSONB(), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["binding_id"], ["integration_project_bindings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_integration_sync_runs_tenant_status", "integration_sync_runs", ["tenant_id", "status"])
    op.create_index("ix_integration_sync_runs_binding_created", "integration_sync_runs", ["binding_id", "created_at"])
    op.create_index("ix_integration_sync_runs_binding_id", "integration_sync_runs", ["binding_id"])
    op.create_index("ix_integration_sync_runs_status", "integration_sync_runs", ["status"])

    op.create_table(
        "integration_synced_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("binding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("external_updated_at", sa.String(length=100), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["binding_id"], ["integration_project_bindings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["knowledge_entry_id"], ["knowledge_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("binding_id", "external_id", name="uq_integration_synced_assets_external"),
    )
    op.create_index("ix_integration_synced_assets_tenant_binding", "integration_synced_assets", ["tenant_id", "binding_id"])
    op.create_index("ix_integration_synced_assets_binding_id", "integration_synced_assets", ["binding_id"])
    op.create_index("ix_integration_synced_assets_content_hash", "integration_synced_assets", ["content_hash"])


def downgrade() -> None:
    op.drop_table("integration_synced_assets")
    op.drop_table("integration_sync_runs")
    op.drop_table("integration_project_bindings")
