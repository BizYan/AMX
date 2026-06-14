"""add project invitation delivery governance

Revision ID: 0021_invitation_delivery
Revises: 0020_account_security
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_invitation_delivery"
down_revision = "0020_account_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_invitations", sa.Column("delivery_status", sa.String(length=20), nullable=False, server_default="pending"))
    op.add_column("project_invitations", sa.Column("delivery_channel", sa.String(length=30), nullable=True))
    op.add_column("project_invitations", sa.Column("delivery_attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("project_invitations", sa.Column("delivery_error", sa.Text(), nullable=True))
    op.add_column("project_invitations", sa.Column("last_delivery_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("project_invitations", sa.Column("last_delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_project_invitations_delivery_status", "project_invitations", ["delivery_status"], if_not_exists=True)
    op.alter_column("project_invitations", "delivery_status", server_default=None)
    op.alter_column("project_invitations", "delivery_attempt_count", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_project_invitations_delivery_status", table_name="project_invitations")
    op.drop_column("project_invitations", "last_delivered_at")
    op.drop_column("project_invitations", "last_delivery_attempt_at")
    op.drop_column("project_invitations", "delivery_error")
    op.drop_column("project_invitations", "delivery_attempt_count")
    op.drop_column("project_invitations", "delivery_channel")
    op.drop_column("project_invitations", "delivery_status")
