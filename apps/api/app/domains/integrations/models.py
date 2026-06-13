"""Integration Domain Models

Models for third-party integrations, webhooks, and outbox events.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UuidMixin,
)


class ProviderType(str, Enum):
    """Supported third-party integration providers."""

    ZENTAO = "zentao"
    JIRA = "jira"
    CONFLUENCE = "confluence"
    PINGCODE = "pingcode"
    TAPD = "tapd"
    FEISHU = "feishu"
    WECOM = "wecom"
    DINGTALK = "dingtalk"
    CUSTOM = "custom"


class IntegrationProvider(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Third-party integration provider configuration.

    Stores encrypted credentials and connection settings for
    external services like Jira, Confluence, ZenTao, etc.
    """

    __tablename__ = "integration_providers"

    provider_type = Column(
        String(50),
        nullable=False,
        index=True,
    )
    name = Column(
        String(255),
        nullable=False,
    )
    config_json = Column(
        JSONB,
        nullable=False,
        default=dict,
    )
    is_enabled = Column(
        Boolean,
        nullable=False,
        default=True,
    )
    last_sync_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relations
    webhook_subscriptions = relationship(
        "WebhookSubscription",
        back_populates="integration_provider",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    inbound_events = relationship(
        "IntegrationInboundEvent",
        back_populates="integration_provider",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    project_bindings = relationship(
        "IntegrationProjectBinding",
        back_populates="integration_provider",
        lazy="noload",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_integration_providers_tenant_id", "tenant_id"),
        Index("ix_integration_providers_provider_type", "provider_type"),
        Index("ix_integration_providers_is_enabled", "is_enabled"),
    )


class IntegrationProjectBinding(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Bind one external integration scope to one AMX project."""

    __tablename__ = "integration_project_bindings"

    integration_provider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    scope_json = Column(JSONB, nullable=False, default=dict)
    field_mapping_json = Column(JSONB, nullable=False, default=dict)
    cursor_json = Column(JSONB, nullable=False, default=dict)
    is_enabled = Column(Boolean, nullable=False, default=True, index=True)
    last_sync_status = Column(String(20), nullable=True, index=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    integration_provider = relationship("IntegrationProvider", back_populates="project_bindings", lazy="selectin")
    runs = relationship(
        "IntegrationSyncRun",
        back_populates="binding",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="IntegrationSyncRun.created_at.desc()",
    )
    assets = relationship(
        "IntegrationSyncedAsset",
        back_populates="binding",
        lazy="noload",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "integration_provider_id",
            "project_id",
            "name",
            name="uq_integration_project_bindings_scope",
        ),
        Index("ix_integration_project_bindings_tenant_project", "tenant_id", "project_id"),
    )


class IntegrationSyncRun(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Durable evidence for one preview or synchronization execution."""

    __tablename__ = "integration_sync_runs"

    binding_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_project_bindings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(20), nullable=False, default="running", index=True)
    mode = Column(String(20), nullable=False, default="sync")
    cursor_before_json = Column(JSONB, nullable=False, default=dict)
    cursor_after_json = Column(JSONB, nullable=False, default=dict)
    total_count = Column(Integer, nullable=False, default=0)
    created_count = Column(Integer, nullable=False, default=0)
    updated_count = Column(Integer, nullable=False, default=0)
    unchanged_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    details_json = Column(JSONB, nullable=False, default=dict)
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    binding = relationship("IntegrationProjectBinding", back_populates="runs", lazy="selectin")

    __table_args__ = (
        Index("ix_integration_sync_runs_tenant_status", "tenant_id", "status"),
        Index("ix_integration_sync_runs_binding_created", "binding_id", "created_at"),
    )


class IntegrationSyncedAsset(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Idempotency mapping from an external item to AMX project assets."""

    __tablename__ = "integration_synced_assets"

    binding_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_project_bindings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id = Column(String(512), nullable=False)
    external_url = Column(Text, nullable=True)
    external_updated_at = Column(String(100), nullable=True)
    content_hash = Column(String(64), nullable=False, index=True)
    source_file_id = Column(UUID(as_uuid=True), ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False)
    knowledge_entry_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_entries.id", ondelete="CASCADE"), nullable=False)
    metadata_json = Column(JSONB, nullable=False, default=dict)

    binding = relationship("IntegrationProjectBinding", back_populates="assets", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("binding_id", "external_id", name="uq_integration_synced_assets_external"),
        Index("ix_integration_synced_assets_tenant_binding", "tenant_id", "binding_id"),
    )


class WebhookSubscription(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Webhook subscription for receiving events from integrations.

    Stores the callback URL and event types to receive from
    third-party services.
    """

    __tablename__ = "webhook_subscriptions"

    tenant_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    integration_provider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url = Column(
        String(2048),
        nullable=False,
    )
    secret = Column(
        String(255),
        nullable=True,
    )
    events = Column(
        JSONB,
        nullable=False,
        default=list,
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    # Relations
    integration_provider = relationship(
        "IntegrationProvider",
        back_populates="webhook_subscriptions",
        lazy="selectin",
    )
    delivery_events = relationship(
        "WebhookDeliveryEvent",
        back_populates="webhook_subscription",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_webhook_subscriptions_tenant_id", "tenant_id"),
        Index("ix_webhook_subscriptions_integration_provider_id", "integration_provider_id"),
        Index("ix_webhook_subscriptions_is_active", "is_active"),
    )


class IntegrationInboundEvent(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Inbound webhook event from third-party integrations.

    Stores raw event data received from external services
    for processing and correlation.
    """

    __tablename__ = "integration_inbound_events"

    tenant_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    integration_provider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(
        String(100),
        nullable=False,
        index=True,
    )
    payload = Column(
        JSONB,
        nullable=False,
        default=dict,
    )
    processed = Column(
        Boolean,
        nullable=False,
        default=False,
    )
    processed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relations
    integration_provider = relationship(
        "IntegrationProvider",
        back_populates="inbound_events",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_integration_inbound_events_tenant_id", "tenant_id"),
        Index("ix_integration_inbound_events_integration_provider_id", "integration_provider_id"),
        Index("ix_integration_inbound_events_event_type", "event_type"),
        Index("ix_integration_inbound_events_processed", "processed"),
    )


class WebhookDeliveryEvent(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Webhook delivery attempt record.

    Tracks outbound webhook deliveries including request details,
    response status, and retry attempts.
    """

    __tablename__ = "webhook_delivery_events"

    tenant_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    webhook_subscription_id = Column(
        UUID(as_uuid=True),
        ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id = Column(
        String(255),
        nullable=False,
        index=True,
    )
    url = Column(
        String(2048),
        nullable=False,
    )
    request_headers = Column(
        JSONB,
        nullable=False,
        default=dict,
    )
    request_body = Column(
        JSONB,
        nullable=False,
        default=dict,
    )
    response_status = Column(
        Integer,
        nullable=True,
    )
    response_body = Column(
        Text,
        nullable=True,
    )
    error_message = Column(
        Text,
        nullable=True,
    )
    attempts = Column(
        Integer,
        nullable=False,
        default=1,
    )
    delivered_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relations
    webhook_subscription = relationship(
        "WebhookSubscription",
        back_populates="delivery_events",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_webhook_delivery_events_tenant_id", "tenant_id"),
        Index("ix_webhook_delivery_events_webhook_subscription_id", "webhook_subscription_id"),
        Index("ix_webhook_delivery_events_event_id", "event_id"),
        Index("ix_webhook_delivery_events_delivered_at", "delivered_at"),
    )


class OutboxEventStatus(str, Enum):
    """Status of outbox events."""
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"


class OutboxEvent(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Outbox event for reliable event publishing.

    Implements the outbox pattern for guaranteed event delivery
    to external systems via webhooks or other channels.
    """

    __tablename__ = "outbox_events"

    tenant_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    aggregate_type = Column(
        String(100),
        nullable=False,
        index=True,
    )
    aggregate_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    event_type = Column(
        String(100),
        nullable=False,
        index=True,
    )
    payload = Column(
        JSONB,
        nullable=False,
        default=dict,
    )
    status = Column(
        String(20),
        nullable=False,
        default=OutboxEventStatus.PENDING.value,
        index=True,
    )
    attempts = Column(
        Integer,
        nullable=False,
        default=0,
    )
    max_attempts = Column(
        Integer,
        nullable=False,
        default=3,
    )
    last_error = Column(
        Text,
        nullable=True,
    )
    published = Column(
        Boolean,
        nullable=False,
        default=False,
    )
    published_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_outbox_events_tenant_id", "tenant_id"),
        Index("ix_outbox_events_aggregate_type", "aggregate_type"),
        Index("ix_outbox_events_aggregate_id", "aggregate_id"),
        Index("ix_outbox_events_event_type", "event_type"),
        Index("ix_outbox_events_status", "status"),
        Index("ix_outbox_events_published", "published"),
    )
