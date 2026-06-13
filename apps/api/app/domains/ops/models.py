"""Ops Domain Models

Defines MetricEvent, QuotaUsage, and AlertRule for platform observability.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import (
    Base,
    TimestampMixin,
    UuidMixin,
)

if TYPE_CHECKING:
    pass


class MetricEvent(Base, UuidMixin, TimestampMixin):
    """Metric event model for tracking platform metrics.

    Stores time-series metric data for SLA monitoring, provider stats, etc.
    Uses monthly partitioning recommended for high-volume metric tables.
    """

    __tablename__ = "metric_events"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    metric_type = Column(
        String(50),
        nullable=False,
        index=True,
    )  # "sla", "provider", "agent", "system"
    metric_name = Column(
        String(100),
        nullable=False,
        index=True,
    )  # "api_latency_ms", "provider_success_rate"
    value = Column(
        Float,
        nullable=False,
    )
    unit = Column(
        String(20),
        nullable=False,
        default="count",
    )  # "ms", "percent", "count", "bytes"
    dimensions = Column(
        JSONB,
        nullable=True,
        default=dict,
    )  # Additional metadata like provider_name, agent_id, region
    recorded_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relations
    tenant = relationship("Tenant", lazy="selectin")

    __table_args__ = (
        Index("ix_metric_events_tenant_type_name_recorded", "tenant_id", "metric_type", "metric_name", "recorded_at"),
        Index("ix_metric_events_recorded_at", "recorded_at"),
    )


class QuotaUsage(Base, UuidMixin, TimestampMixin):
    """Quota usage model for tracking resource consumption.

    Tracks usage against defined limits for different quota types per tenant.
    Period can be "daily", "weekly", "monthly", "eternal".
    """

    __tablename__ = "quota_usages"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quota_type = Column(
        String(50),
        nullable=False,
        index=True,
    )  # "API_CALLS", "STORAGE_BYTES", "DOCUMENT_COUNT", "USER_COUNT", "EXPORT_COUNT"
    used_amount = Column(
        Float,
        nullable=False,
        default=0,
    )
    limit_amount = Column(
        Float,
        nullable=False,
        default=0,
    )
    period = Column(
        String(20),
        nullable=False,
        default="monthly",
    )  # "daily", "weekly", "monthly", "eternal"
    reset_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relations
    tenant = relationship("Tenant", lazy="selectin")

    __table_args__ = (
        Index("ix_quota_usages_tenant_quota_type", "tenant_id", "quota_type", unique=True),
    )


class AlertRule(Base, UuidMixin, TimestampMixin):
    """Alert rule model for configuring threshold-based notifications.

    Defines conditions that trigger alerts when metrics exceed thresholds.
    """

    __tablename__ = "alert_rules"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(
        String(255),
        nullable=False,
    )
    condition_json = Column(
        JSONB,
        nullable=False,
        default=dict,
    )  # {"metric_type": "provider", "metric_name": "success_rate", "operator": "<", "threshold": 0.95}
    notification_channels = Column(
        JSONB,
        nullable=False,
        default=list,
    )  # ["email:admin@company.com", "slack:#alerts"]
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    # Relations
    tenant = relationship("Tenant", lazy="selectin")

    __table_args__ = (
        Index("ix_alert_rules_tenant_active", "tenant_id", "is_active"),
    )


class NotificationEvent(Base, UuidMixin, TimestampMixin):
    """Notification event model for tracking notification delivery.

    Stores notification events for audit, retry, and failure analysis.
    """

    __tablename__ = "notification_events"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    channel = Column(
        String(20),
        nullable=False,
    )  # "email", "webhook", "system", "sms"
    recipient = Column(
        String(500),
        nullable=True,
    )  # email address or webhook URL
    title = Column(
        String(255),
        nullable=False,
    )
    body = Column(
        String(2000),
        nullable=False,
    )
    status = Column(
        String(20),
        nullable=False,
        default="pending",
    )  # "pending", "sent", "failed", "retrying"
    retry_count = Column(
        String(10),
        nullable=False,
        default=0,
    )
    error_message = Column(
        String(1000),
        nullable=True,
    )
    metadata_json = Column(
        JSONB,
        nullable=True,
        default=dict,
    )
    sent_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_retry_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relations
    tenant = relationship("Tenant", lazy="selectin")

    __table_args__ = (
        Index("ix_notification_events_tenant_status", "tenant_id", "status"),
        Index("ix_notification_events_channel_status", "channel", "status"),
    )
