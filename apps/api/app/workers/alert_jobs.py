"""Alert System Background Worker Jobs

Job functions for evaluating alert rules and sending notifications
via configured channels. Supports quota, provider health, circuit breaker,
agent run failure, and cache hit rate conditions.
"""

import asyncio
import json
import logfire
from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select, func, and_, or_

from app.db.session import AsyncSessionLocal
from app.domains.ops.models import AlertRule, MetricEvent, NotificationEvent, QuotaUsage
from app.services.quota_service import QuotaType
from app.services.cache_service import CacheService
from app.services.circuit_breaker import get_provider_circuit_breaker, CircuitState


# Condition types
CONDITION_QUOTA = "quota"
CONDITION_PROVIDER_HEALTH = "provider_health"
CONDITION_CIRCUIT_OPEN = "circuit_open"
CONDITION_AGENT_FAILURE_RATE = "agent_failure_rate"
CONDITION_CACHE_HIT_RATE = "cache_hit_rate"

# Operators
OPERATOR_GT = ">"
OPERATOR_LT = "<"
OPERATOR_GTE = ">="
OPERATOR_LTE = "<="


async def evaluate_alert_rules(ctx: dict) -> dict[str, Any]:
    """Evaluate all active alert rules.

    Iterates through all active alert rules and evaluates their conditions,
    sending notifications when thresholds are breached.

    Args:
        ctx: ARQ context dict containing redis connection

    Returns:
        Dict with evaluation results
    """
    logfire.info("Starting alert rule evaluation")

    async with AsyncSessionLocal() as db:
        # Get all active alert rules
        result = await db.execute(
            select(AlertRule).where(AlertRule.is_active == True)
        )
        rules = list(result.scalars().all())

        if not rules:
            logfire.info("No active alert rules to evaluate")
            return {"evaluated": 0, "triggered": 0, "errors": 0}

        triggered_count = 0
        error_count = 0

        for rule in rules:
            try:
                triggered = await evaluate_single_rule(ctx, str(rule.id))
                if triggered:
                    triggered_count += 1
            except Exception as e:
                logfire.error(f"Error evaluating rule {rule.id}: {e}")
                error_count += 1

        logfire.info(
            f"Alert rule evaluation complete",
            evaluated=len(rules),
            triggered=triggered_count,
            errors=error_count,
        )

        return {
            "evaluated": len(rules),
            "triggered": triggered_count,
            "errors": error_count,
        }


async def evaluate_single_rule(ctx: dict, rule_id: str) -> bool:
    """Evaluate a single alert rule and send notification if triggered.

    Args:
        ctx: ARQ context dict containing redis connection
        rule_id: UUID string of the alert rule to evaluate

    Returns:
        True if alert was triggered, False otherwise
    """
    logfire.info(f"Evaluating alert rule: {rule_id}")

    async with AsyncSessionLocal() as db:
        # Get the alert rule
        result = await db.execute(
            select(AlertRule).where(AlertRule.id == UUID(rule_id))
        )
        rule = result.scalar_one_or_none()

        if not rule:
            logfire.error(f"Alert rule not found: {rule_id}")
            return False

        if not rule.is_active:
            logfire.info(f"Alert rule is inactive: {rule_id}")
            return False

        # Evaluate condition
        condition = rule.condition_json or {}
        triggered, alert_data = await _evaluate_condition(condition, rule.tenant_id, db)

        if triggered:
            logfire.warning(
                f"Alert rule triggered: {rule.name}",
                rule_id=rule_id,
                condition=condition,
                alert_data=alert_data,
            )

            # Send notifications
            await send_alert_notification(ctx, rule_id, alert_data)
            return True

        logfire.debug(f"Alert rule not triggered: {rule.name}", rule_id=rule_id)
        return False


