"""Add tenant API keys.

Revision ID: 0010_tenant_api_keys
Revises: 0009_agent_runtime_meta
Create Date: 2026-06-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0010_tenant_api_keys"
down_revision = "0009_agent_runtime_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create tenant-scoped API key metadata table."""
    op.create_table(
        "tenant_api_keys",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("permissions", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenant_api_keys_key_prefix", "tenant_api_keys", ["key_prefix"], if_not_exists=True)
    op.create_index("ix_tenant_api_keys_key_hash", "tenant_api_keys", ["key_hash"], unique=True, if_not_exists=True)
    op.create_index("ix_tenant_api_keys_deleted_at", "tenant_api_keys", ["deleted_at"], if_not_exists=True)
    op.create_index("ix_tenant_api_keys_tenant_id", "tenant_api_keys", ["tenant_id"], if_not_exists=True)
    op.create_index(
        "ix_tenant_api_keys_tenant_status",
        "tenant_api_keys",
        ["tenant_id", "status"],
        if_not_exists=True,
    )
    op.create_index("ix_tenant_api_keys_created_by", "tenant_api_keys", ["created_by_id"], if_not_exists=True)


def downgrade() -> None:
    """Drop tenant-scoped API key metadata table."""
    op.drop_index("ix_tenant_api_keys_created_by", table_name="tenant_api_keys", if_exists=True)
    op.drop_index("ix_tenant_api_keys_tenant_status", table_name="tenant_api_keys", if_exists=True)
    op.drop_index("ix_tenant_api_keys_tenant_id", table_name="tenant_api_keys", if_exists=True)
    op.drop_index("ix_tenant_api_keys_deleted_at", table_name="tenant_api_keys", if_exists=True)
    op.drop_index("ix_tenant_api_keys_key_hash", table_name="tenant_api_keys", if_exists=True)
    op.drop_index("ix_tenant_api_keys_key_prefix", table_name="tenant_api_keys", if_exists=True)
    op.drop_table("tenant_api_keys")
