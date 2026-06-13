"""Integration Domain Schemas

Pydantic v2 schemas for request/response validation.
"""

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


T = TypeVar("T")


# =============================================================================
# Integration Provider Schemas
# =============================================================================


class IntegrationProviderBase(BaseModel):
    """Base integration provider schema."""

    provider_type: str = Field(..., description="Provider type (zentao/jira/confluence/...)")
    name: str = Field(..., description="Integration name")
    config_json: dict[str, Any] = Field(default_factory=dict, description="Configuration JSON")
    is_enabled: bool = Field(default=True, description="Whether integration is enabled")


class IntegrationProviderCreate(IntegrationProviderBase):
    """Schema for creating an integration provider."""

    pass


class IntegrationProviderUpdate(BaseModel):
    """Schema for updating an integration provider."""

    name: str | None = None
    config_json: dict[str, Any] | None = None
    is_enabled: bool | None = None


class IntegrationProviderResponse(IntegrationProviderBase):
    """Schema for integration provider response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    last_sync_at: datetime | None
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Webhook Subscription Schemas
# =============================================================================


class WebhookSubscriptionBase(BaseModel):
    """Base webhook subscription schema."""

    url: str = Field(..., description="Webhook callback URL", max_length=2048)
    events: list[str] = Field(default_factory=list, description="Event types to receive")
    is_active: bool = Field(default=True, description="Whether subscription is active")


class WebhookSubscriptionCreate(WebhookSubscriptionBase):
    """Schema for creating a webhook subscription."""

    secret: str | None = Field(None, description="Webhook secret for signature verification")


class WebhookSubscriptionUpdate(BaseModel):
    """Schema for updating a webhook subscription."""

    url: str | None = None
    events: list[str] | None = None
    is_active: bool | None = None


class WebhookSubscriptionResponse(WebhookSubscriptionBase):
    """Schema for webhook subscription response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    integration_provider_id: UUID
    secret: str | None
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Integration Inbound Event Schemas
# =============================================================================


class IntegrationInboundEventCreate(BaseModel):
    """Schema for creating an integration inbound event."""

    event_type: str = Field(..., description="Type of event")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event payload")


class IntegrationInboundEventResponse(BaseModel):
    """Schema for integration inbound event response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    integration_provider_id: UUID
    event_type: str
    payload: dict[str, Any]
    processed: bool
    processed_at: datetime | None
    created_at: datetime


# =============================================================================
# Webhook Delivery Event Schemas
# =============================================================================


class WebhookDeliveryEventCreate(BaseModel):
    """Schema for creating a webhook delivery event."""

    webhook_subscription_id: UUID = Field(..., description="Webhook subscription ID")
    event_id: str = Field(..., description="Event ID")
    url: str = Field(..., description="Delivery URL")
    request_headers: dict[str, Any] = Field(default_factory=dict, description="Request headers")
    request_body: dict[str, Any] = Field(default_factory=dict, description="Request body")
    attempts: int = Field(default=1, description="Number of delivery attempts")


class WebhookDeliveryEventResponse(BaseModel):
    """Schema for webhook delivery event response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    webhook_subscription_id: UUID
    event_id: str
    url: str
    request_headers: dict[str, Any]
    request_body: dict[str, Any]
    response_status: int | None
    response_body: str | None
    error_message: str | None
    attempts: int
    delivered_at: datetime | None
    created_at: datetime


# =============================================================================
# Outbox Event Schemas
# =============================================================================


class OutboxEventBase(BaseModel):
    """Base outbox event schema."""

    aggregate_type: str = Field(..., description="Type of aggregate (e.g., document, project)")
    aggregate_id: UUID = Field(..., description="ID of the aggregate")
    event_type: str = Field(..., description="Event type (e.g., created, updated)")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event payload")


class OutboxEventCreate(OutboxEventBase):
    """Schema for creating an outbox event."""

    pass