async def _evaluate_condition(
    condition: dict[str, Any],
    tenant_id: UUID,
    db,
) -> tuple[bool, dict[str, Any]]:
    """Evaluate an alert condition.

    Supports:
    - quota: Quota threshold exceeded (e.g., > 80%, > 90%, > 100%)
    - provider_health: Provider error rate > threshold
    - circuit_open: Provider circuit breaker is open
    - agent_failure_rate: Agent run failure rate > threshold
    - cache_hit_rate: Cache hit rate < threshold

    Args:
        condition: Condition configuration dict
        tenant_id: Tenant UUID
        db: Database session

    Returns:
        Tuple of (triggered: bool, alert_data: dict)
    """
    condition_type = condition.get("condition_type")
    metric_name = condition.get("metric_name")
    operator = condition.get("operator", OPERATOR_GT)
    threshold = float(condition.get("threshold", 0))

    if condition_type == CONDITION_QUOTA:
        return await _evaluate_quota_condition(condition, tenant_id, db)
    elif condition_type == CONDITION_PROVIDER_HEALTH:
        return await _evaluate_provider_health_condition(condition, db)
    elif condition_type == CONDITION_CIRCUIT_OPEN:
        return await _evaluate_circuit_open_condition(condition, db)
    elif condition_type == CONDITION_AGENT_FAILURE_RATE:
        return await _evaluate_agent_failure_rate_condition(condition, tenant_id, db)
    elif condition_type == CONDITION_CACHE_HIT_RATE:
        return await _evaluate_cache_hit_rate_condition(condition, db)
    else:
        # Try to evaluate from metric_events table with generic approach
        return await _evaluate_generic_metric_condition(condition, tenant_id, db)


async def _evaluate_quota_condition(
    condition: dict[str, Any],
    tenant_id: UUID,
    db,
) -> tuple[bool, dict[str, Any]]:
    """Evaluate quota threshold condition.

    Args:
        condition: Condition with quota_type and threshold
        tenant_id: Tenant UUID
        db: Database session

    Returns:
        Tuple of (triggered, alert_data)
    """
    quota_type = condition.get("quota_type")
    operator = condition.get("operator", OPERATOR_GT)
    threshold_percent = float(condition.get("threshold", 80))  # Default 80%

    if not quota_type:
        return False, {}

    # Get quota usage
    result = await db.execute(
        select(QuotaUsage).where(
            and_(
                QuotaUsage.tenant_id == tenant_id,
                QuotaUsage.quota_type == quota_type,
            )
        )
    )
    quota = result.scalar_one_or_none()

    if not quota or quota.limit_amount == 0:
        return False, {}

    usage_percent = (quota.used_amount / quota.limit_amount) * 100

    triggered = _compare_values(usage_percent, operator, threshold_percent)

    alert_data = {
        "quota_type": quota_type,
        "used_amount": quota.used_amount,
        "limit_amount": quota.limit_amount,
        "usage_percent": round(usage_percent, 2),
        "threshold_percent": threshold_percent,
        "operator": operator,
        "message": f"Quota {quota_type} usage at {usage_percent:.1f}% (threshold: {threshold_percent}%)",
    }

    return triggered, alert_data


