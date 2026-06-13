"""Outbox Event Worker Jobs

Job functions for processing outbox events with reliable delivery,
distributed locking, retry logic, and dead letter queue support.
"""

import json
import logfire
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, and_

from app.db.session import AsyncSessionLocal
from app.services.cache_service import acquire_lock, release_lock
from app.domains.integrations.models import (
    OutboxEvent,
    OutboxEventStatus,
    WebhookSubscription,
)


# Maximum events to process per batch
OUTBOX_BATCH_SIZE = 50

# Lock timeout for processing a single event (seconds)
OUTBOX_LOCK_TIMEOUT = 30

# Lock TTL (seconds)
OUTBOX_LOCK_TTL = 60


async def process_outbox_event(ctx: dict, event_id: str) -> dict[str, Any]:
    """Process a single outbox event with distributed locking.

    Implements at-least-once delivery semantics by:
    1. Acquiring a distributed lock to prevent duplicate processing
    2. Querying the event by ID (status='pending', attempts < max_attempts)
    3. Attempting delivery via webhook
    4. Marking as published on success
    5. Incrementing attempts on failure
    6. Moving to DLQ after max attempts exceeded

    Args:
        ctx: ARQ context dict containing redis connection
        event_id: UUID of the outbox event to process

    Returns:
        Dict with processing result
    """
    logfire.info(f"Processing outbox event: {event_id}")

    # Validate event_id format
    try:
        event_uuid = UUID(event_id)
    except (ValueError, TypeError):
        logfire.error(f"Invalid event ID format: {event_id}")
        return {"success": False, "error": "Invalid event ID format"}

    async with AsyncSessionLocal() as db:
        # Query the event with row-level lock
        result = await db.execute(
            select(OutboxEvent).where(
                and_(
                    OutboxEvent.id == event_uuid,
                    OutboxEvent.deleted_at.is_(None),
                )
            ).with_for_update(skip_locked=True)
        )
        event = result.scalar_one_or_none()

        if not event:
            logfire.warning(f"Outbox event not found: {event_id}")
            return {"success": False, "error": "Event not found"}

        # Check if already published
        if event.status == OutboxEventStatus.PUBLISHED.value:
            logfire.info(f"Event already published: {event_id}")
            return {"success": True, "error": "Already published", "skipped": True}

        # Check if max attempts exceeded
        if event.attempts >= event.max_attempts:
            logfire.warning(
                f"Event exceeded max attempts: {event_id}",
                attempts=event.attempts,
                max_attempts=event.max_attempts,
            )
            # Move to DLQ
            await _move_event_to_dlq(ctx, event, "Max attempts exceeded")
            # Mark as failed
            event.status = OutboxEventStatus.FAILED.value
            await db.commit()
            return {
                "success": False,
                "error": "Max attempts exceeded",
                "event_id": event_id,
                "attempts": event.attempts,
                "moved_to_dlq": True,
            }

        # Acquire distributed lock to prevent duplicate processing
        lock_acquired = False
        lock_key = f"outbox_event:{event_id}"

        try:
            lock_acquired = await acquire_lock(
                lock_name=lock_key,
                tenant_id=str(event.tenant_id) if event.tenant_id else "system",
                timeout=OUTBOX_LOCK_TIMEOUT,
                ttl=OUTBOX_LOCK_TTL,
            )
        except Exception as e:
            logfire.warning(f"Failed to acquire lock for event {event_id}: {e}")

        if not lock_acquired:
            logfire.info(f"Could not acquire lock, event may be processing elsewhere: {event_id}")
            return {"success": False, "error": "Could not acquire lock", "retry_later": True}

        try:
            # Increment attempts
            event.attempts += 1
            await db.commit()

            # Attempt delivery
            delivery_result = await _deliver_outbox_event(event, db)

            if delivery_result["success"]:
                # Mark as published
                event.status = OutboxEventStatus.PUBLISHED.value
                event.published = True
                event.published_at = datetime.now(timezone.utc)
                event.last_error = None
                await db.commit()

                logfire.info(f"Outbox event published successfully: {event_id}")
                return {
                    "success": True,
                    "event_id": event_id,
                    "attempts": event.attempts,
                    "delivery_result": delivery_result,
                }
            else:
                # Increment failed attempts
                event.last_error = delivery_result.get("error", "Delivery failed")

                # Check if we should retry or move to DLQ
                if event.attempts >= event.max_attempts:
                    await _move_event_to_dlq(ctx, event, event.last_error)
                    event.status = OutboxEventStatus.FAILED.value
                    await db.commit()

                    logfire.warning(
                        f"Outbox event moved to DLQ after {event.attempts} attempts: {event_id}",
                        error=event.last_error,
                    )
                    return {
                        "success": False,
                        "error": event.last_error,
                        "event_id": event_id,
                        "attempts": event.attempts,
                        "moved_to_dlq": True,
                    }
                else:
                    # Keep as pending for retry
                    await db.commit()

                    logfire.warning(
                        f"Outbox event delivery failed, will retry: {event_id}",
                        error=event.last_error,
                        attempts=event.attempts,
                        max_attempts=event.max_attempts,
                    )
                    return {
                        "success": False,
                        "error": event.last_error,
                        "event_id": event_id,
                        "attempts": event.attempts,
                        "max_attempts": event.max_attempts,
                        "retry_later": True,
                    }

        finally:
            # Always release the lock
            try:
                await release_lock(
                    lock_name=lock_key,
                    tenant_id=str(event.tenant_id) if event.tenant_id else "system",
                )
            except Exception as e:
                logfire.warning(f"Failed to release lock for event {event_id}: {e}")


