"""Webhook and Outbox Worker Jobs

Job functions for webhook delivery with retry logic and outbox event publishing.
Implements exponential backoff, signature verification, and dead letter queue.
"""

import asyncio
import hashlib
import hmac
import json
import logfire
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select

from app.core.settings import settings
from app.db.session import AsyncSessionLocal
from app.domains.integrations.models import (
    WebhookSubscription,
    WebhookDeliveryEvent,
    OutboxEvent,
)
from app.domains.integrations.service import WebhookService


# Exponential backoff delays in seconds for webhook delivery (5s/30s/120s)
WEBHOOK_BACKOFF_DELAYS = [5, 30, 120]
MAX_DELIVERY_ATTEMPTS = 3

# DLQ key for failed webhook deliveries
WEBHOOK_DLQ_KEY = "webhook:dlq"


async def deliver_webhook_job(ctx: dict, subscription_id: str, event_payload: dict) -> dict[str, Any]:
    """Deliver a webhook with retry logic.

    Implements HMAC-SHA256 signature verification, exponential backoff,
    and records delivery events for auditing.

    Args:
        ctx: ARQ context dict containing redis connection
        subscription_id: UUID of the webhook subscription
        event_payload: Event data to deliver

    Returns:
        Dict with delivery result
    """
    logfire.info(f"Delivering webhook: {subscription_id}")

    async with AsyncSessionLocal() as db:
        # Get subscription
        result = await db.execute(
            select(WebhookSubscription).where(WebhookSubscription.id == UUID(subscription_id))
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            logfire.error(f"Subscription not found: {subscription_id}")
            return {"success": False, "error": "Subscription not found"}

        if not subscription.is_active:
            logfire.warning(f"Subscription inactive: {subscription_id}")
            return {"success": False, "error": "Subscription inactive"}

        # Create delivery event
        delivery = WebhookDeliveryEvent(
            tenant_id=subscription.tenant_id,
            webhook_subscription_id=subscription.id,
            event_id=event_payload.get("event_id", str(UUID.uuid4())),
            url=subscription.url,
            request_headers={"Content-Type": "application/json"},
            request_body=event_payload,
            attempts=1,
        )
        db.add(delivery)
        await db.flush()
        await db.refresh(delivery)

        # Attempt delivery with retries
        success = await _attempt_webhook_delivery(subscription, event_payload, delivery, db)

        if success:
            delivery.response_status = 200
            delivery.delivered_at = datetime.now(timezone.utc)
            delivery.error_message = None
            await db.commit()

            logfire.info(f"Webhook delivered successfully: {subscription_id}")
            return {"success": True, "delivery_id": str(delivery.id)}
        else:
            await db.commit()
            # If exhausted retries, the delivery event records the failure
            logfire.warning(f"Webhook delivery failed after all retries: {subscription_id}")
            return {
                "success": False,
                "delivery_id": str(delivery.id),
                "error": delivery.error_message or "Max retries exceeded",
                "attempts": delivery.attempts,
            }


async def deliver_webhook_with_retry(ctx: dict, delivery_id: str) -> dict[str, Any]:
    """ARQ job for webhook delivery with exponential backoff retry.

    This job implements automatic retry with exponential backoff (5s/30s/120s)
    and moves failed deliveries to DLQ after 3 attempts exhausted.

    Uses ARQ's built-in retry mechanism with max_retries=2 (total 3 attempts).

    Args:
        ctx: ARQ context dict containing redis connection and job info
        delivery_id: UUID of the WebhookDeliveryEvent to deliver

    Returns:
        Dict with delivery result
    """
    # ARQ passes job_id, max_retries, retry_times in ctx for retry handling
    job_id = ctx.get("job_id")
    retry_times = ctx.get("retry_times", [])

    logfire.info(f"Delivering webhook with retry: {delivery_id}", retry_count=len(retry_times))

    async with AsyncSessionLocal() as db:
        # Get delivery event
        result = await db.execute(
            select(WebhookDeliveryEvent).where(WebhookDeliveryEvent.id == UUID(delivery_id))
        )
        delivery = result.scalar_one_or_none()

        if not delivery:
            logfire.error(f"Delivery event not found: {delivery_id}")
            return {"success": False, "error": "Delivery event not found"}

        # Check if already delivered
        if delivery.delivered_at:
            logfire.info(f"Delivery already successful: {delivery_id}")
            return {"success": True, "delivery_id": delivery_id}

        # Get subscription
        result = await db.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.id == delivery.webhook_subscription_id
            )
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            logfire.error(f"Subscription not found for delivery: {delivery_id}")
            return {"success": False, "error": "Subscription not found"}

        if not subscription.is_active:
            logfire.warning(f"Subscription inactive: {subscription.id}")
            delivery.error_message = "Subscription inactive"
            await db.commit()
            return {"success": False, "error": "Subscription inactive"}

        # Increment attempts
        delivery.attempts = len(retry_times) + 1

        # Build headers with HMAC-SHA256 signature
        headers = {"Content-Type": "application/json"}
        if subscription.secret:
            body_json = json.dumps(delivery.request_body or {}, separators=(",", ":"))
            signature = hmac.new(
                subscription.secret.encode(),
                body_json.encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Signature"] = f"sha256={signature}"

        # Attempt delivery
        last_error = None
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    subscription.url,
                    json=delivery.request_body or {},
                    headers=headers,
                )

            delivery.response_status = response.status_code
            delivery.response_body = response.text[:5000] if response.text else None

            if 200 <= response.status_code < 300:
                delivery.delivered_at = datetime.now(timezone.utc)
                delivery.error_message = None
                await db.commit()
                logfire.info(f"Webhook delivered successfully: {delivery_id}")
                return {"success": True, "delivery_id": delivery_id}

            last_error = f"HTTP {response.status_code}: {response.text[:500]}"
            delivery.error_message = last_error

            # Don't retry client errors (4xx)
            if 400 <= response.status_code < 500:
                await db.commit()
                return {
                    "success": False,
                    "delivery_id": delivery_id,
                    "error": last_error,
                    "attempts": delivery.attempts,
                }

        except Exception as e:
            last_error = str(e)
            delivery.error_message = last_error
            delivery.response_status = None
            logfire.error(f"Webhook delivery exception: {delivery_id}", error=last_error)

        await db.commit()

        # Check if this was the last retry (ARQ max_retries exceeded)
        # ARQ passes (job_id, max_retries) so we can check if we're out of retries
        arq_max_retries = ctx.get("max_retries", 2)  # Default to 2 since total attempts = 3
        current_attempt = len(retry_times) + 1
        total_attempts = current_attempt + arq_max_retries

        if current_attempt > arq_max_retries:
            # All retries exhausted, move to DLQ
            logfire.warning(
                f"Webhook delivery failed after all retries, moving to DLQ: {delivery_id}",
                attempts=delivery.attempts,
                error=last_error,
            )
            await _move_webhook_to_dlq(ctx, delivery, subscription, last_error)
            return {
                "success": False,
                "delivery_id": delivery_id,
                "error": last_error or "Max retries exceeded",
                "attempts": delivery.attempts,
                "moved_to_dlq": True,
            }

        # Return failure to trigger ARQ retry with backoff
        return {
            "success": False,
            "delivery_id": delivery_id,
            "error": last_error or "Delivery failed",
            "attempts": delivery.attempts,
        }


