"""add conflict closure rescan evidence

Revision ID: 0025_conflict_closure
Revises: 0024_conflict_change_linkage
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0025_conflict_closure"
down_revision = "0024_conflict_change_linkage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_conflicts",
        sa.Column("closure_scan_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "document_conflicts",
        sa.Column("closure_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_conflicts",
        sa.Column("closure_evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_document_conflicts_closure_scan_id",
        "document_conflicts",
        ["closure_scan_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_conflicts_closure_scan_id", table_name="document_conflicts")
    op.drop_column("document_conflicts", "closure_evidence_json")
    op.drop_column("document_conflicts", "closure_verified_at")
    op.drop_column("document_conflicts", "closure_scan_id")
