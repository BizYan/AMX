"""add conflict risk acceptance evidence

Revision ID: 0026_conflict_risk
Revises: 0025_conflict_closure
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0026_conflict_risk"
down_revision = "0025_conflict_closure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_conflicts",
        sa.Column("risk_accepted_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "document_conflicts",
        sa.Column("risk_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_conflicts",
        sa.Column("risk_acceptance_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_conflicts",
        sa.Column("risk_acceptance_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_document_conflicts_risk_accepted_by",
        "document_conflicts",
        ["risk_accepted_by"],
    )
    op.create_index(
        "ix_document_conflicts_risk_acceptance_expires_at",
        "document_conflicts",
        ["risk_acceptance_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_conflicts_risk_acceptance_expires_at",
        table_name="document_conflicts",
    )
    op.drop_index("ix_document_conflicts_risk_accepted_by", table_name="document_conflicts")
    op.drop_column("document_conflicts", "risk_acceptance_json")
    op.drop_column("document_conflicts", "risk_acceptance_expires_at")
    op.drop_column("document_conflicts", "risk_accepted_at")
    op.drop_column("document_conflicts", "risk_accepted_by")