async def _move_webhook_to_dlq(
    ctx: dict,
    delivery: WebhookDeliveryEvent,
    subscription: WebhookSubscription,
    error: str,
) -> None:
    """Move a failed webhook delivery to the dead letter queue.

    Args:
        ctx: ARQ context dict
        delivery: Failed WebhookDeliveryEvent
        subscription: WebhookSubscription (for context)
        error: Error message from the failure
    """
    redis = ctx.get("redis")
    if not redis:
        logfire.warning("Redis not available for webhook DLQ")
        return

    dlq_entry = {
        "delivery_id": str(delivery.id),
        "webhook_subscription_id": str(delivery.webhook_subscription_id),
        "tenant_id": str(delivery.tenant_id) if delivery.tenant_id else None,
        "event_id": delivery.event_id,
        "url": delivery.url,
        "request_body": delivery.request_body,
        "attempts": delivery.attempts,
        "error": error,
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }

    await redis.rpush(WEBHOOK_DLQ_KEY, json.dumps(dlq_entry))
    logfire.info(f"Moved webhook delivery to DLQ: {delivery.id}")


async def get_webhook_dlq_entries(ctx: dict, limit: int = 100) -> list[dict[str, Any]]:
    """Get entries from the webhook dead letter queue.

    Args:
        ctx: ARQ context dict
        limit: Maximum number of entries to return

    Returns:
        List of DLQ entries
    """
    redis = ctx.get("redis")
    if not redis:
        return []

    entries = await redis.lrange(WEBHOOK_DLQ_KEY, 0, limit - 1)
    return [json.loads(entry) for entry in entries]


