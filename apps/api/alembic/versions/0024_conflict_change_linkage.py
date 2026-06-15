"""add conflict change request linkage

Revision ID: 0024_conflict_change_linkage
Revises: 0023_conflict_assignment
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0024_conflict_change_linkage"
down_revision = "0023_conflict_assignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_conflicts",
        sa.Column("linked_change_request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "document_conflicts",
        sa.Column("accepted_revision_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "document_conflicts",
        sa.Column("revision_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_document_conflicts_linked_change_request_id",
        "document_conflicts",
        ["linked_change_request_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_conflicts_linked_change_request_id",
        table_name="document_conflicts",
    )
    op.drop_column("document_conflicts", "revision_accepted_at")
    op.drop_column("document_conflicts", "accepted_revision_json")
    op.drop_column("document_conflicts", "linked_change_request_id")
