"""Ops Domain API Router

FastAPI endpoints for health checks, metrics, quotas, alerts, and reports.
"""

from datetime import datetime, timezone, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.domains.identity.models import User
from app.domains.ops.models import AlertRule, MetricEvent, NotificationEvent, QuotaUsage
from app.domains.ops.schemas import (
    AlertRuleCreate,
    AlertRuleListResponse,
    AlertRuleResponse,
    AlertRuleUpdate,
    CircuitBreakerListResponse,
    CircuitBreakerStateResponse,
    HealthResponse,
    LivenessResponse,
    PlatformMetricsResponse,
    QuotaListResponse,
    QuotaResetRequest,
    QuotaSetLimitRequest,
    QuotaUsageResponse,
    ReadinessResponse,
    TenantMetricsResponse,
    UsageStatsResponse,
    RateLimitsResponse,
    EndpointRateLimitResponse,
    QuotaStatusResponse,
    QuotaCommandCenterResponse,
    CapabilityReadinessResponse,
    CapabilityActivationRequest,
    CapabilityActivationResponse,
    CapabilityCommissioningRunRequest,
    CapabilityCommissioningResponse,
    NotificationDeliveryListResponse,
    NotificationDeliveryResponse,
    ProductionOpsCommandCenterResponse,
)
from app.services.cache_service import CacheService
from app.services.circuit_breaker import get_provider_circuit_breaker
from app.services.quota_service import QuotaService, QuotaType, QuotaExceededError
from app.services.report_service import ReportService
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.domains.identity.service import AuthService
from app.services.permission_evaluator import create_permission_evaluator

router = APIRouter()
security = HTTPBearer()


# ============================================================================
# Dependency Injection
# ============================================================================


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))] = None,
) -> User | None:
    """Dependency to get current user from JWT token.

    For health/metrics endpoints, this may return None for public access.
    """
    if not credentials:
        return None
    auth_service = AuthService(db)
    return await auth_service.get_current_user(credentials.credentials)


