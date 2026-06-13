"""Add persisted document comment anchors.

Revision ID: 0011_document_comment_anchors
Revises: 0010_tenant_api_keys
Create Date: 2026-06-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_document_comment_anchors"
down_revision = "0010_tenant_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Persist human-readable document locations for review comments."""
    op.add_column("document_comments", sa.Column("anchor", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove persisted document comment locations."""
    op.drop_column("document_comments", "anchor")
