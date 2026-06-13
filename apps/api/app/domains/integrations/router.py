"""Integrations Domain API Router

Endpoints for third-party integration management, webhooks, and outbox events.
"""

import hashlib
import hmac
import json
import logfire
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.security import decode_token
from app.domains.integrations.models import (
    IntegrationProvider,
    WebhookSubscription,
    IntegrationInboundEvent,
    OutboxEvent,
)
from app.domains.integrations.schemas import (
    IntegrationProviderCreate,
    IntegrationProviderUpdate,
    IntegrationProviderResponse,
    WebhookSubscriptionCreate,
    WebhookSubscriptionUpdate,
    WebhookSubscriptionResponse,
    WebhookDeliveryEventResponse,
    IntegrationInboundEventResponse,
    OutboxEventCreate,
    OutboxEventResponse,
    WebhookPayload,
    TestConnectionResponse,
    IntegrationProductionCommandCenter,
    IntegrationOperationsIncidentQueue,
    IntegrationOperationsSummary,
    IntegrationProjectBindingCreate,
    IntegrationProjectBindingResponse,
    IntegrationProjectBindingUpdate,
    IntegrationSyncPreviewResponse,
    IntegrationSyncRunResponse,
    PaginationParams,
)
from app.domains.integrations.project_sync_service import IntegrationProjectSyncService
from app.domains.integrations.service import (
    IntegrationService,
    WebhookService,
    OutboxService,
)
from app.models.identity import User


router = APIRouter()