async def require_ops_permission(
    action: str,
    user: User | None,
    db: AsyncSession,
) -> User:
    """Require ops RBAC permission for production operation endpoints."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    evaluator = create_permission_evaluator(db)
    if await evaluator.has_permission(user, action, "ops", user.tenant_id):
        return user
    if action == "read" and await evaluator.has_permission(user, "manage", "ops", user.tenant_id):
        return user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Ops permission required",
    )


async def require_ops_reader(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User | None, Depends(get_current_user)],
) -> User:
    """Require read access to production operation evidence."""
    return await require_ops_permission("read", user, db)


async def require_ops_manager(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User | None, Depends(get_current_user)],
) -> User:
    """Require manage access for production operation mutations."""
    return await require_ops_permission("manage", user, db)


async def require_admin(
    user: Annotated[User, Depends(require_ops_manager)],
) -> User:
    """Backward-compatible dependency name for existing admin-only ops mutations."""
    return user


async def require_tenant_scope(
    *,
    db: AsyncSession,
    user: User,
    tenant_id: UUID,
) -> None:
    """Ensure tenant-scoped ops reads and writes do not cross tenant boundaries."""
    evaluator = create_permission_evaluator(db)
    if await evaluator.check_tenant_access(user, tenant_id):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Tenant access required",
    )


# ============================================================================
# Health Endpoints
# ============================================================================


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """System health check endpoint.

    Returns basic health status for container orchestration.
    """
    return HealthResponse(status="healthy", version="1.0.0")


@router.get("/health/ready", response_model=ReadinessResponse, tags=["health"])
async def readiness_probe(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadinessResponse:
    """Readiness probe checking database and Redis connectivity.

    Returns status of all required system components.
    """
    # Check database connection
    db_status = "connected"
    try:
        await db.execute("SELECT 1")
    except Exception:
        db_status = "disconnected"

    # Check Redis connection
    redis_status = "disconnected"
    try:
        cache_service = await CacheService.get_instance()
        if cache_service._redis:
            await cache_service._redis.ping()
            redis_status = "connected"
        else:
            redis_status = "not_configured"
    except Exception:
        redis_status = "disconnected"

    overall_status = "ready" if db_status == "connected" else "not_ready"

    return ReadinessResponse(
        status=overall_status,
        database=db_status,
        redis=redis_status,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/health/live", response_model=LivenessResponse, tags=["health"])
async def liveness_probe() -> LivenessResponse:
    """Liveness probe endpoint.

    Returns basic liveness status.
    """
    return LivenessResponse(
        status="alive",
        timestamp=datetime.now(timezone.utc),
    )


@router.get(
    "/capabilities/readiness",
    response_model=CapabilityReadinessResponse,
    tags=["health"],
)
async def get_capability_readiness(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user)] = None,
) -> CapabilityReadinessResponse:
    """Get core product capability readiness for the active tenant."""
    from app.domains.ops.capability_readiness import CapabilityReadinessService

    tenant_id = current_user.tenant_id if current_user else None
    service = CapabilityReadinessService(db)
    return await service.build(tenant_id)


@router.get(
    "/capabilities/activation-plan",
    response_model=CapabilityActivationResponse,
    tags=["health"],
)
async def get_capability_activation_plan(
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(require_ops_manager)],
) -> CapabilityActivationResponse:
    """Get a dry-run plan for safe core capability activation."""
    from app.domains.ops.capability_activation import CapabilityActivationService

    service = CapabilityActivationService(db)
    return await service.build_plan(admin.tenant_id, admin.id)


@router.post(
    "/capabilities/activation-run",
    response_model=CapabilityActivationResponse,
    tags=["health"],
)
async def run_capability_activation(
    request: CapabilityActivationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(require_ops_manager)],
) -> CapabilityActivationResponse:
    """Run confirmed safe core capability activation actions."""
    from app.domains.ops.capability_activation import CapabilityActivationService

    service = CapabilityActivationService(db)
    return await service.run(admin.tenant_id, admin.id, request)


@router.get(
    "/capabilities/commissioning",
    response_model=CapabilityCommissioningResponse,
    tags=["health"],
)
async def get_capability_commissioning(
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(require_ops_reader)],
) -> CapabilityCommissioningResponse:
    """Get production commissioning checks for core product capabilities."""
    from app.domains.ops.capability_commissioning import CapabilityCommissioningService

    service = CapabilityCommissioningService(db)
    return await service.build(admin.tenant_id)


@router.post(
    "/capabilities/commissioning/run",
    response_model=CapabilityCommissioningResponse,
    tags=["health"],
)
async def run_capability_commissioning(
    request: CapabilityCommissioningRunRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(require_ops_manager)],
) -> CapabilityCommissioningResponse:
    """Run selected production commissioning checks for core capabilities."""
    from app.domains.ops.capability_commissioning import CapabilityCommissioningService

    service = CapabilityCommissioningService(db)
    return await service.run(admin.tenant_id, request)


@router.get(
    "/production-command-center",
    response_model=ProductionOpsCommandCenterResponse,
    tags=["health"],
)
async def get_production_command_center(
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(require_ops_reader)],
) -> ProductionOpsCommandCenterResponse:
    """Get the aggregated production operations command center snapshot."""
    from app.domains.ops.production_command_center import ProductionOpsCommandCenterService

    service = ProductionOpsCommandCenterService(db)
    return await service.build(admin.tenant_id)


# ============================================================================
# Metrics Endpoints
# ============================================================================


@router.get("/metrics", response_model=PlatformMetricsResponse, tags=["metrics"])
async def get_platform_metrics(
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_reader)],
) -> PlatformMetricsResponse:
    """Get platform-wide metrics.

    Returns aggregated metrics across all tenants.
    """
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)

    # Get metric events from last 24 hours
    from sqlalchemy import select, func, and_

    # Total API calls in last 24h
    api_calls_query = select(func.count(MetricEvent.id)).where(
        and_(
            MetricEvent.metric_type == "api_call",
            MetricEvent.recorded_at >= yesterday,
        )
    )
    result = await db.execute(api_calls_query)
    total_api_calls = result.scalar_one() if result.scalar_one_or_none() else 0

    # Error rate calculation
    error_query = select(func.count(MetricEvent.id)).where(
        and_(
            MetricEvent.metric_type == "error",
            MetricEvent.recorded_at >= yesterday,
        )
    )
    result = await db.execute(error_query)
    total_errors = result.scalar_one() if result.scalar_one_or_none() else 0

    error_rate = (total_errors / total_api_calls * 100) if total_api_calls > 0 else 0

    # Average latency
    latency_query = select(func.avg(MetricEvent.value)).where(
        and_(
            MetricEvent.metric_name == "latency_ms",
            MetricEvent.recorded_at >= yesterday,
        )
    )
    result = await db.execute(latency_query)
    avg_latency = result.scalar_one() if result.scalar_one_or_none() else 0

    # Active users count (unique users in last 24h)
    active_users_query = select(func.count(func.distinct(MetricEvent.tenant_id))).where(
        and_(
            MetricEvent.metric_type.in_(["login", "api_call"]),
            MetricEvent.recorded_at >= yesterday,
        )
    )
    result = await db.execute(active_users_query)
    active_users = result.scalar_one() if result.scalar_one_or_none() else 0

    # Total tenants
    tenants_query = select(func.count(func.distinct(MetricEvent.tenant_id)))
    result = await db.execute(tenants_query)
    total_tenants = result.scalar_one() if result.scalar_one_or_none() else 0

    return PlatformMetricsResponse(
        timestamp=now,
        total_tenants=total_tenants,
        active_users_24h=active_users,
        total_api_calls_24h=total_api_calls,
        error_rate_percent=round(error_rate, 2),
        avg_latency_ms=round(avg_latency, 2) if avg_latency else 0,
    )


@router.get(
    "/metrics/tenant/{tenant_id}",
    response_model=TenantMetricsResponse,
    tags=["metrics"],
)
async def get_tenant_metrics(
    tenant_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_reader)],
) -> TenantMetricsResponse:
    """Get tenant-specific metrics.

    Args:
        tenant_id: Tenant UUID

    Returns:
        Tenant metrics including API calls, storage, documents, users
    """
    await require_tenant_scope(db=db, user=ops_user, tenant_id=tenant_id)

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    from sqlalchemy import select, func, and_

    # API calls today
    today_calls_query = select(func.count(MetricEvent.id)).where(
        and_(
            MetricEvent.tenant_id == tenant_id,
            MetricEvent.metric_type == "api_call",
            MetricEvent.recorded_at >= today_start,
        )
    )
    result = await db.execute(today_calls_query)
    api_calls_today = result.scalar_one() if result.scalar_one_or_none() else 0

    # API calls this month
    month_calls_query = select(func.count(MetricEvent.id)).where(
        and_(
            MetricEvent.tenant_id == tenant_id,
            MetricEvent.metric_type == "api_call",
            MetricEvent.recorded_at >= month_start,
        )
    )
    result = await db.execute(month_calls_query)
    api_calls_month = result.scalar_one() if result.scalar_one_or_none() else 0

    # Get quota information
    quota_service = QuotaService(db)

    # Storage
    storage_quota = await quota_service.get_quota_usage(tenant_id, QuotaType.STORAGE_BYTES)
    storage_used = storage_quota.used_amount if storage_quota else 0
    storage_limit = storage_quota.limit_amount if storage_quota else 0

    # Document count
    doc_quota = await quota_service.get_quota_usage(tenant_id, QuotaType.DOCUMENT_COUNT)
    document_count = int(doc_quota.used_amount) if doc_quota else 0

    # User count
    user_quota = await quota_service.get_quota_usage(tenant_id, QuotaType.USER_COUNT)
    user_count = int(user_quota.used_amount) if user_quota else 0

    # Active agents (agents with runs in last 24h)
    yesterday = now - timedelta(days=1)
    agents_query = select(func.count(func.distinct(MetricEvent.dimensions["agent_id"]))).where(
        and_(
            MetricEvent.tenant_id == tenant_id,
            MetricEvent.metric_type == "agent",
            MetricEvent.recorded_at >= yesterday,
        )
    )
    result = await db.execute(agents_query)
    active_agents = result.scalar_one() if result.scalar_one_or_none() else 0

    return TenantMetricsResponse(
        tenant_id=tenant_id,
        timestamp=now,
        api_calls_today=api_calls_today,
        api_calls_this_month=api_calls_month,
        storage_used_bytes=int(storage_used),
        storage_limit_bytes=int(storage_limit),
        document_count=document_count,
        user_count=user_count,
        active_agents=active_agents,
    )


# ============================================================================
# Quota Endpoints
# ============================================================================


@router.get("/quota", response_model=QuotaStatusResponse, tags=["quotas"])
async def get_quota_status(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_ops_reader)],
) -> QuotaStatusResponse:
    """Get active tenant API quota status for frontend display."""
    tenant_id = None
    if current_user:
        tenant_id = current_user.tenant_id

    if not tenant_id:
        # Sandbox fallback
        return QuotaStatusResponse(
            used=120,
            limit=1000,
            resetAt=datetime.now(timezone.utc) + timedelta(days=30)
        )

    quota_service = QuotaService(db)
    api_quota = await quota_service.get_quota_usage(tenant_id, QuotaType.API_CALLS)

    if api_quota:
        used_val = int(api_quota.used_amount)
        limit_val = int(api_quota.limit_amount)
        reset_at_val = api_quota.reset_at or (datetime.now(timezone.utc) + timedelta(days=30))
    else:
        used_val = 0
        limit_val = 1000
        reset_at_val = datetime.now(timezone.utc) + timedelta(days=30)

    return QuotaStatusResponse(
        used=used_val,
        limit=limit_val,
        resetAt=reset_at_val
    )


@router.get("/quotas", response_model=QuotaListResponse, tags=["quotas"])
async def list_quotas(
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_reader)],
    tenant_id: UUID = Query(...),
) -> QuotaListResponse:
    """Get all quota usages for a tenant.

    Args:
        tenant_id: Tenant UUID

    Returns:
        List of quota usage records
    """
    await require_tenant_scope(db=db, user=ops_user, tenant_id=tenant_id)

    quota_service = QuotaService(db)
    quotas = await quota_service.get_all_quotas(tenant_id)

    return QuotaListResponse(
        quotas=[QuotaUsageResponse.model_validate(q) for q in quotas],
        total=len(quotas),
    )


@router.get(
    "/quota-command-center",
    response_model=QuotaCommandCenterResponse,
    tags=["quotas"],
)
async def get_quota_command_center(
    tenant_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_reader)],
) -> QuotaCommandCenterResponse:
    """Get the backend-authoritative quota production operating gate."""
    await require_tenant_scope(db=db, user=ops_user, tenant_id=tenant_id)

    from app.domains.ops.quota_command_center import QuotaCommandCenterService

    return await QuotaCommandCenterService(db).build(tenant_id)


@router.get(
    "/quotas/{quota_type}",
    response_model=QuotaUsageResponse,
    tags=["quotas"],
)
async def get_quota_usage(
    quota_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_reader)],
    tenant_id: UUID = Query(...),
) -> QuotaUsageResponse:
    """Get specific quota usage for a tenant.

    Args:
        quota_type: Quota type (e.g., "API_CALLS", "STORAGE_BYTES")
        tenant_id: Tenant UUID

    Returns:
        Quota usage record

    Raises:
        HTTPException: 404 if quota not found
    """
    await require_tenant_scope(db=db, user=ops_user, tenant_id=tenant_id)

    quota_service = QuotaService(db)
    usage = await quota_service.get_quota_usage(tenant_id, quota_type)

    if not usage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quota {quota_type} not found for tenant",
        )

    return QuotaUsageResponse.model_validate(usage)


@router.post(
    "/quotas/{quota_type}/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["quotas"],
)
async def reset_quota(
    quota_type: str,
    tenant_id: UUID,
    request: QuotaResetRequest,
    admin: Annotated[User, Depends(require_ops_manager)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Reset quota usage to zero (admin only).

    Args:
        quota_type: Quota type to reset
        tenant_id: Tenant UUID
        request: Reset confirmation
        admin: Admin user
        db: Database session

    Raises:
        HTTPException: 400 if not confirmed
    """
    await require_tenant_scope(db=db, user=admin, tenant_id=tenant_id)

    if not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must confirm reset with confirm=true",
        )

    quota_service = QuotaService(db)
    await quota_service.reset_quota(tenant_id, quota_type)


