"""Database models for user-facing in-app notifications."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base, TenantMixin, TimestampMixin, UuidMixin


class UserNotification(Base, UuidMixin, TimestampMixin, TenantMixin):
    """One actionable notification in a user's inbox."""

    __tablename__ = "user_notifications"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    category = Column(String(50), nullable=False, default="system", index=True)
    priority = Column(String(20), nullable=False, default="normal", index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    action_url = Column(String(1000), nullable=True)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    dedupe_key = Column(String(255), nullable=True)
    metadata_json = Column(JSONB, nullable=False, default=dict)
    read_at = Column(DateTime(timezone=True), nullable=True, index=True)
    archived_at = Column(DateTime(timezone=True), nullable=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    ack_required = Column(Boolean, nullable=False, default=False, index=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True, index=True)
    ack_deadline_at = Column(DateTime(timezone=True), nullable=True, index=True)
    escalation_level = Column(Integer, nullable=False, default=0)
    escalated_at = Column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "dedupe_key", name="uq_user_notifications_dedupe"),
        Index("ix_user_notifications_inbox", "tenant_id", "user_id", "archived_at", "created_at"),
        Index("ix_user_notifications_unread", "tenant_id", "user_id", "read_at"),
        Index("ix_user_notifications_entity", "entity_type", "entity_id"),
        Index("ix_user_notifications_ack_queue", "ack_required", "acknowledged_at", "ack_deadline_at"),
    )


class NotificationPreference(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Per-user notification delivery and escalation preferences."""

    __tablename__ = "notification_preferences"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    in_app_enabled = Column(Boolean, nullable=False, default=True)
    email_enabled = Column(Boolean, nullable=False, default=False)
    enabled_categories = Column(JSONB, nullable=False, default=list)
    min_priority = Column(String(20), nullable=False, default="low")
    daily_digest = Column(Boolean, nullable=False, default=False)
    ack_timeout_minutes = Column(Integer, nullable=False, default=60)

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_notification_preferences_user"),
        Index("ix_notification_preferences_tenant_user", "tenant_id", "user_id"),
    )
