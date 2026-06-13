"""Ops Domain Schemas

Pydantic schemas for ops domain endpoints.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# =============================================================================
# Health Schemas
# =============================================================================


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str = "1.0.0"


class ReadinessResponse(BaseModel):
    """Readiness probe response with component status."""

    status: str
    database: str
    redis: str
    timestamp: datetime


class LivenessResponse(BaseModel):
    """Liveness probe response."""

    status: str
    timestamp: datetime


# =============================================================================
# Metric Schemas
# =============================================================================


class MetricEventResponse(BaseModel):
    """Metric event response."""

    id: UUID
    tenant_id: UUID | None
    metric_type: str
    metric_name: str
    value: float
    unit: str
    dimensions: dict[str, Any]
    recorded_at: datetime

    model_config = {"from_attributes": True}


class PlatformMetricsResponse(BaseModel):
    """Platform-wide metrics response."""

    timestamp: datetime
    total_tenants: int
    active_users_24h: int
    total_api_calls_24h: int
    error_rate_percent: float
    avg_latency_ms: float


class TenantMetricsResponse(BaseModel):
    """Tenant-specific metrics response."""

    tenant_id: UUID
    timestamp: datetime
    api_calls_today: int
    api_calls_this_month: int
    storage_used_bytes: int
    storage_limit_bytes: int
    document_count: int
    user_count: int
    active_agents: int


# =============================================================================
# Quota Schemas
# =============================================================================


class QuotaUsageResponse(BaseModel):
    """Quota usage response."""

    id: UUID
    tenant_id: UUID
    quota_type: str
    used_amount: float
    limit_amount: float
    period: str
    reset_at: datetime | None

    model_config = {"from_attributes": True}


class QuotaCheckResponse(BaseModel):
    """Quota check response."""

    quota_type: str
    allowed: bool
    used_amount: float
    limit_amount: float
    remaining: float
    usage_percent: float


class QuotaResetRequest(BaseModel):
    """Quota reset request (admin)."""

    confirm: bool = Field(..., description="Must be true to confirm reset")


class QuotaSetLimitRequest(BaseModel):
    """Quota limit set request (admin)."""

    limit: float = Field(..., gt=0, description="New quota limit")
    period: str = Field(..., description="Period: daily, weekly, monthly, eternal")


class QuotaListResponse(BaseModel):
    """List of quota usages response."""

    quotas: list[QuotaUsageResponse]
    total: int


# =============================================================================
# Alert Schemas
# =============================================================================


class AlertRuleBase(BaseModel):
    """Base alert rule schema."""

    name: str
    condition_json: dict[str, Any]
    notification_channels: list[str] = Field(default_factory=list)


class AlertRuleCreate(AlertRuleBase):
    """Alert rule creation request."""

    pass


class AlertRuleUpdate(BaseModel):
    """Alert rule update request."""

    name: str | None = None
    condition_json: dict[str, Any] | None = None
    notification_channels: list[str] | None = None
    is_active: bool | None = None


class AlertRuleResponse(BaseModel):
    """Alert rule response."""

    id: UUID
    tenant_id: UUID
    name: str
    condition_json: dict[str, Any]
    notification_channels: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AlertRuleListResponse(BaseModel):
    """List of alert rules response."""

    rules: list[AlertRuleResponse]
    total: int


class NotificationDeliveryResponse(BaseModel):
    id: UUID
    tenant_id: UUID | None
    channel: str
    recipient: str | None
    title: str
    body: str
    status: str
    retry_count: str
    error_message: str | None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    sent_at: datetime | None
    next_retry_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NotificationDeliveryListResponse(BaseModel):
    items: list[NotificationDeliveryResponse]
    total: int
    sent_count: int
    failed_count: int
    pending_count: int


# =============================================================================
# Report Schemas
# =============================================================================


class AuditSummaryResponse(BaseModel):
    """Audit summary report response."""

    tenant_id: str
    period: dict[str, str]
    total_actions: int
    actions_by_type: dict[str, int]
    resources_accessed: dict[str, int]
    active_users: int
    top_users: list[tuple[str, int]]


class ProviderStatsResponse(BaseModel):
    """Provider statistics report response."""

    tenant_id: str
    period: dict[str, str]
    providers: dict[str, Any]
    total_provider_calls: int


class AgentStatsResponse(BaseModel):
    """Agent statistics report response."""

    tenant_id: str
    period: dict[str, str]
    agents: dict[str, Any]
    total_agent_runs: int


class QuotaReportResponse(BaseModel):
    """Quota usage report response."""

    tenant_id: str
    generated_at: str
    quotas: list[dict[str, Any]]
    total_quotas: int


# =============================================================================
# Circuit Breaker Schemas
# =============================================================================


class CircuitBreakerStateResponse(BaseModel):
    """Circuit breaker state response."""

    name: str
    state: str
    failure_count: int
    last_failure_time: float | None


class CircuitBreakerListResponse(BaseModel):
    """List of circuit breaker states response."""

    breakers: list[CircuitBreakerStateResponse]


# =============================================================================
# Usage Stats Schemas
# =============================================================================


class UsageStatsResponse(BaseModel):
    """Usage statistics response for a tenant."""

    tenant_id: UUID
    timestamp: datetime
    total_requests: int
    successful_requests: int
    failed_requests: int
    average_latency_ms: float

    model_config = {"from_attributes": True}


class EndpointRateLimitResponse(BaseModel):
    """Endpoint rate limit response."""

    endpoint: str
    limit: int
    remaining: int
    reset_at: datetime

    model_config = {"from_attributes": True}


class RateLimitsResponse(BaseModel):
    """Rate limits response for a tenant."""

    tenant_id: UUID
    timestamp: datetime
    rate_limits: list[EndpointRateLimitResponse]


class QuotaStatusResponse(BaseModel):
    """Quota status response for the frontend (camelCase matching api-client)."""

    used: int
    limit: int
    resetAt: datetime


class QuotaCommandCenterGate(BaseModel):
    """Authoritative operating gate for tenant quota health."""

    status: str = Field(description="passed, attention, or blocked")
    can_operate: bool
    label: str
    summary: str
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class QuotaCommandCenterSummary(BaseModel):
    """Normalized quota and request health metrics."""

    api_used: int
    api_limit: int
    api_remaining: int
    api_usage_percent: float
    total_requests: int
    successful_requests: int
    failed_requests: int
    failure_rate_percent: float
    average_latency_ms: float
    daily_burn: int
    projected_days_remaining: int | None
    risky_endpoint_count: int
    provider_risk_count: int
    open_breaker_count: int


class QuotaCommandCenterRiskItem(BaseModel):
    """One production risk that affects quota operations."""

    code: str
    severity: str
    title: str
    detail: str
    count: int = 1
    href: str


class QuotaCommandCenterAction(BaseModel):
    """Actionable response to a quota operations risk."""

    code: str
    title: str
    description: str
    href: str
    priority: str


class QuotaCommandCenterRateLimitRisk(BaseModel):
    """Endpoint whose remaining rate limit requires attention."""

    endpoint: str
    limit: int
    remaining: int
    used_percentage: float
    reset_at: datetime


class QuotaCommandCenterResponse(BaseModel):
    """Backend-authoritative quota production operations snapshot."""

    generated_at: datetime
    tenant_id: UUID
    release_gate: QuotaCommandCenterGate
    summary: QuotaCommandCenterSummary
    risk_items: list[QuotaCommandCenterRiskItem] = Field(default_factory=list)
    priority_actions: list[QuotaCommandCenterAction] = Field(default_factory=list)
    rate_limit_risks: list[QuotaCommandCenterRateLimitRisk] = Field(default_factory=list)


class CapabilityReadinessItem(BaseModel):
    """Readiness status for one core product capability."""

    key: str
    label: str
    status: str
    score: int
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class CapabilityReadinessResponse(BaseModel):
    """Aggregated core capability readiness for the active tenant/platform."""

    generated_at: datetime
    tenant_id: UUID | None
    overall_status: str
    overall_score: int
    production_ready: bool
    capabilities: list[CapabilityReadinessItem]


class CapabilityActivationAction(BaseModel):
    """One executable or manual action for moving a core capability forward."""

    key: str
    label: str
    capability_key: str
    action_type: str = Field(description="safe or manual")
    status: str = Field(description="planned, completed, skipped, manual, blocked, failed")
    can_execute: bool = False
    requires_confirmation: bool = False
    description: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)


class CapabilityActivationRequest(BaseModel):
    """Request to run safe core capability activation actions."""

    dry_run: bool = True
    confirm: bool = False
    actions: list[str] | None = None


class CapabilityActivationResponse(BaseModel):
    """Activation plan or run result for core product capabilities."""

    generated_at: datetime
    tenant_id: UUID | None
    dry_run: bool
    executed: bool
    readiness_before: CapabilityReadinessResponse
    readiness_after: CapabilityReadinessResponse | None = None
    actions: list[CapabilityActivationAction] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    next_steps: list[str] = Field(default_factory=list)


class CapabilityCommissioningAction(BaseModel):
    """Action target for resolving one production commissioning check."""

    label: str
    href: str
    api_endpoint: str | None = None
    method: str | None = None
    description: str


class CapabilityCommissioningCheck(BaseModel):
    """One executable production commissioning check."""

    key: str
    capability_key: str
    label: str
    status: str = Field(description="passed, failed, warning, or not_run")
    severity: str = Field(description="critical, high, medium, or info")
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    action: CapabilityCommissioningAction
    can_run: bool = False
    configuration_requirements: dict[str, Any] = Field(default_factory=dict)
    validation_steps: list[str] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)
    run_status: str | None = Field(default=None, description="passed, failed, skipped, or null")
    run_result: dict[str, Any] = Field(default_factory=dict)


class CapabilityCommissioningRunRequest(BaseModel):
    """Request to run selected production commissioning checks."""

    checks: list[str] | None = None


class CapabilityCommissioningResponse(BaseModel):
    """Production commissioning summary for core AMX capabilities."""

    generated_at: datetime
    tenant_id: UUID | None
    production_usable: bool
    executed: bool
    overall_status: str
    overall_score: int
    readiness: CapabilityReadinessResponse
    checks: list[CapabilityCommissioningCheck] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    next_steps: list[str] = Field(default_factory=list)


class ProductionOpsReleaseGate(BaseModel):
    """Release gate summary for production operations."""

    status: str
    can_release: bool
    readiness_score: int
    commissioning_score: int
    summary: str


class ProductionOpsBlocker(BaseModel):
    """A normalized production blocker from readiness or commissioning."""

    key: str
    capability_key: str
    label: str
    severity: str
    source: str
    summary: str
    action_label: str | None = None
    action_href: str | None = None
    api_endpoint: str | None = None


class ProductionOpsPriorityAction(BaseModel):
    """Action link for resolving production operations blockers."""

    key: str
    label: str
    href: str
    capability_key: str
    severity: str
    description: str
    api_endpoint: str | None = None


class ProductionOpsCommandCenterResponse(BaseModel):
    """Aggregated production operations command center payload."""

    generated_at: datetime
    tenant_id: UUID | None
    release_gate: ProductionOpsReleaseGate
    summary: dict[str, int] = Field(default_factory=dict)
    blockers: list[ProductionOpsBlocker] = Field(default_factory=list)
    priority_actions: list[ProductionOpsPriorityAction] = Field(default_factory=list)
    readiness: CapabilityReadinessResponse
    commissioning: CapabilityCommissioningResponse
    next_steps: list[str] = Field(default_factory=list)
