"""add conflict assignment governance

Revision ID: 0023_conflict_assignment_governance
Revises: 0022_document_conflicts
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0023_conflict_assignment_governance"
down_revision = "0022_document_conflicts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_conflicts",
        sa.Column("assignee_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "document_conflicts",
        sa.Column("assignment_source", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "document_conflicts",
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_conflicts",
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_document_conflicts_assignee_user_id_users",
        "document_conflicts",
        "users",
        ["assignee_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_document_conflicts_assignee_user_id",
        "document_conflicts",
        ["assignee_user_id"],
    )

    op.create_table(
        "document_conflict_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conflict_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("previous_status", sa.String(length=20), nullable=True),
        sa.Column("resulting_status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conflict_id"], ["document_conflicts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_conflict_decisions_tenant_id",
        "document_conflict_decisions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_document_conflict_decisions_project_id",
        "document_conflict_decisions",
        ["project_id"],
    )
    op.create_index(
        "ix_document_conflict_decisions_conflict_id",
        "document_conflict_decisions",
        ["conflict_id"],
    )
    op.create_index(
        "ix_document_conflict_decisions_actor_id",
        "document_conflict_decisions",
        ["actor_id"],
    )
    op.create_index(
        "ix_document_conflict_decisions_action",
        "document_conflict_decisions",
        ["action"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_conflict_decisions_action", table_name="document_conflict_decisions")
    op.drop_index("ix_document_conflict_decisions_actor_id", table_name="document_conflict_decisions")
    op.drop_index("ix_document_conflict_decisions_conflict_id", table_name="document_conflict_decisions")
    op.drop_index("ix_document_conflict_decisions_project_id", table_name="document_conflict_decisions")
    op.drop_index("ix_document_conflict_decisions_tenant_id", table_name="document_conflict_decisions")
    op.drop_table("document_conflict_decisions")
    op.drop_index("ix_document_conflicts_assignee_user_id", table_name="document_conflicts")
    op.drop_constraint(
        "fk_document_conflicts_assignee_user_id_users",
        "document_conflicts",
        type_="foreignkey",
    )
    op.drop_column("document_conflicts", "due_at")
    op.drop_column("document_conflicts", "assigned_at")
    op.drop_column("document_conflicts", "assignment_source")
    op.drop_column("document_conflicts", "assignee_user_id")
