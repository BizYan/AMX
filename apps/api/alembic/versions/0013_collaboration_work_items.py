"""Add persistent collaboration work items.

Revision ID: 0013_collaboration_work_items
Revises: 0012_user_notifications
Create Date: 2026-06-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0013_collaboration_work_items"
down_revision = "0012_user_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collaboration_work_items",
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=True),
        sa.Column("comment_id", UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_to", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("work_type", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_key", sa.String(length=255), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["comment_id"], ["document_comments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "source_key", name="uq_collaboration_work_items_source"),
    )
    for column in [
        "tenant_id",
        "project_id",
        "document_id",
        "comment_id",
        "assigned_to",
        "created_by",
        "work_type",
        "status",
        "priority",
        "due_at",
    ]:
        op.create_index(f"ix_collaboration_work_items_{column}", "collaboration_work_items", [column], if_not_exists=True)
    op.create_index(
        "ix_collaboration_work_items_board",
        "collaboration_work_items",
        ["tenant_id", "status", "due_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_collaboration_work_items_assignee_status",
        "collaboration_work_items",
        ["tenant_id", "assigned_to", "status"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("collaboration_work_items")