async def _deliver_outbox_event(event: OutboxEvent, db) -> dict[str, Any]:
    """Deliver an outbox event to webhook subscriptions.

    Args:
        event: OutboxEvent to deliver
        db: Database session

    Returns:
        Dict with delivery result
    """
    # Find active webhook subscriptions for this tenant
    if event.tenant_id:
        result = await db.execute(
            select(WebhookSubscription).where(
                and_(
                    WebhookSubscription.tenant_id == event.tenant_id,
                    WebhookSubscription.deleted_at.is_(None),
                    WebhookSubscription.is_active == True,
                )
            )
        )
        subscriptions = list(result.scalars().all())
    else:
        subscriptions = []

    if not subscriptions:
        logfire.info(f"No subscriptions for tenant {event.tenant_id}, marking as delivered")
        return {"success": True, "skipped": True, "reason": "No subscriptions"}

    # Build event payload
    event_payload = {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": str(event.aggregate_id),
        "payload": event.payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenant_id": str(event.tenant_id) if event.tenant_id else None,
    }

    # Attempt delivery to each subscription
    all_succeeded = True
    last_error = None

    for subscription in subscriptions:
        try:
            success = await _deliver_to_subscription(subscription, event_payload, db)
            if not success:
                all_succeeded = False
                # Get last error from subscription delivery
                last_error = f"Delivery to subscription {subscription.id} failed"
        except Exception as e:
            all_succeeded = False
            last_error = str(e)

    if all_succeeded:
        return {"success": True, "subscriptions_count": len(subscriptions)}
    else:
        return {"success": False, "error": last_error}