@router.patch(
    "/quotas/{quota_type}",
    response_model=QuotaUsageResponse,
    tags=["quotas"],
)
async def set_quota_limit(
    quota_type: str,
    tenant_id: UUID,
    request: QuotaSetLimitRequest,
    admin: Annotated[User, Depends(require_ops_manager)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuotaUsageResponse:
    """Set quota limit (admin only).

    Args:
        quota_type: Quota type to update
        tenant_id: Tenant UUID
        request: New limit and period
        admin: Admin user
        db: Database session

    Returns:
        Updated quota usage
    """
    await require_tenant_scope(db=db, user=admin, tenant_id=tenant_id)

    quota_service = QuotaService(db)
    usage = await quota_service.set_quota_limit(
        tenant_id,
        quota_type,
        request.limit,
        request.period,
    )
    return QuotaUsageResponse.model_validate(usage)


# ============================================================================
# Usage Stats Endpoints
# ============================================================================


@router.get(
    "/usage-stats",
    response_model=UsageStatsResponse,
    tags=["quotas"],
)
async def get_usage_stats(
    tenant_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_reader)],
) -> UsageStatsResponse:
    """Get usage statistics for a tenant.

    Returns real metrics from metric_events table:
    - total_requests: all API calls in the billing period
    - successful_requests: calls with metric_name not containing "error"
    - failed_requests: calls with metric_name containing "error"
    - average_latency_ms: average latency from api_call metrics

    Args:
        tenant_id: Tenant UUID
        db: Database session

    Returns:
        UsageStatsResponse with real metrics
    """
    await require_tenant_scope(db=db, user=ops_user, tenant_id=tenant_id)

    from sqlalchemy import select, func, and_

    now = datetime.now(timezone.utc)
    # Use a 30-day window for billing period
    period_start = now - timedelta(days=30)

    # Get quota to determine billing period reset
    quota_service = QuotaService(db)
    api_quota = await quota_service.get_quota_usage(tenant_id, QuotaType.API_CALLS)
    if api_quota and api_quota.reset_at:
        period_start = api_quota.reset_at

    # Total requests (all API calls in period)
    total_query = select(func.count(MetricEvent.id)).where(
        and_(
            MetricEvent.tenant_id == tenant_id,
            MetricEvent.metric_type == "api_call",
            MetricEvent.recorded_at >= period_start,
        )
    )
    result = await db.execute(total_query)
    total_requests = result.scalar_one_or_none() or 0

    # Successful requests (no error indicator)
    success_query = select(func.count(MetricEvent.id)).where(
        and_(
            MetricEvent.tenant_id == tenant_id,
            MetricEvent.metric_type == "api_call",
            MetricEvent.metric_name.notlike('%error%'),
            MetricEvent.recorded_at >= period_start,
        )
    )
    result = await db.execute(success_query)
    successful_requests = result.scalar_one_or_none() or 0

    # Failed requests (error indicators)
    failed_query = select(func.count(MetricEvent.id)).where(
        and_(
            MetricEvent.tenant_id == tenant_id,
            MetricEvent.metric_type == "error",
            MetricEvent.recorded_at >= period_start,
        )
    )
    result = await db.execute(failed_query)
    failed_requests = result.scalar_one_or_none() or 0

    # Average latency from api_call metrics
    latency_query = select(func.avg(MetricEvent.value)).where(
        and_(
            MetricEvent.tenant_id == tenant_id,
            MetricEvent.metric_type == "api_call",
            MetricEvent.metric_name == "latency_ms",
            MetricEvent.recorded_at >= period_start,
        )
    )
    result = await db.execute(latency_query)
    avg_latency_ms = round(result.scalar_one_or_none() or 0, 2)

    return UsageStatsResponse(
        tenant_id=tenant_id,
        timestamp=now,
        total_requests=int(total_requests),
        successful_requests=int(successful_requests),
        failed_requests=int(failed_requests),
        average_latency_ms=avg_latency_ms,
    )