async def _attempt_webhook_delivery(
    subscription: WebhookSubscription,
    payload: dict[str, Any],
    delivery: WebhookDeliveryEvent,
    db,
) -> bool:
    """Attempt to deliver webhook with signature and retries.

    Args:
        subscription: WebhookSubscription
        payload: Event payload
        delivery: WebhookDeliveryEvent to track result
        db: Database session

    Returns:
        True if delivery succeeded, False otherwise
    """
    # Create signature if secret is configured
    headers = {"Content-Type": "application/json"}
    if subscription.secret:
        body_json = json.dumps(payload, separators=(",", ":"))
        signature = hmac.new(
            subscription.secret.encode(),
            body_json.encode(),
            hashlib.sha256,
        ).hexdigest()
        headers["X-Signature"] = f"sha256={signature}"
        headers["X-Webhook-Event-ID"] = payload.get("event_id", "")

    attempt = 0
    last_error = None

    while attempt < MAX_DELIVERY_ATTEMPTS:
        attempt += 1
        delivery.attempts = attempt

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    subscription.url,
                    json=payload,
                    headers=headers,
                )

            delivery.response_status = response.status_code
            delivery.response_body = response.text[:5000] if response.text else None

            if 200 <= response.status_code < 300:
                return True

            last_error = f"HTTP {response.status_code}: {response.text[:500]}"

            # Don't retry client errors (4xx)
            if 400 <= response.status_code < 500:
                delivery.error_message = last_error
                return False

        except Exception as e:
            last_error = str(e)
            delivery.error_message = last_error
            delivery.response_status = None

        # Exponential backoff before retry
        if attempt < MAX_DELIVERY_ATTEMPTS:
            delay = WEBHOOK_BACKOFF_DELAYS[min(attempt - 1, len(WEBHOOK_BACKOFF_DELAYS) - 1)]
            logfire.info(f"Retrying webhook in {delay}s: {subscription.id}", attempt=attempt)
            await asyncio.sleep(delay)

    delivery.error_message = last_error or "Max retries exceeded"
    return False


async def publish_outbox_job(ctx: dict) -> dict[str, Any]:
    """Publish pending outbox events.

    Processes pending outbox events and delivers them to the
    appropriate webhook subscriptions via the deliver_webhook_job.

    NOTE: Events are only marked as published AFTER successful delivery
    confirmation from the delivery job, not after enqueueing. This ensures
    no data loss if delivery fails after the job is enqueued.

    Args:
        ctx: ARQ context dict containing redis connection

    Returns:
        Dict with publishing results
    """
    logfire.info("Publishing pending outbox events")

    async with AsyncSessionLocal() as db:
        # Get pending events
        result = await db.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.published == False,
                OutboxEvent.deleted_at.is_(None),
            )
            .limit(100)
            .order_by(OutboxEvent.created_at.asc())
        )
        pending_events = list(result.scalars().all())

        if not pending_events:
            logfire.info("No pending outbox events")
            return {"processed": 0, "published": 0, "failed": 0}

        published_count = 0
        failed_count = 0

        for event in pending_events:
            try:
                # Find active webhook subscriptions for this tenant
                subscriptions_result = await db.execute(
                    select(WebhookSubscription).where(
                        WebhookSubscription.tenant_id == event.tenant_id,
                        WebhookSubscription.deleted_at.is_(None),
                        WebhookSubscription.is_active == True,
                    )
                )
                subscriptions = list(subscriptions_result.scalars().all())

                if not subscriptions:
                    logfire.info(f"No subscriptions for tenant: {event.tenant_id}")
                    # Mark as published anyway since there's no destination
                    event.published = True
                    event.published_at = datetime.now(timezone.utc)
                    await db.commit()
                    published_count += 1
                    continue

                # Track overall delivery success for this event
                all_delivered = True
                delivery_error = None

                # Deliver to all matching subscriptions and wait for result
                for sub in subscriptions:
                    event_payload = {
                        "event_id": str(event.id),
                        "event_type": event.event_type,
                        "aggregate_type": event.aggregate_type,
                        "aggregate_id": str(event.aggregate_id),
                        "payload": event.payload,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "tenant_id": str(event.tenant_id),
                    }

                    # Enqueue webhook delivery job and wait for result
                    redis = ctx.get("redis")
                    if redis:
                        from arq import enqueue_job

                        job = await enqueue_job(
                            "deliver_webhook_job",
                            str(sub.id),
                            event_payload,
                            redis=redis,
                        )
                        logfire.info(f"Enqueued webhook delivery: {sub.id}")

                        # Wait for job completion to confirm delivery
                        # This ensures we only mark published after delivery succeeds
                        result = await job.result(timeout=60)
                        if not result or not result.get("success"):
                            all_delivered = False
                            delivery_error = result.get("error") if result else "No result"
                    else:
                        # No redis means we can't track delivery, fail safe
                        all_delivered = False
                        delivery_error = "Redis not available"

                # Only mark as published AFTER all deliveries confirmed successful
                # If any delivery failed, keep event as pending for retry
                if all_delivered:
                    event.published = True
                    event.published_at = datetime.now(timezone.utc)
                    await db.commit()
                    published_count += 1
                    logfire.info(f"Outbox event published: {event.id}")
                else:
                    # Log failure but don't mark as published
                    logfire.warning(
                        f"Outbox event delivery failed: {event.id}",
                        error=delivery_error,
                    )
                    failed_count += 1

            except Exception as e:
                logfire.error(f"Failed to publish outbox event: {event.id}", error=str(e))
                failed_count += 1
                await db.rollback()

        logfire.info(
            f"Outbox publishing complete",
            processed=len(pending_events),
            published=published_count,
            failed=failed_count,
        )

        return {
            "processed": len(pending_events),
            "published": published_count,
            "failed": failed_count,
        }