class OutboxEventResponse(OutboxEventBase):
    """Schema for outbox event response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    published: bool
    published_at: datetime | None
    created_at: datetime


# =============================================================================
# Webhook Payload Schema
# =============================================================================


class WebhookPayload(BaseModel):
    """Schema for incoming webhook payloads."""

    event_type: str = Field(..., description="Type of event")
    event_id: str = Field(..., description="Unique event identifier for idempotency")
    timestamp: datetime | None = Field(None, description="Event timestamp")
    data: dict[str, Any] = Field(default_factory=dict, description="Event data")


# =============================================================================
# Test Connection Schemas
# =============================================================================


class TestConnectionRequest(BaseModel):
    """Schema for testing a connection."""

    pass


class TestConnectionResponse(BaseModel):
    """Schema for connection test response."""

    status: str = Field(..., description="Connection status")
    message: str = Field(..., description="Status message")
    details: dict[str, Any] | None = Field(None, description="Additional details")


class IntegrationOperationsEvidence(BaseModel):
    """Operational evidence for integration production readiness."""

    integration_count: int
    enabled_integration_count: int
    configured_integration_count: int
    synced_integration_count: int
    webhook_count: int
    active_webhook_count: int
    successful_delivery_count: int
    failed_delivery_count: int
    pending_outbox_count: int
    failed_outbox_count: int
    project_binding_count: int = 0
    completed_project_sync_count: int = 0
    synced_asset_count: int = 0


class IntegrationOperationsSummary(BaseModel):
    """Integration and webhook production operations summary."""

    status: str
    score: int
    summary: str
    evidence: IntegrationOperationsEvidence
    blockers: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class IntegrationProductionReleaseGate(BaseModel):
    """Release gate for external integration production readiness."""

    status: str
    label: str
    summary: str
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class IntegrationProductionRiskItem(BaseModel):
    """Actionable integration production risk."""

    code: str
    severity: str
    title: str
    detail: str
    count: int
    href: str


class IntegrationProductionPriorityAction(BaseModel):
    """Priority action for closing integration readiness."""

    code: str
    title: str
    description: str
    href: str
    priority: str


class IntegrationProductionCommandCenter(BaseModel):
    """Integration production command center payload."""

    release_gate: IntegrationProductionReleaseGate
    summary: dict[str, int]
    risk_items: list[IntegrationProductionRiskItem]
    priority_actions: list[IntegrationProductionPriorityAction]
    operations_summary: IntegrationOperationsSummary


class IntegrationOperationsIncident(BaseModel):
    """One actionable production integration incident."""

    id: UUID
    category: str
    severity: str
    title: str
    detail: str
    status: str
    attempts: int = 0
    occurred_at: datetime
    action_type: str
    action_href: str


class IntegrationOperationsIncidentQueue(BaseModel):
    """Cross-channel failure queue for integration operators."""

    total: int
    critical_count: int
    retryable_count: int
    items: list[IntegrationOperationsIncident]


class IntegrationProjectBindingCreate(BaseModel):
    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    scope: dict[str, Any] = Field(default_factory=dict)
    field_mapping: dict[str, str] = Field(default_factory=dict)
    is_enabled: bool = True


class IntegrationProjectBindingUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    scope: dict[str, Any] | None = None
    field_mapping: dict[str, str] | None = None
    is_enabled: bool | None = None


class IntegrationProjectBindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    integration_provider_id: UUID
    project_id: UUID
    name: str
    scope_json: dict[str, Any]
    field_mapping_json: dict[str, Any]
    cursor_json: dict[str, Any]
    is_enabled: bool
    last_sync_status: str | None
    last_synced_at: datetime | None
    last_error: str | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class IntegrationNormalizedItem(BaseModel):
    external_id: str
    title: str
    content: str
    external_url: str | None = None
    external_updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IntegrationSyncPreviewResponse(BaseModel):
    binding_id: UUID
    total: int
    items: list[IntegrationNormalizedItem]
    cursor: dict[str, Any] = Field(default_factory=dict)


class IntegrationSyncRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    binding_id: UUID
    status: str
    mode: str
    cursor_before_json: dict[str, Any]
    cursor_after_json: dict[str, Any]
    total_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    failed_count: int
    error_message: str | None
    details_json: dict[str, Any]
    requested_by: UUID | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime


# =============================================================================
# Pagination
# =============================================================================


class PaginationParams(BaseModel):
    """Pagination parameters for list endpoints."""

    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response schema."""

    items: list[T]
    total: int
    page: int
    page_size: int
    has_more: bool