@router.get(
    "/rate-limits",
    response_model=RateLimitsResponse,
    tags=["quotas"],
)
async def get_rate_limits(
    tenant_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_reader)],
) -> RateLimitsResponse:
    """Get endpoint rate limits for a tenant.

    Returns real rate limit data from metric_events and cached data.
    Rate limits are tracked per endpoint with remaining quota.

    Args:
        tenant_id: Tenant UUID
        db: Database session

    Returns:
        RateLimitsResponse with per-endpoint rate limits
    """
    await require_tenant_scope(db=db, user=ops_user, tenant_id=tenant_id)

    now = datetime.now(timezone.utc)

    # Known endpoints with their rate limits
    # In production, these would come from a configuration or cached values
    endpoint_configs = [
        {"endpoint": "/api/documents", "limit": 1000},
        {"endpoint": "/api/knowledge", "limit": 500},
        {"endpoint": "/api/agent", "limit": 100},
        {"endpoint": "/api/providers", "limit": 200},
        {"endpoint": "/api/projects", "limit": 300},
    ]

    rate_limits = []
    for config in endpoint_configs:
        endpoint = config["endpoint"]
        limit = config["limit"]

        # Calculate used amount from metric_events (last 1 hour window)
        window_start = now - timedelta(hours=1)

        # Get endpoint usage from API call metrics
        usage_query = select(func.count(MetricEvent.id)).where(
            and_(
                MetricEvent.tenant_id == tenant_id,
                MetricEvent.metric_type == "api_call",
                MetricEvent.dimensions["endpoint"].astext == endpoint,
                MetricEvent.recorded_at >= window_start,
            )
        )
        result = await db.execute(usage_query)
        used = result.scalar_one_or_none() or 0

        # Calculate remaining (rate limit is per minute, scale to per hour)
        remaining = max(0, limit - int(used))

        # Reset at end of current hour
        reset_at = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

        rate_limits.append(
            EndpointRateLimitResponse(
                endpoint=endpoint,
                limit=limit,
                remaining=remaining,
                reset_at=reset_at,
            )
        )

    return RateLimitsResponse(
        tenant_id=tenant_id,
        timestamp=now,
        rate_limits=rate_limits,
    )