async def _evaluate_provider_health_condition(
    condition: dict[str, Any],
    db,
) -> tuple[bool, dict[str, Any]]:
    """Evaluate provider health (error rate) condition.

    Args:
        condition: Condition with provider_name and threshold (error rate %)
        db: Database session

    Returns:
        Tuple of (triggered, alert_data)
    """
    provider_name = condition.get("provider_name")
    error_threshold = float(condition.get("threshold", 10))  # Default 10%

    # Calculate error rate from metric events
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=15)

    # Get total calls and errors for provider
    total_query = select(func.count(MetricEvent.id)).where(
        and_(
            MetricEvent.metric_type == "provider",
            MetricEvent.metric_name == "call",
            MetricEvent.dimensions["provider_name"].astext == provider_name,
            MetricEvent.recorded_at >= window_start,
        )
    )
    total_result = await db.execute(total_query)
    total_calls = total_result.scalar_one_or_none() or 0

    error_query = select(func.count(MetricEvent.id)).where(
        and_(
            MetricEvent.metric_type == "error",
            MetricEvent.metric_name == "provider_error",
            MetricEvent.dimensions["provider_name"].astext == provider_name,
            MetricEvent.recorded_at >= window_start,
        )
    )
    error_result = await db.execute(error_query)
    total_errors = error_result.scalar_one_or_none() or 0

    if total_calls == 0:
        return False, {}

    error_rate = (total_errors / total_calls) * 100
    triggered = _compare_values(error_rate, OPERATOR_GT, error_threshold)

    alert_data = {
        "provider_name": provider_name,
        "error_rate": round(error_rate, 2),
        "total_calls": total_calls,
        "total_errors": total_errors,
        "threshold": error_threshold,
        "message": f"Provider {provider_name} error rate at {error_rate:.1f}% (threshold: {error_threshold}%)",
    }

    return triggered, alert_data


async def _evaluate_circuit_open_condition(
    condition: dict[str, Any],
    db,
) -> tuple[bool, dict[str, Any]]:
    """Evaluate circuit breaker open condition.

    Args:
        condition: Condition with provider_name
        db: Database session (unused, reads from circuit breaker state)

    Returns:
        Tuple of (triggered, alert_data)
    """
    provider_name = condition.get("provider_name")

    breaker_manager = get_provider_circuit_breaker()
    breaker = breaker_manager.get_breaker(provider_name)

    is_open = breaker.state == CircuitState.OPEN

    alert_data = {
        "provider_name": provider_name,
        "circuit_state": breaker.state.value,
        "failure_count": breaker._failure_count,
        "last_failure_time": breaker._last_failure_time,
        "message": f"Circuit breaker for {provider_name} is {breaker.state.value}",
    }

    return is_open, alert_data


async def _evaluate_agent_failure_rate_condition(
    condition: dict[str, Any],
    tenant_id: UUID,
    db,
) -> tuple[bool, dict[str, Any]]:
    """Evaluate agent run failure rate condition.

    Args:
        condition: Condition with agent_id (optional) and threshold
        tenant_id: Tenant UUID
        db: Database session

    Returns:
        Tuple of (triggered, alert_data)
    """
    agent_id = condition.get("agent_id")
    operator = condition.get("operator", OPERATOR_GT)
    failure_threshold = float(condition.get("threshold", 10))  # Default 10%

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=30)

    # Build query for agent runs
    base_filter = [
        MetricEvent.tenant_id == tenant_id,
        MetricEvent.metric_type == "agent",
        MetricEvent.recorded_at >= window_start,
    ]

    if agent_id:
        base_filter.append(MetricEvent.dimensions["agent_id"].astext == str(agent_id))

    # Get total runs
    total_query = select(func.count(MetricEvent.id)).where(
        and_(
            *base_filter,
            or_(
                MetricEvent.metric_name == "run",
                MetricEvent.metric_name == "run_completed",
                MetricEvent.metric_name == "run_failed",
                MetricEvent.metric_name == "run_cancelled",
            ),
        )
    )
    total_result = await db.execute(total_query)
    total_runs = total_result.scalar_one_or_none() or 0

    # Get failed runs
    failed_filter = base_filter + [
        MetricEvent.metric_name == "run_failed",
    ]
    failed_query = select(func.count(MetricEvent.id)).where(and_(*failed_filter))
    failed_result = await db.execute(failed_query)
    failed_runs = failed_result.scalar_one_or_none() or 0

    if total_runs == 0:
        return False, {}

    failure_rate = (failed_runs / total_runs) * 100
    triggered = _compare_values(failure_rate, operator, failure_threshold)

    alert_data = {
        "agent_id": agent_id or "all",
        "failure_rate": round(failure_rate, 2),
        "total_runs": total_runs,
        "failed_runs": failed_runs,
        "threshold": failure_threshold,
        "operator": operator,
        "message": f"Agent failure rate at {failure_rate:.1f}% (threshold: {failure_threshold}%)",
    }

    return triggered, alert_data


