"""Provider Health Background Worker

Background worker to periodically check provider health (Graphify, GitNexus, MiniMax)
and record metrics to ProviderHealth table.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
import logfire
from sqlalchemy import select, and_

from app.db.session import AsyncSessionLocal
from app.domains.providers.models import (
    Provider,
    ProviderType,
    ProviderHealth,
    HealthStatus,
)
from app.integrations.gitnexus.config import load_gitnexus_runtime_config
from app.services.circuit_breaker import get_provider_circuit_breaker, CircuitState


async def check_provider_health(ctx: dict, provider_id: str) -> dict[str, Any]:
    """Check health of a single provider.

    Args:
        ctx: ARQ context dict containing redis connection
        provider_id: UUID of the provider to check

    Returns:
        Dict with health check result
    """
    logfire.info(f"Checking provider health: {provider_id}")

    async with AsyncSessionLocal() as db:
        # Get provider
        result = await db.execute(
            select(Provider).where(Provider.id == UUID(provider_id))
        )
        provider = result.scalar_one_or_none()

        if not provider:
            logfire.error(f"Provider not found: {provider_id}")
            return {"success": False, "error": "Provider not found", "provider_id": provider_id}

        # Get circuit breaker state
        circuit_breaker = get_provider_circuit_breaker()
        breaker = circuit_breaker.get_breaker(provider.name)

        # Determine health status based on circuit breaker state
        if breaker.state == CircuitState.OPEN:
            # Circuit is open - provider is down
            await record_health_metric(
                db=db,
                provider_id=UUID(provider_id),
                status=HealthStatus.DOWN,
                latency_ms=None,
                error="Circuit breaker is open",
            )
            await db.commit()
            return {
                "success": True,
                "provider_id": provider_id,
                "status": HealthStatus.DOWN.value,
                "error": "Circuit breaker is open",
            }

        # Perform actual health check based on provider type
        start_time = time.time()
        error_message = None
        health_status = HealthStatus.HEALTHY

        try:
            if provider.provider_type == ProviderType.LLM.value:
                health_status = await _check_llm_health(provider, breaker)
            elif provider.provider_type == ProviderType.GRAPHIFY.value:
                health_status = await _check_graphify_health(provider, breaker)
            elif provider.provider_type == ProviderType.GITNEXUS.value:
                health_status = await _check_gitnexus_health(provider, breaker)
            else:
                # For custom providers, assume healthy if circuit is closed
                health_status = HealthStatus.HEALTHY
        except Exception as e:
            logfire.error(f"Health check failed for provider {provider_id}", error=str(e))
            error_message = str(e)
            health_status = HealthStatus.DOWN

        latency_ms = int((time.time() - start_time) * 1000)

        # Record health metric
        await record_health_metric(
            db=db,
            provider_id=UUID(provider_id),
            status=health_status,
            latency_ms=latency_ms,
            error=error_message,
        )
        await db.commit()

        logfire.info(
            f"Health check completed for provider: {provider_id}",
            status=health_status.value,
            latency_ms=latency_ms,
        )

        return {
            "success": True,
            "provider_id": provider_id,
            "status": health_status.value,
            "latency_ms": latency_ms,
            "error": error_message,
        }


async def check_all_providers_health(ctx: dict) -> dict[str, Any]:
    """Check health of all registered providers.

    Args:
        ctx: ARQ context dict containing redis connection

    Returns:
        Dict with overall health check results
    """
    logfire.info("Checking health of all providers")

    async with AsyncSessionLocal() as db:
        # Get all active providers
        result = await db.execute(
            select(Provider).where(
                and_(
                    Provider.status == "active",
                    Provider.deleted_at.is_(None),
                )
            )
        )
        providers = result.scalars().all()

        results = []
        for provider in providers:
            try:
                result = await check_provider_health(ctx, str(provider.id))
                results.append(result)
            except Exception as e:
                logfire.error(f"Failed to check provider {provider.id}", error=str(e))
                results.append({
                    "success": False,
                    "provider_id": str(provider.id),
                    "error": str(e),
                })

        # Count health statuses
        healthy_count = sum(1 for r in results if r.get("status") == HealthStatus.HEALTHY.value)
        degraded_count = sum(1 for r in results if r.get("status") == HealthStatus.DEGRADED.value)
        down_count = sum(1 for r in results if r.get("status") == HealthStatus.DOWN.value)

        logfire.info(
            f"Health check completed for all providers",
            total=len(providers),
            healthy=healthy_count,
            degraded=degraded_count,
            down=down_count,
        )

        return {
            "success": True,
            "total_providers": len(providers),
            "healthy": healthy_count,
            "degraded": degraded_count,
            "down": down_count,
            "results": results,
        }


async def record_health_metric(
    db,
    provider_id: UUID,
    status: HealthStatus,
    latency_ms: int | None = None,
    error: str | None = None,
) -> ProviderHealth:
    """Record a health metric for a provider.

    Args:
        db: Database session
        provider_id: UUID of the provider
        status: Health status (HEALTHY, DEGRADED, DOWN)
        latency_ms: Response time in milliseconds
        error: Error message if any

    Returns:
        Created ProviderHealth record
    """
    health_record = ProviderHealth(
        provider_id=provider_id,
        status=status.value,
        response_time_ms=latency_ms,
        last_check_at=datetime.now(timezone.utc),
    )

    db.add(health_record)
    return health_record


async def _check_llm_health(provider: Provider, breaker) -> HealthStatus:
    """Check LLM provider health by calling /v1/models endpoint.

    Args:
        provider: Provider model instance
        breaker: Circuit breaker for this provider

    Returns:
        HealthStatus based on the check result
    """
    config = provider.config_json or {}
    base_url = config.get("base_url", "https://api.minimax.chat/v1")
    api_key = config.get("api_key", "")

    if not api_key:
        return HealthStatus.DEGRADED

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            if response.status_code == 200:
                return HealthStatus.HEALTHY
            elif response.status_code >= 500:
                return HealthStatus.DOWN
            else:
                return HealthStatus.DEGRADED
    except httpx.Timeout:
        return HealthStatus.DEGRADED
    except httpx.RequestError:
        return HealthStatus.DOWN


async def _check_graphify_health(provider: Provider, breaker) -> HealthStatus:
    """Check Graphify provider health.

    Args:
        provider: Provider model instance
        breaker: Circuit breaker for this provider

    Returns:
        HealthStatus based on the check result
    """
    config = provider.config_json or {}
    endpoint = _provider_endpoint(config)
    if endpoint is None:
        return HealthStatus.DOWN
    api_key = config.get("api_key")

    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{endpoint}/health",
                headers=headers,
            )

            if response.status_code == 200:
                return HealthStatus.HEALTHY
            elif response.status_code >= 500:
                return HealthStatus.DOWN
            else:
                return HealthStatus.DEGRADED
    except httpx.Timeout:
        return HealthStatus.DEGRADED
    except httpx.RequestError:
        return HealthStatus.DOWN


async def _check_gitnexus_health(provider: Provider, breaker) -> HealthStatus:
    """Check GitNexus provider health.

    Args:
        provider: Provider model instance
        breaker: Circuit breaker for this provider

    Returns:
        HealthStatus based on the check result
    """
    try:
        runtime_config = load_gitnexus_runtime_config(provider.config_json or {})
    except ValueError:
        return HealthStatus.DOWN

    try:
        headers = {}
        if runtime_config.api_key:
            headers["Authorization"] = f"Bearer {runtime_config.api_key}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{runtime_config.endpoint}{runtime_config.health_path}",
                headers=headers,
            )

            if response.status_code == 200:
                return HealthStatus.HEALTHY
            elif response.status_code >= 500:
                return HealthStatus.DOWN
            else:
                return HealthStatus.DEGRADED
    except httpx.Timeout:
        return HealthStatus.DEGRADED
    except httpx.RequestError:
        return HealthStatus.DOWN


def _provider_endpoint(config: dict[str, Any]) -> str | None:
    for key in ("endpoint", "base_url", "server_url", "api_url", "url"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip("/")
    return None