# ============================================================================
# Alert Endpoints
# ============================================================================


@router.get("/alerts", response_model=AlertRuleListResponse, tags=["alerts"])
async def list_alert_rules(
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_reader)],
    tenant_id: UUID = Query(...),
    is_active: bool | None = Query(default=None),
) -> AlertRuleListResponse:
    """List alert rules for a tenant.

    Args:
        tenant_id: Tenant UUID
        is_active: Optional filter for active/inactive rules
        db: Database session

    Returns:
        List of alert rules
    """
    await require_tenant_scope(db=db, user=ops_user, tenant_id=tenant_id)

    from sqlalchemy import select

    query = select(AlertRule).where(AlertRule.tenant_id == tenant_id)

    if is_active is not None:
        query = query.where(AlertRule.is_active == is_active)

    result = await db.execute(query)
    rules = list(result.scalars().all())

    return AlertRuleListResponse(
        rules=[AlertRuleResponse.model_validate(r) for r in rules],
        total=len(rules),
    )


@router.post(
    "/alerts",
    response_model=AlertRuleResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["alerts"],
)
async def create_alert_rule(
    tenant_id: UUID,
    data: AlertRuleCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_manager)],
) -> AlertRuleResponse:
    """Create a new alert rule.

    Args:
        tenant_id: Tenant UUID
        data: Alert rule creation data
        db: Database session

    Returns:
        Created alert rule
    """
    await require_tenant_scope(db=db, user=ops_user, tenant_id=tenant_id)

    rule = AlertRule(
        tenant_id=tenant_id,
        name=data.name,
        condition_json=data.condition_json,
        notification_channels=data.notification_channels,
        is_active=True,
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule)

    return AlertRuleResponse.model_validate(rule)