async def _evaluate_cache_hit_rate_condition(
    condition: dict[str, Any],
    db,
) -> tuple[bool, dict[str, Any]]:
    """Evaluate cache hit rate condition.

    Args:
        condition: Condition with threshold (as percentage)
        db: Database session

    Returns:
        Tuple of (triggered, alert_data)
    """
    hit_rate_threshold = float(condition.get("threshold", 80))  # Default 80%

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=15)

    # Get cache hits
    hits_query = select(func.count(MetricEvent.id)).where(
        and_(
            MetricEvent.metric_type == "cache",
            MetricEvent.metric_name == "hit",
            MetricEvent.recorded_at >= window_start,
        )
    )
    hits_result = await db.execute(hits_query)
    cache_hits = hits_result.scalar_one_or_none() or 0

    # Get cache misses
    misses_query = select(func.count(MetricEvent.id)).where(
        and_(
            MetricEvent.metric_type == "cache",
            MetricEvent.metric_name == "miss",
            MetricEvent.recorded_at >= window_start,
        )
    )
    misses_result = await db.execute(misses_query)
    cache_misses = misses_result.scalar_one_or_none() or 0

    total_requests = cache_hits + cache_misses
    if total_requests == 0:
        return False, {}

    hit_rate = (cache_hits / total_requests) * 100
    triggered = _compare_values(hit_rate, OPERATOR_LT, hit_rate_threshold)

    alert_data = {
        "hit_rate": round(hit_rate, 2),
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "total_requests": total_requests,
        "threshold": hit_rate_threshold,
        "message": f"Cache hit rate at {hit_rate:.1f}% (threshold: {hit_rate_threshold}%)",
    }

    return triggered, alert_data


async def _evaluate_generic_metric_condition(
    condition: dict[str, Any],
    tenant_id: UUID,
    db,
) -> tuple[bool, dict[str, Any]]:
    """Evaluate a generic metric condition from metric_events table.

    Args:
        condition: Condition with metric_type, metric_name, operator, threshold
        tenant_id: Tenant UUID
        db: Database session

    Returns:
        Tuple of (triggered, alert_data)
    """
    metric_type = condition.get("metric_type")
    metric_name = condition.get("metric_name")
    operator = condition.get("operator", OPERATOR_GT)
    threshold = float(condition.get("threshold", 0))

    if not metric_type or not metric_name:
        return False, {}

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=15)

    # Get average value for the metric
    avg_query = select(func.avg(MetricEvent.value)).where(
        and_(
            MetricEvent.tenant_id == tenant_id,
            MetricEvent.metric_type == metric_type,
            MetricEvent.metric_name == metric_name,
            MetricEvent.recorded_at >= window_start,
        )
    )
    result = await db.execute(avg_query)
    avg_value = result.scalar_one_or_none()

    if avg_value is None:
        return False, {}

    triggered = _compare_values(avg_value, operator, threshold)

    alert_data = {
        "metric_type": metric_type,
        "metric_name": metric_name,
        "current_value": round(float(avg_value), 2),
        "threshold": threshold,
        "operator": operator,
        "message": f"Metric {metric_type}.{metric_name} at {avg_value} (threshold: {threshold})",
    }

    return triggered, alert_data


def _compare_values(current: float, operator: str, threshold: float) -> bool:
    """Compare current value against threshold using operator.

    Args:
        current: Current value
        operator: Comparison operator (>, <, >=, <=)
        threshold: Threshold value

    Returns:
        True if condition is met, False otherwise
    """
    if operator == OPERATOR_GT:
        return current > threshold
    elif operator == OPERATOR_GTE:
        return current >= threshold
    elif operator == OPERATOR_LT:
        return current < threshold
    elif operator == OPERATOR_LTE:
        return current <= threshold
    return False