async def _deliver_to_subscription(
    subscription: WebhookSubscription,
    payload: dict[str, Any],
    db,
) -> bool:
    """Deliver event payload to a specific webhook subscription.

    Args:
        subscription: WebhookSubscription to deliver to
        payload: Event payload
        db: Database session

    Returns:
        True if delivery succeeded, False otherwise
    """
    import hashlib
    import hmac
    import httpx

    # Create signature if secret is configured
    headers = {"Content-Type": "application/json"}
    if subscription.secret:
        import json as json_lib
        body_json = json_lib.dumps(payload, separators=(",", ":"))
        signature = hmac.new(
            subscription.secret.encode(),
            body_json.encode(),
            hashlib.sha256,
        ).hexdigest()
        headers["X-Webhook-Signature"] = f"sha256={signature}"
        headers["X-Webhook-Event-ID"] = payload.get("event_id", "")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                subscription.url,
                json=payload,
                headers=headers,
            )

        # 2xx responses are success
        if 200 <= response.status_code < 300:
            return True

        # 4xx responses are client errors, don't retry
        if 400 <= response.status_code < 500:
            logfire.warning(
                f"Webhook delivery client error: {subscription.id}",
                status=response.status_code,
            )
            return False

        # 5xx are server errors, should retry
        logfire.warning(
            f"Webhook delivery server error: {subscription.id}",
            status=response.status_code,
        )
        return False

    except Exception as e:
        logfire.error(f"Webhook delivery exception: {subscription.id}", error=str(e))
        return False


async def _move_event_to_dlq(ctx: dict, event: OutboxEvent, error: str) -> None:
    """Move a failed outbox event to the dead letter queue.

    Args:
        ctx: ARQ context dict
        event: Failed outbox event
        error: Error message from the failure
    """
    redis = ctx.get("redis")
    if not redis:
        logfire.warning("Redis not available for DLQ")
        return

    dlq_key = "outbox:dlq"
    dlq_entry = {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": str(event.aggregate_id),
        "tenant_id": str(event.tenant_id) if event.tenant_id else None,
        "payload": event.payload,
        "attempts": event.attempts,
        "error": error,
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }

    await redis.rpush(dlq_key, json.dumps(dlq_entry))
    logfire.info(f"Moved outbox event to DLQ: {event.id}")


async def get_outbox_dlq_entries(ctx: dict, limit: int = 100) -> list[dict[str, Any]]:
    """Get entries from the outbox dead letter queue.

    Args:
        ctx: ARQ context dict
        limit: Maximum number of entries to return

    Returns:
        List of DLQ entries
    """
    redis = ctx.get("redis")
    if not redis:
        return []

    dlq_key = "outbox:dlq"
    entries = await redis.lrange(dlq_key, 0, limit - 1)

    return [json.loads(entry) for entry in entries]


async def retry_outbox_event_from_dlq(ctx: dict, event_id: str) -> dict[str, Any]:
    """Retry a failed outbox event from the DLQ.

    Resets the event status and re-enqueues it for processing.

    Args:
        ctx: ARQ context dict
        event_id: UUID of the outbox event to retry

    Returns:
        Dict with retry result
    """
    logfire.info(f"Retrying outbox event from DLQ: {event_id}")

    try:
        event_uuid = UUID(event_id)
    except (ValueError, TypeError):
        return {"success": False, "error": "Invalid event ID format"}

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OutboxEvent).where(OutboxEvent.id == event_uuid)
        )
        event = result.scalar_one_or_none()

        if not event:
            return {"success": False, "error": "Event not found"}

        # Reset event status for retry
        event.status = OutboxEventStatus.PENDING.value
        event.attempts = 0
        event.last_error = None
        await db.commit()

        # Remove from DLQ if present
        redis = ctx.get("redis")
        if redis:
            dlq_key = "outbox:dlq"
            entries = await redis.lrange(dlq_key, 0, -1)
            for entry in entries:
                parsed = json.loads(entry)
                if parsed.get("event_id") == event_id:
                    await redis.lrem(dlq_key, 1, entry)
                    break

        # Enqueue for processing
        if redis:
            from arq import enqueue_job
            await enqueue_job(
                "process_outbox_event",
                event_id,
                redis=redis,
            )
            logfire.info(f"Re-enqueued outbox event for processing: {event_id}")

        return {
            "success": True,
            "event_id": event_id,
            "message": "Event re-enqueued for processing",
        }