@router.get(
    "/notification-deliveries",
    response_model=NotificationDeliveryListResponse,
    tags=["alerts"],
)
async def list_notification_deliveries(
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_reader)],
    tenant_id: UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    channel: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> NotificationDeliveryListResponse:
    await require_tenant_scope(db=db, user=ops_user, tenant_id=tenant_id)
    from app.domains.ops.notification_delivery_service import NotificationDeliveryService

    return await NotificationDeliveryService(db).list_deliveries(
        tenant_id,
        status=status_filter,
        channel=channel,
        limit=limit,
    )


@router.post(
    "/notification-deliveries/{event_id}/retry",
    response_model=NotificationDeliveryResponse,
    tags=["alerts"],
)
async def retry_notification_delivery(
    event_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_manager)],
) -> NotificationDeliveryResponse:
    event = await db.get(NotificationEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Notification delivery not found")
    await require_tenant_scope(db=db, user=ops_user, tenant_id=event.tenant_id)
    from app.domains.ops.notification_delivery_service import NotificationDeliveryService

    retried = await NotificationDeliveryService(db).retry_delivery(event_id, event.tenant_id)
    if not retried:
        raise HTTPException(status_code=404, detail="Notification delivery not found")
    from app.services.audit_service import AuditService

    await AuditService(db).log_action(
        tenant_id=event.tenant_id,
        user_id=ops_user.id,
        action="notification_delivery.retry",
        resource_type="notification_event",
        resource_id=event.id,
        metadata={"status": retried.status, "channel": retried.channel},
    )
    return NotificationDeliveryResponse.model_validate(retried)


@router.patch(
    "/alerts/{alert_id}",
    response_model=AlertRuleResponse,
    tags=["alerts"],
)
async def update_alert_rule(
    alert_id: UUID,
    data: AlertRuleUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_manager)],
) -> AlertRuleResponse:
    """Update an existing alert rule.

    Args:
        alert_id: Alert rule UUID
        data: Update data
        db: Database session

    Returns:
        Updated alert rule

    Raises:
        HTTPException: 404 if rule not found
    """
    from sqlalchemy import select

    result = await db.execute(select(AlertRule).where(AlertRule.id == alert_id))
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert rule not found",
        )

    await require_tenant_scope(db=db, user=ops_user, tenant_id=rule.tenant_id)

    # Update fields
    if data.name is not None:
        rule.name = data.name
    if data.condition_json is not None:
        rule.condition_json = data.condition_json
    if data.notification_channels is not None:
        rule.notification_channels = data.notification_channels
    if data.is_active is not None:
        rule.is_active = data.is_active

    await db.flush()
    await db.refresh(rule)

    return AlertRuleResponse.model_validate(rule)