async def get_current_user(
    authorization: str = Header(..., description="Bearer token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency to get current authenticated user.

    Args:
        authorization: Bearer token header
        db: Database session

    Returns:
        User: Current authenticated user

    Raises:
        HTTPException: If token is invalid or user not found
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization[7:]  # Strip "Bearer " prefix

    try:
        from app.domains.identity.service import AuthService

        auth_service = AuthService(db)
        user = await auth_service.get_current_user(token)

        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        return user
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


# =============================================================================
# Integration Provider Endpoints
# =============================================================================


@router.get("", response_model=dict)
async def list_integrations(
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all integrations for the current tenant.

    Args:
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of integrations
    """
    service = IntegrationService(db)
    integrations, total = await service.list_integrations(
        tenant_id=current_user.tenant_id,
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
    )
    has_more = (pagination.page * pagination.page_size) < total

    return {
        "items": [IntegrationProviderResponse.model_validate(i) for i in integrations],
        "total": total,
        "page": pagination.page,
        "page_size": pagination.page_size,
        "has_more": has_more,
    }


@router.post("", response_model=IntegrationProviderResponse, status_code=201)
async def create_integration(
    data: IntegrationProviderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new integration.

    Args:
        data: Integration creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created integration
    """
    service = IntegrationService(db)
    integration = await service.create_integration(
        tenant_id=current_user.tenant_id,
        provider_type=data.provider_type,
        name=data.name,
        config=data.config_json,
    )
    return IntegrationProviderResponse.model_validate(integration)


@router.get("/operations/summary", response_model=IntegrationOperationsSummary)
async def get_integration_operations_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get integration, webhook, and outbox production operations evidence."""
    service = IntegrationService(db)
    return await service.build_operations_summary(current_user.tenant_id)


@router.get("/operations/command-center", response_model=IntegrationProductionCommandCenter)
async def get_integration_production_command_center(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get integration production release gate, risks, and priority actions."""
    service = IntegrationService(db)
    return await service.build_production_command_center(current_user.tenant_id)


@router.get("/operations/incidents", response_model=IntegrationOperationsIncidentQueue)
async def get_integration_operations_incidents(
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the actionable cross-channel integration failure queue."""
    return await IntegrationService(db).build_incident_queue(current_user.tenant_id, limit)


@router.get("/{integration_id}/project-bindings", response_model=list[IntegrationProjectBindingResponse])
async def list_project_bindings(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await IntegrationProjectSyncService(db).list_bindings(integration_id, current_user.tenant_id)


@router.post("/{integration_id}/project-bindings", response_model=IntegrationProjectBindingResponse, status_code=201)
async def create_project_binding(
    integration_id: UUID,
    data: IntegrationProjectBindingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await IntegrationProjectSyncService(db).create_binding(
            tenant_id=current_user.tenant_id,
            integration_id=integration_id,
            project_id=data.project_id,
            name=data.name,
            scope=data.scope,
            field_mapping=data.field_mapping,
            is_enabled=data.is_enabled,
            created_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/project-bindings/{binding_id}", response_model=IntegrationProjectBindingResponse)
async def update_project_binding(
    binding_id: UUID,
    data: IntegrationProjectBindingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    binding = await IntegrationProjectSyncService(db).update_binding(binding_id, current_user.tenant_id, data)
    if not binding:
        raise HTTPException(status_code=404, detail="Integration project binding not found")
    return binding


@router.post("/project-bindings/{binding_id}/preview", response_model=IntegrationSyncPreviewResponse)
async def preview_project_binding(
    binding_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await IntegrationProjectSyncService(db).preview_binding(binding_id, current_user.tenant_id, limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/project-bindings/{binding_id}/sync", response_model=IntegrationSyncRunResponse)
async def sync_project_binding(
    binding_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await IntegrationProjectSyncService(db).sync_binding(binding_id, current_user.tenant_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/project-bindings/{binding_id}/runs", response_model=list[IntegrationSyncRunResponse])
async def list_project_binding_runs(
    binding_id: UUID,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await IntegrationProjectSyncService(db).list_runs(binding_id, current_user.tenant_id, limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sync-runs/{run_id}/retry", response_model=IntegrationSyncRunResponse)
async def retry_project_binding_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await IntegrationProjectSyncService(db).retry_run(run_id, current_user.tenant_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{integration_id}", response_model=IntegrationProviderResponse)
async def get_integration(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get an integration by ID.

    Args:
        integration_id: Integration UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Integration details

    Raises:
        HTTPException: If integration not found
    """
    service = IntegrationService(db)
    integration = await service.get_integration(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
    )

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    return IntegrationProviderResponse.model_validate(integration)


@router.patch("/{integration_id}", response_model=IntegrationProviderResponse)
async def update_integration(
    integration_id: UUID,
    data: IntegrationProviderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an integration.

    Args:
        integration_id: Integration UUID
        data: Update data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated integration

    Raises:
        HTTPException: If integration not found
    """
    service = IntegrationService(db)
    integration = await service.update_integration(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
        updates=data,
    )

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    return IntegrationProviderResponse.model_validate(integration)


@router.delete("/{integration_id}", status_code=204)
async def delete_integration(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an integration (soft delete).

    Args:
        integration_id: Integration UUID
        db: Database session
        current_user: Current authenticated user

    Raises:
        HTTPException: If integration not found
    """
    service = IntegrationService(db)
    deleted = await service.delete_integration(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
    )

    if not deleted:
        raise HTTPException(status_code=404, detail="Integration not found")


@router.post("/{integration_id}/test", response_model=TestConnectionResponse)
async def test_integration_connection(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test an integration connection.

    Args:
        integration_id: Integration UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Connection test result
    """
    service = IntegrationService(db)
    result = await service.test_connection(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
    )
    return TestConnectionResponse(**result)


@router.post("/{integration_id}/sync")
async def sync_integration(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger integration sync.

    Args:
        integration_id: Integration UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Sync result
    """
    service = IntegrationService(db)
    result = await service.sync_integration(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
    )
    return result


# =============================================================================
# Webhook Subscription Endpoints
# =============================================================================


@router.get("/{integration_id}/webhooks", response_model=dict)
async def list_webhooks(
    integration_id: UUID,
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List webhook subscriptions for an integration.

    Args:
        integration_id: Integration UUID
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of webhooks
    """
    service = WebhookService(db)
    webhooks, total = await service.list_subscriptions(
        tenant_id=current_user.tenant_id,
        integration_id=integration_id,
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
    )
    has_more = (pagination.page * pagination.page_size) < total

    return {
        "items": [WebhookSubscriptionResponse.model_validate(w) for w in webhooks],
        "total": total,
        "page": pagination.page,
        "page_size": pagination.page_size,
        "has_more": has_more,
    }


@router.post("/{integration_id}/webhooks", response_model=WebhookSubscriptionResponse, status_code=201)
async def create_webhook(
    integration_id: UUID,
    data: WebhookSubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a webhook subscription.

    Args:
        integration_id: Integration UUID
        data: Webhook creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created webhook subscription
    """
    # Verify integration exists and belongs to tenant
    integration_service = IntegrationService(db)
    integration = await integration_service.get_integration(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    service = WebhookService(db)
    webhook = await service.create_subscription(
        tenant_id=current_user.tenant_id,
        integration_id=integration_id,
        url=data.url,
        events=data.events,
        secret=data.secret,
    )
    return WebhookSubscriptionResponse.model_validate(webhook)


@router.delete("/{integration_id}/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(
    integration_id: UUID,
    webhook_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a webhook subscription.

    Args:
        integration_id: Integration UUID
        webhook_id: Webhook UUID
        db: Database session
        current_user: Current authenticated user

    Raises:
        HTTPException: If webhook not found
    """
    service = WebhookService(db)
    deleted = await service.delete_subscription(
        subscription_id=webhook_id,
        tenant_id=current_user.tenant_id,
    )

    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook not found")


@router.patch("/{integration_id}/webhooks/{webhook_id}", response_model=WebhookSubscriptionResponse)
async def update_webhook(
    integration_id: UUID,
    webhook_id: UUID,
    data: WebhookSubscriptionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a webhook subscription.

    Args:
        integration_id: Integration UUID
        webhook_id: Webhook UUID
        data: Update data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated webhook subscription

    Raises:
        HTTPException: If webhook not found
    """
    service = WebhookService(db)

    # First verify webhook belongs to tenant
    webhook = await service.get_subscription(webhook_id, current_user.tenant_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    # Verify integration belongs to tenant
    integration_service = IntegrationService(db)
    integration = await integration_service.get_integration(
        integration_id=integration_id,
        tenant_id=current_user.tenant_id,
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    # Apply updates
    if data.url is not None:
        webhook.url = data.url
    if data.events is not None:
        webhook.events = data.events
    if data.is_active is not None:
        webhook.is_active = data.is_active

    await db.flush()
    await db.refresh(webhook)

    return WebhookSubscriptionResponse.model_validate(webhook)


# =============================================================================
# Inbound Webhook Endpoint
# =============================================================================


@router.post("/webhooks/inbound")
async def receive_inbound_webhook(
    request: Request,
    provider_id: UUID = Query(..., description="Integration provider ID"),
    db: AsyncSession = Depends(get_db),
):
    """Receive an incoming webhook from a third-party integration.

    This endpoint verifies the webhook signature using HMAC-SHA256 if a
    webhook_secret is configured on the integration. If no secret is
    configured, signature verification is skipped (not recommended for production).

    Args:
        request: FastAPI request object for reading raw body
        provider_id: Integration provider UUID
        db: Database session

    Returns:
        Acknowledgment

    Raises:
        HTTPException: If signature verification fails or integration not found
    """
    # Get integration to find tenant and webhook secret
    integration_service = IntegrationService(db)
    integration = await integration_service.get_integration(integration_id=provider_id)

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    # Verify HMAC-SHA256 signature if webhook_secret is configured
    webhook_secret = integration.config_json.get("webhook_secret")
    if webhook_secret:
        # Get raw request body for signature verification
        body = await request.body()
        signature_header = request.headers.get("X-Webhook-Signature")

        if not signature_header:
            raise HTTPException(
                status_code=401,
                detail="Missing webhook signature. Provide X-Webhook-Signature header.",
            )

        # Compute expected signature
        expected_signature = hmac.new(
            webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()

        # Verify signature using constant-time comparison
        if not hmac.compare_digest(f"sha256={expected_signature}", signature_header):
            raise HTTPException(
                status_code=401,
                detail="Invalid webhook signature",
            )

        logfire.info(f"Webhook signature verified for provider: {provider_id}")

    # Parse JSON payload
    try:
        payload_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    service = WebhookService(db)
    event = await service.handle_inbound_webhook(
        tenant_id=integration.tenant_id,
        integration_id=provider_id,
        event_type=payload_data.get("event_type", "unknown"),
        payload=payload_data.get("data", payload_data),
    )

    return {
        "status": "received",
        "event_id": str(event.id),
    }


@router.get("/webhooks/{webhook_id}/deliveries", response_model=dict)
async def get_webhook_deliveries(
    webhook_id: UUID,
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get delivery history for a webhook subscription.

    Args:
        webhook_id: Webhook subscription UUID
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of delivery events
    """
    from sqlalchemy import select

    # Verify webhook belongs to tenant
    service = WebhookService(db)
    webhook = await service.get_subscription(webhook_id, current_user.tenant_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    # Get deliveries
    from app.domains.integrations.models import WebhookDeliveryEvent

    # Count total - verify tenant via webhook subscription
    count_result = await db.execute(
        select(func.count(WebhookDeliveryEvent.id)).where(
            WebhookDeliveryEvent.webhook_subscription_id == webhook_id,
            WebhookDeliveryEvent.tenant_id == current_user.tenant_id,
        )
    )
    total = count_result.scalar()

    # Get paginated results - verify tenant via webhook subscription
    result = await db.execute(
        select(WebhookDeliveryEvent)
        .where(
            WebhookDeliveryEvent.webhook_subscription_id == webhook_id,
            WebhookDeliveryEvent.tenant_id == current_user.tenant_id,
        )
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
        .order_by(WebhookDeliveryEvent.created_at.desc())
    )
    deliveries = list(result.scalars().all())

    has_more = (pagination.page * pagination.page_size) < total

    return {
        "items": [WebhookDeliveryEventResponse.model_validate(d) for d in deliveries],
        "total": total,
        "page": pagination.page,
        "page_size": pagination.page_size,
        "has_more": has_more,
    }


@router.post("/webhooks/deliveries/{delivery_id}/retry", response_model=WebhookDeliveryEventResponse)
async def retry_webhook_delivery(
    delivery_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retry one failed webhook delivery and preserve the updated evidence."""
    try:
        return await WebhookService(db).retry_delivery(delivery_id, current_user.tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# =============================================================================
# Outbox Event Endpoints
# =============================================================================


@router.get("/outbox/events", response_model=dict)
async def list_outbox_events(
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List outbox events for the current tenant.

    Args:
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of outbox events
    """
    from sqlalchemy import select

    # Count total
    count_result = await db.execute(
        select(func.count(OutboxEvent.id)).where(
            OutboxEvent.tenant_id == current_user.tenant_id,
            OutboxEvent.deleted_at.is_(None),
        )
    )
    total = count_result.scalar()

    # Get paginated results
    result = await db.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.tenant_id == current_user.tenant_id,
            OutboxEvent.deleted_at.is_(None),
        )
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
        .order_by(OutboxEvent.created_at.desc())
    )
    events = list(result.scalars().all())

    has_more = (pagination.page * pagination.page_size) < total

    return {
        "items": [OutboxEventResponse.model_validate(e) for e in events],
        "total": total,
        "page": pagination.page,
        "page_size": pagination.page_size,
        "has_more": has_more,
    }


@router.post("/outbox/events", response_model=OutboxEventResponse, status_code=201)
async def create_outbox_event(
    data: OutboxEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new outbox event.

    Args:
        data: Outbox event creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created outbox event
    """
    service = OutboxService(db)
    event = await service.create_event(
        tenant_id=current_user.tenant_id,
        aggregate_type=data.aggregate_type,
        aggregate_id=data.aggregate_id,
        event_type=data.event_type,
        payload=data.payload,
    )
    return OutboxEventResponse.model_validate(event)


@router.post("/outbox/events/{event_id}/retry", response_model=OutboxEventResponse)
async def retry_outbox_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return one failed outbox event to the publish queue."""
    try:
        return await OutboxService(db).retry_event(event_id, current_user.tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/outbox/publish")
async def publish_outbox_events(
    batch_size: int = Query(default=100, ge=1, le=500, description="Batch size"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger outbox event publishing.

    This endpoint is typically called by a worker process to publish
    pending outbox events to their destinations.

    Args:
        batch_size: Number of events to process
        db: Database session
        current_user: Current authenticated user

    Returns:
        Publishing results
    """
    service = OutboxService(db)
    result = await service.publish_pending_events(batch_size=batch_size)
    return result


# Import func for count queries
from sqlalchemy import func
