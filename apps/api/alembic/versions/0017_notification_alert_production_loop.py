"""Complete notification preferences, acknowledgement, and escalation.

Revision ID: 0017_notification_alert_loop
Revises: 0016_integration_project_sync
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0017_notification_alert_loop"
down_revision = "0016_integration_project_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_notifications", sa.Column("ack_required", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("user_notifications", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_notifications", sa.Column("ack_deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_notifications", sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("user_notifications", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_user_notifications_ack_queue",
        "user_notifications",
        ["ack_required", "acknowledged_at", "ack_deadline_at"],
        if_not_exists=True,
    )
    op.create_index("ix_user_notifications_ack_required", "user_notifications", ["ack_required"], if_not_exists=True)
    op.create_index("ix_user_notifications_acknowledged_at", "user_notifications", ["acknowledged_at"], if_not_exists=True)
    op.create_index("ix_user_notifications_ack_deadline_at", "user_notifications", ["ack_deadline_at"], if_not_exists=True)
    op.create_index("ix_user_notifications_escalated_at", "user_notifications", ["escalated_at"], if_not_exists=True)

    op.create_table(
        "notification_preferences",
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled_categories", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("min_priority", sa.String(length=20), nullable=False, server_default="low"),
        sa.Column("daily_digest", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ack_timeout_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_notification_preferences_user"),
    )
    op.create_index("ix_notification_preferences_user_id", "notification_preferences", ["user_id"], if_not_exists=True)
    op.create_index("ix_notification_preferences_tenant_id", "notification_preferences", ["tenant_id"], if_not_exists=True)
    op.create_index(
        "ix_notification_preferences_tenant_user",
        "notification_preferences",
        ["tenant_id", "user_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.drop_index("ix_user_notifications_ack_queue", table_name="user_notifications")
    op.drop_column("user_notifications", "escalated_at")
    op.drop_column("user_notifications", "escalation_level")
    op.drop_column("user_notifications", "ack_deadline_at")
    op.drop_column("user_notifications", "acknowledged_at")
    op.drop_column("user_notifications", "ack_required")