# ============================================================================
# Circuit Breaker Endpoints
# ============================================================================


@router.get(
    "/circuit-breakers",
    response_model=CircuitBreakerListResponse,
    tags=["circuit-breakers"],
)
async def list_circuit_breaker_states(
    ops_user: Annotated[User, Depends(require_ops_reader)],
) -> CircuitBreakerListResponse:
    """Get state of all circuit breakers.

    Returns:
        List of circuit breaker states
    """
    breaker_manager = get_provider_circuit_breaker()
    states = breaker_manager.get_all_states()

    breakers = [
        CircuitBreakerStateResponse(
            name=name,
            state=state["state"],
            failure_count=state["failure_count"],
            last_failure_time=state.get("last_failure_time"),
        )
        for name, state in states.items()
    ]

    return CircuitBreakerListResponse(breakers=breakers)


# ============================================================================
# Report Endpoints
# ============================================================================


@router.get("/reports/audit-summary", tags=["reports"])
async def get_audit_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_reader)],
    tenant_id: UUID = Query(...),
    start_date: datetime = Query(...),
    end_date: datetime = Query(...),
) -> dict[str, Any]:
    """Generate audit summary report.

    Args:
        tenant_id: Tenant UUID
        start_date: Start of date range
        end_date: End of date range
        db: Database session

    Returns:
        Audit summary statistics
    """
    await require_tenant_scope(db=db, user=ops_user, tenant_id=tenant_id)

    report_service = ReportService(db)
    return await report_service.generate_audit_summary(tenant_id, start_date, end_date)