def _json_safe(value: Any) -> Any:
    """Convert alert metadata into JSON-compatible values for JSONB storage."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _build_alert_message(rule: AlertRule, alert_data: dict[str, Any]) -> tuple[str, str]:
    """Build a consistent alert title/body for all notification channels."""
    alert_title = f"[Alert] {rule.name}"
    alert_body = alert_data.get("message", f"Alert rule '{rule.name}' triggered")
    return alert_title, alert_body


async def _record_notification_event(
    db,
    rule: AlertRule,
    *,
    channel: str,
    recipient: str | None,
    title: str,
    body: str,
    status: str,
    alert_data: dict[str, Any],
    result: dict[str, Any],
    retry_count: int = 0,
    error_message: str | None = None,
) -> NotificationEvent:
    """Persist notification delivery outcome for audit and retry workflows."""
    raw_error = error_message or result.get("error")
    serialized_error = str(raw_error)[:1000] if raw_error else None
    notification_event = NotificationEvent(
        tenant_id=rule.tenant_id,
        channel=channel[:20],
        recipient=recipient,
        title=title[:255],
        body=body[:2000],
        status=status,
        retry_count=str(retry_count),
        error_message=serialized_error,
        metadata_json=_json_safe(
            {
                "rule_id": str(rule.id),
                "rule_name": rule.name,
                "condition": rule.condition_json,
                "alert_data": alert_data,
                "delivery_result": result,
            }
        ),
        sent_at=datetime.now(timezone.utc) if status == "sent" else None,
    )
    db.add(notification_event)
    return notification_event


async def send_alert_notification(
    ctx: dict,
    rule_id: str,
    alert_data: dict[str, Any],
) -> dict[str, Any]:
    """Send alert notification via configured channels.

    Supports:
    - Email: Sends via NotificationService SMTP integration
    - Webhook: POSTs alert data to configured URL
    - System: Logs and persists an in-app notification event

    Args:
        ctx: ARQ context dict containing redis connection
        rule_id: UUID string of the triggered alert rule
        alert_data: Alert data to send

    Returns:
        Dict with notification results
    """
    logfire.info(f"Sending alert notifications for rule: {rule_id}")

    async with AsyncSessionLocal() as db:
        # Get the alert rule
        result = await db.execute(
            select(AlertRule).where(AlertRule.id == UUID(rule_id))
        )
        rule = result.scalar_one_or_none()

        if not rule:
            logfire.error(f"Alert rule not found for notification: {rule_id}")
            return {"success": False, "error": "Rule not found"}

        notification_channels = rule.notification_channels or []
        results = []
        notification_event_count = 0

        for channel in notification_channels:
            try:
                if channel.startswith("email:"):
                    recipient = channel[6:]  # Extract email after "email:"
                    result = await _send_email_notification(recipient, rule, alert_data)
                elif channel.startswith("webhook:"):
                    webhook_url = channel[8:]  # Extract URL after "webhook:"
                    result = await _send_webhook_notification(webhook_url, rule, alert_data)
                elif channel == "system":
                    result = await _send_system_notification(rule, alert_data)
                    try:
                        from app.domains.notifications.service import UserNotificationService

                        await UserNotificationService(db).broadcast_to_tenant(
                            tenant_id=rule.tenant_id,
                            title=result["title"],
                            body=result["body"],
                            category="operations_alert",
                            priority="urgent",
                            action_url="/system-health",
                            entity_type="alert_rule",
                            entity_id=rule.id,
                            dedupe_key=f"alert:{rule.id}:{alert_data.get('triggered_at') or alert_data.get('timestamp') or str(alert_data)}",
                            metadata={"alert_data": alert_data},
                            ack_required=True,
                        )
                    except Exception as inbox_error:
                        # Channel delivery evidence remains valid even when the
                        # optional user-inbox fanout needs a later retry.
                        logfire.error(
                            "Failed to fan out system alert to user inboxes",
                            rule_id=str(rule.id),
                            error=str(inbox_error),
                        )
                else:
                    logfire.warning(f"Unknown notification channel: {channel}")
                    title, body = _build_alert_message(rule, alert_data)
                    result = {
                        "channel": channel,
                        "channel_type": "unknown",
                        "recipient": channel,
                        "title": title,
                        "body": body,
                        "success": False,
                        "error": "Unknown channel",
                    }
                results.append(result)
            except Exception as e:
                logfire.error(f"Error sending notification via {channel}: {e}")
                title, body = _build_alert_message(rule, alert_data)
                result = {
                    "channel": channel,
                    "channel_type": channel.split(":", 1)[0] if channel else "unknown",
                    "recipient": channel.split(":", 1)[1] if ":" in channel else channel,
                    "title": title,
                    "body": body,
                    "success": False,
                    "error": str(e),
                }
                results.append(result)

            await _record_notification_event(
                db,
                rule,
                channel=result.get("channel_type", "unknown"),
                recipient=result.get("recipient"),
                title=result.get("title") or _build_alert_message(rule, alert_data)[0],
                body=result.get("body") or _build_alert_message(rule, alert_data)[1],
                status="sent" if result.get("success") else "failed",
                alert_data=alert_data,
                result=result,
                retry_count=int(result.get("retry_count", 0) or 0),
                error_message=result.get("error"),
            )
            notification_event_count += 1

        if notification_event_count:
            await db.commit()

        all_success = all(r.get("success", False) for r in results)
        logfire.info(
            f"Alert notification complete for rule: {rule_id}",
            total_channels=len(notification_channels),
            successful=sum(1 for r in results if r.get("success")),
        )

        return {
            "success": all_success,
            "rule_id": rule_id,
            "results": results,
            "notification_event_count": notification_event_count,
        }


async def _send_email_notification(
    recipient: str,
    rule: AlertRule,
    alert_data: dict[str, Any],
) -> dict[str, Any]:
    """Send email notification using NotificationService with retry.

    Args:
        recipient: Email address
        rule: AlertRule that triggered
        alert_data: Alert data

    Returns:
        Dict with result
    """
    from app.services.notification_service import (
        NotificationService,
        NotificationChannel,
        NotificationPriority,
    )

    notification_service = NotificationService()

    alert_title, alert_body = _build_alert_message(rule, alert_data)

    # Retry configuration
    max_retries = 3
    retry_delay = 5  # seconds

    for attempt in range(max_retries):
        try:
            result = await notification_service.send(
                title=alert_title,
                body=alert_body,
                channel=NotificationChannel.EMAIL,
                recipient=recipient,
                priority=NotificationPriority.HIGH,
                metadata={
                    "rule_id": str(rule.id),
                    "alert_data": alert_data,
                    "tenant_id": str(rule.tenant_id) if rule.tenant_id else None,
                },
            )

            if result.success:
                logfire.info(
                    f"Email notification sent successfully to {recipient}",
                    rule_name=rule.name,
                    attempt=attempt + 1,
                )
                return {
                    "channel": f"email:{recipient}",
                    "channel_type": "email",
                    "recipient": recipient,
                    "title": alert_title,
                    "body": alert_body,
                    "success": True,
                    "message": f"Email sent to {recipient}",
                    "retry_count": attempt,
                }

            logfire.warning(
                f"Email notification attempt {attempt + 1} failed: {result.error}",
                rule_name=rule.name,
                attempt=attempt + 1,
            )

        except Exception as e:
            logfire.error(
                f"Email notification error on attempt {attempt + 1}: {e}",
                rule_name=rule.name,
                attempt=attempt + 1,
            )

        # Wait before retry if not last attempt
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay * (attempt + 1))  # Exponential backoff

    # All retries exhausted - write notification event for later processing
    logfire.error(
        f"Email notification failed after {max_retries} attempts",
        rule_name=rule.name,
        recipient=recipient,
    )

    return {
        "channel": f"email:{recipient}",
        "channel_type": "email",
        "recipient": recipient,
        "title": alert_title,
        "body": alert_body,
        "success": False,
        "error": f"Failed after {max_retries} attempts",
        "message": f"Email notification failed after {max_retries} attempts",
        "retry_count": max_retries,
    }


async def _send_webhook_notification(
    webhook_url: str,
    rule: AlertRule,
    alert_data: dict[str, Any],
) -> dict[str, Any]:
    """Send webhook notification.

    Args:
        webhook_url: URL to POST alert data to
        rule: AlertRule that triggered
        alert_data: Alert data

    Returns:
        Dict with result
    """
    payload = {
        "event_type": "alert_triggered",
        "rule_id": str(rule.id),
        "rule_name": rule.name,
        "tenant_id": str(rule.tenant_id),
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "alert_data": alert_data,
        "condition": rule.condition_json,
    }
    alert_title, alert_body = _build_alert_message(rule, alert_data)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        if 200 <= response.status_code < 300:
            logfire.info(f"Webhook notification sent successfully: {webhook_url}")
            return {
                "channel": f"webhook:{webhook_url}",
                "channel_type": "webhook",
                "recipient": webhook_url,
                "title": alert_title,
                "body": alert_body,
                "success": True,
                "status_code": response.status_code,
            }
        else:
            logfire.warning(
                f"Webhook notification failed: {webhook_url}",
                status_code=response.status_code,
                response=response.text[:500],
            )
            return {
                "channel": f"webhook:{webhook_url}",
                "channel_type": "webhook",
                "recipient": webhook_url,
                "title": alert_title,
                "body": alert_body,
                "success": False,
                "status_code": response.status_code,
                "error": f"HTTP {response.status_code}",
            }

    except Exception as e:
        logfire.error(f"Webhook notification error: {webhook_url}", error=str(e))
        return {
            "channel": f"webhook:{webhook_url}",
            "channel_type": "webhook",
            "recipient": webhook_url,
            "title": alert_title,
            "body": alert_body,
            "success": False,
            "error": str(e),
        }


async def _send_system_notification(
    rule: AlertRule,
    alert_data: dict[str, Any],
) -> dict[str, Any]:
    """Send system notification (logged).

    Args:
        rule: AlertRule that triggered
        alert_data: Alert data

    Returns:
        Dict with result
    """
    logfire.warning(
        f"[SYSTEM ALERT] Rule '{rule.name}' triggered",
        rule_id=str(rule.id),
        tenant_id=str(rule.tenant_id),
        alert_data=alert_data,
    )
    alert_title, alert_body = _build_alert_message(rule, alert_data)

    return {
        "channel": "system",
        "channel_type": "system",
        "recipient": "system",
        "title": alert_title,
        "body": alert_body,
        "success": True,
        "message": "System notification logged",
    }


# Helper functions for job queue management


async def enqueue_alert_evaluation(ctx: dict) -> None:
    """Enqueue an alert evaluation job.

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
            "evaluate_alert_rules",
            redis=redis,
        )
        logfire.info("Enqueued alert evaluation job")
    except Exception as e:
        logfire.error(f"Failed to enqueue alert evaluation", error=str(e))


async def enqueue_single_rule_evaluation(ctx: dict, rule_id: str) -> None:
    """Enqueue evaluation of a single alert rule.

    Args:
        ctx: ARQ context dict
        rule_id: UUID of the rule to evaluate
    """
    redis = ctx.get("redis")
    if not redis:
        logfire.error("Redis not available for enqueuing")
        return

    from arq import enqueue_job

    try:
        await enqueue_job(
            "evaluate_single_rule",
            rule_id,
            redis=redis,
        )
        logfire.info(f"Enqueued alert rule evaluation: {rule_id}")
    except Exception as e:
        logfire.error(f"Failed to enqueue alert rule evaluation: {rule_id}", error=str(e))
