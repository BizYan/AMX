"""complete project invitation lifecycle

Revision ID: 0018_project_invites
Revises: 0017_notification_alert_loop
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_project_invites"
down_revision = "0017_notification_alert_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_invitations", sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("project_invitations", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_project_invitations_accepted_at", "project_invitations", ["accepted_at"], if_not_exists=True)
    op.create_index("ix_project_invitations_revoked_at", "project_invitations", ["revoked_at"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_project_invitations_revoked_at", table_name="project_invitations")
    op.drop_index("ix_project_invitations_accepted_at", table_name="project_invitations")
    op.drop_column("project_invitations", "revoked_at")
    op.drop_column("project_invitations", "accepted_at")