@router.get("/reports/provider-stats", tags=["reports"])
async def get_provider_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_reader)],
    tenant_id: UUID = Query(...),
    start_date: datetime = Query(...),
    end_date: datetime = Query(...),
) -> dict[str, Any]:
    """Generate provider statistics report.

    Args:
        tenant_id: Tenant UUID
        start_date: Start of date range
        end_date: End of date range
        db: Database session

    Returns:
        Provider statistics including success rates and latencies
    """
    await require_tenant_scope(db=db, user=ops_user, tenant_id=tenant_id)

    report_service = ReportService(db)
    return await report_service.generate_provider_stats(tenant_id, start_date, end_date)


@router.get("/reports/agent-stats", tags=["reports"])
async def get_agent_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_reader)],
    tenant_id: UUID = Query(...),
    start_date: datetime = Query(...),
    end_date: datetime = Query(...),
) -> dict[str, Any]:
    """Generate agent statistics report.

    Args:
        tenant_id: Tenant UUID
        start_date: Start of date range
        end_date: End of date range
        db: Database session

    Returns:
        Agent run statistics
    """
    await require_tenant_scope(db=db, user=ops_user, tenant_id=tenant_id)

    report_service = ReportService(db)
    return await report_service.generate_agent_stats(tenant_id, start_date, end_date)


@router.get("/reports/quota", tags=["reports"])
async def get_quota_report(
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_reader)],
    tenant_id: UUID = Query(...),
) -> dict[str, Any]:
    """Generate quota usage report.

    Args:
        tenant_id: Tenant UUID
        db: Database session

    Returns:
        Quota usage report
    """
    await require_tenant_scope(db=db, user=ops_user, tenant_id=tenant_id)

    report_service = ReportService(db)
    return await report_service.generate_quota_report(tenant_id)


@router.get("/reports/audit-excel", tags=["reports"])
async def export_audit_excel(
    db: Annotated[AsyncSession, Depends(get_db)],
    ops_user: Annotated[User, Depends(require_ops_reader)],
    tenant_id: UUID = Query(...),
    start_date: datetime = Query(...),
    end_date: datetime = Query(...),
) -> Response:
    """Export audit logs to Excel.

    Args:
        tenant_id: Tenant UUID
        start_date: Start of date range
        end_date: End of date range
        db: Database session

    Returns:
        Excel file download
    """
    await require_tenant_scope(db=db, user=ops_user, tenant_id=tenant_id)

    report_service = ReportService(db)
    excel_bytes = await report_service.export_audit_excel(tenant_id, start_date, end_date)

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=audit_{tenant_id}_{start_date.date()}_{end_date.date()}.xlsx"
        },
    )
