"""Add user-facing in-app notifications.

Revision ID: 0012_user_notifications
Revises: 0011_document_comment_anchors
Create Date: 2026-06-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0012_user_notifications"
down_revision = "0011_document_comment_anchors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_notifications",
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=False, server_default="system"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("action_url", sa.String(length=1000), nullable=True),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", "dedupe_key", name="uq_user_notifications_dedupe"),
    )
    op.create_index("ix_user_notifications_user_id", "user_notifications", ["user_id"], if_not_exists=True)
    op.create_index("ix_user_notifications_tenant_id", "user_notifications", ["tenant_id"], if_not_exists=True)
    op.create_index("ix_user_notifications_category", "user_notifications", ["category"], if_not_exists=True)
    op.create_index("ix_user_notifications_priority", "user_notifications", ["priority"], if_not_exists=True)
    op.create_index("ix_user_notifications_read_at", "user_notifications", ["read_at"], if_not_exists=True)
    op.create_index("ix_user_notifications_archived_at", "user_notifications", ["archived_at"], if_not_exists=True)
    op.create_index("ix_user_notifications_expires_at", "user_notifications", ["expires_at"], if_not_exists=True)
    op.create_index(
        "ix_user_notifications_inbox",
        "user_notifications",
        ["tenant_id", "user_id", "archived_at", "created_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_user_notifications_unread",
        "user_notifications",
        ["tenant_id", "user_id", "read_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_user_notifications_entity",
        "user_notifications",
        ["entity_type", "entity_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("user_notifications")
