"""Add project delivery plans and milestones.

Revision ID: 0015_project_delivery_plans
Revises: 0014_project_launch_plans
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0015_project_delivery_plans"
down_revision = "0014_project_launch_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_delivery_plans",
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("blueprint_key", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("summary_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("settings_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_project_delivery_plans_project"),
    )
    op.create_table(
        "project_milestones",
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=True), nullable=True),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planned_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("required_document_types_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("required_workflow_template_ids_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("gate_results_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plan_id"], ["project_delivery_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "key", name="uq_project_milestones_plan_key"),
    )
    for table, columns in {
        "project_delivery_plans": ["tenant_id", "project_id", "blueprint_key", "status", "created_by"],
        "project_milestones": ["tenant_id", "project_id", "plan_id", "owner_id", "status", "priority", "due_at"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column], if_not_exists=True)
    op.create_index("ix_project_delivery_plans_tenant_status", "project_delivery_plans", ["tenant_id", "status"])
    op.create_index("ix_project_milestones_plan_order", "project_milestones", ["plan_id", "order_index"])
    op.create_index("ix_project_milestones_tenant_status", "project_milestones", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_table("project_milestones")
    op.drop_table("project_delivery_plans")
