"""add persisted document conflicts

Revision ID: 0022_document_conflicts
Revises: 0021_invitation_delivery
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0022_document_conflicts"
down_revision = "0021_invitation_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_conflicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_key", sa.String(length=80), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("primary_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("primary_document_version", sa.Integer(), nullable=False),
        sa.Column("related_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("related_document_version", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("absent_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["primary_document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["related_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "fingerprint",
            name="uq_document_conflicts_tenant_project_fingerprint",
        ),
    )
    op.create_index("ix_document_conflicts_project_id", "document_conflicts", ["project_id"])
    op.create_index("ix_document_conflicts_status", "document_conflicts", ["status"])
    op.create_index("ix_document_conflicts_severity", "document_conflicts", ["severity"])
    op.create_index("ix_document_conflicts_last_scan_id", "document_conflicts", ["last_scan_id"])


def downgrade() -> None:
    op.drop_index("ix_document_conflicts_last_scan_id", table_name="document_conflicts")
    op.drop_index("ix_document_conflicts_severity", table_name="document_conflicts")
    op.drop_index("ix_document_conflicts_status", table_name="document_conflicts")
    op.drop_index("ix_document_conflicts_project_id", table_name="document_conflicts")
    op.drop_table("document_conflicts")