async def retry_webhook_delivery(ctx: dict, delivery_id: str) -> dict[str, Any]:
    """Retry a failed webhook delivery.

    Specifically handles manual retry requests for failed deliveries,
    bypassing the normal retry mechanism but still respecting max_retries.

    Args:
        ctx: ARQ context dict containing redis connection
        delivery_id: UUID of the delivery event to retry

    Returns:
        Dict with retry result
    """
    logfire.info(f"Retrying webhook delivery: {delivery_id}")

    async with AsyncSessionLocal() as db:
        # Get delivery event
        result = await db.execute(
            select(WebhookDeliveryEvent).where(WebhookDeliveryEvent.id == UUID(delivery_id))
        )
        delivery = result.scalar_one_or_none()

        if not delivery:
            return {"success": False, "error": "Delivery event not found"}

        # Check if already successful
        if delivery.delivered_at:
            return {
                "success": False,
                "error": "Delivery already successful",
                "delivery_id": delivery_id,
            }

        # Get subscription
        result = await db.execute(
            select(WebhookSubscription).where(WebhookSubscription.id == delivery.webhook_subscription_id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            return {"success": False, "error": "Subscription not found"}

        # Attempt delivery again
        success = await _attempt_webhook_delivery(
            subscription,
            delivery.request_body or {},
            delivery,
            db,
        )

        if success:
            delivery.delivered_at = datetime.now(timezone.utc)
            delivery.error_message = None
            await db.commit()

            return {"success": True, "delivery_id": delivery_id}
        else:
            await db.commit()

            return {
                "success": False,
                "delivery_id": delivery_id,
                "error": delivery.error_message or "Retry failed",
                "attempts": delivery.attempts,
            }


# Helper functions for job queue management


async def enqueue_webhook_delivery(
    ctx: dict,
    subscription_id: str,
    event_payload: dict,
) -> None:
    """Enqueue a webhook delivery job.

    Args:
        ctx: ARQ context dict
        subscription_id: UUID of the subscription
        event_payload: Event data to deliver
    """
    redis = ctx.get("redis")
    if not redis:
        logfire.error("Redis not available for enqueuing")
        return

    from arq import enqueue_job

    try:
        await enqueue_job(
            "deliver_webhook_job",
            subscription_id,
            event_payload,
            redis=redis,
        )
        logfire.info(f"Enqueued webhook delivery: {subscription_id}")
    except Exception as e:
        logfire.error(f"Failed to enqueue webhook delivery: {subscription_id}", error=str(e))


async def enqueue_outbox_publishing(ctx: dict) -> None:
    """Enqueue an outbox publishing job.

    Args:
        ctx: ARQ context dict
    """
    redis = ctx.get("redis")
    if not redis:
        logfire.error("Redis not available for enqueuing")
        return

    from arq import enqueue_job

    try:
        await enqueue_job(
            "publish_outbox_job",
            redis=redis,
        )
        logfire.info("Enqueued outbox publishing job")
    except Exception as e:
        logfire.error(f"Failed to enqueue outbox publishing", error=str(e))