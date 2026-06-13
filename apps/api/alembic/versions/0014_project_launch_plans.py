"""Add persistent project launch plans.

Revision ID: 0014_project_launch_plans
Revises: 0013_collaboration_work_items
Create Date: 2026-06-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0014_project_launch_plans"
down_revision = "0013_collaboration_work_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_launch_plans",
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("blueprint_key", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("config_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("checks_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("results_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_project_launch_plans_project"),
    )
    for column in ["tenant_id", "project_id", "blueprint_key", "status", "created_by"]:
        op.create_index(
            f"ix_project_launch_plans_{column}",
            "project_launch_plans",
            [column],
            if_not_exists=True,
        )
    op.create_index(
        "ix_project_launch_plans_tenant_status",
        "project_launch_plans",
        ["tenant_id", "status"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("project_launch_plans")
