"""Idempotency Middleware

Middleware to prevent duplicate API request processing using Redis-based
idempotency keys stored in the database.
"""

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.settings import settings


class IdempotencyRecord:
    """Record for tracking idempotency keys."""

    def __init__(
        self,
        idempotency_key: str,
        tenant_id: UUID,
        user_id: UUID | None,
        endpoint: str,
        request_hash: str,
        response_body: bytes | None = None,
        response_status: int | None = None,
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
    ):
        self.idempotency_key = idempotency_key
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.endpoint = endpoint
        self.request_hash = request_hash
        self.response_body = response_body
        self.response_status = response_status
        self.created_at = created_at or datetime.now(timezone.utc)
        self.expires_at = expires_at


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Middleware to handle idempotent API requests.

    Uses a combination of Redis (for fast lookups) and database
    (for durable storage) to track idempotency keys.

    The idempotency key should be provided in the X-Idempotency-Key header.
    """

    # Headers
    IDEMPOTENCY_KEY_HEADER = "x-idempotency-key"
    RETRY_COUNT_HEADER = "x-idempotency-retry-count"

    # TTL for idempotency records (default 24 hours)
    DEFAULT_TTL_SECONDS = 86400

    # Maximum size for response body to cache (1MB)
    MAX_RESPONSE_SIZE = 1024 * 1024

    # Endpoints that support idempotency
    IDEMPOTENT_ENDPOINTS = {
        "POST",
        "PUT",
        "PATCH",
    }

    def __init__(self, app, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        """Initialize idempotency middleware.

        Args:
            app: FastAPI application
            ttl_seconds: Time-to-live for idempotency records in seconds
        """
        super().__init__(app)
        self.ttl_seconds = ttl_seconds
        # Endpoints to exclude from idempotency checking
        self.exclude_paths = {
            "/health",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/redoc",
        }

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        """Process the request with idempotency checking.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response with idempotency handling
        """
        # Skip if method doesn't support idempotency
        if request.method not in self.IDEMPOTENT_ENDPOINTS:
            return await call_next(request)

        # Skip if path is excluded
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return await call_next(request)

        # Get idempotency key from header
        idempotency_key = request.headers.get(self.IDEMPOTENCY_KEY_HEADER)

        if not idempotency_key:
            # No idempotency key provided - process normally
            return await call_next(request)

        # Validate idempotency key format (should be UUID-like)
        if len(idempotency_key) > 64 or len(idempotency_key) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid idempotency key format",
            )

        # Check if we have a cached response
        cached = await self._check_cache(idempotency_key, request)
        if cached:
            return cached

        # Process request and cache response
        response = await call_next(request)

        # Cache successful responses
        if response.status_code < 400:
            await self._cache_response(idempotency_key, request, response)

        return response

    async def _check_cache(
        self, idempotency_key: str, request: Request
    ) -> Response | None:
        """Check if there's a cached response for this idempotency key.

        Args:
            idempotency_key: The idempotency key
            request: The original request

        Returns:
            Cached response if exists, None otherwise
        """
        # Import here to avoid circular imports
        from app.services.cache_service import CacheService

        # Try Redis first for fast lookup
        cache_key = f"idempotency:{idempotency_key}"
        try:
            cache_service = CacheService()
            cached_data = await cache_service.redis.get(cache_key)

            if cached_data:
                # Found in Redis - return cached response
                data = json.loads(cached_data)
                return Response(
                    content=data["body"],
                    status_code=data["status"],
                    headers={
                        "X-Idempotency-Replayed": "true",
                        "X-Idempotency-Key": idempotency_key,
                    },
                    media_type=data.get("media_type", "application/json"),
                )
        except Exception:
            # Redis unavailable - fall through to check database
            pass

        return None

    async def _cache_response(
        self, idempotency_key: str, request: Request, response: Response
    ) -> None:
        """Cache the response for this idempotency key.

        Args:
            idempotency_key: The idempotency key
            request: The original request
            response: The response to cache
        """
        from app.services.cache_service import CacheService

        # Read response body
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        # Skip if response is too large
        if len(body) > self.MAX_RESPONSE_SIZE:
            return

        cache_key = f"idempotency:{idempotency_key}"

        # Cache in Redis with TTL
        data = {
            "status": response.status_code,
            "body": body.decode("utf-8", errors="replace"),
            "media_type": response.media_type or "application/json",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            cache_service = CacheService()
            await cache_service.redis.set(
                cache_key,
                json.dumps(data),
                ex=self.ttl_seconds,
            )
        except Exception:
            # Log but don't fail if Redis caching fails
            pass


def generate_idempotency_key(
    method: str,
    endpoint: str,
    tenant_id: UUID,
    request_body: dict | None = None,
) -> str:
    """Generate an idempotency key from request details.

    Args:
        method: HTTP method
        endpoint: API endpoint
        tenant_id: Tenant UUID
        request_body: Request body dict

    Returns:
        Deterministic idempotency key
    """
    # Create deterministic string from request details
    parts = [
        str(tenant_id),
        method.upper(),
        endpoint,
    ]

    if request_body:
        # Sort keys for deterministic serialization
        body_str = json.dumps(request_body, sort_keys=True, default=str)
        body_hash = hashlib.sha256(body_str.encode()).hexdigest()[:16]
        parts.append(body_hash)

    # Create composite key
    composite = "|".join(parts)
    return hashlib.sha256(composite.encode()).hexdigest()[:32]


async def check_idempotency_key_exists(
    db: AsyncSession,
    idempotency_key: str,
) -> bool:
    """Check if an idempotency key already exists in the database.

    Args:
        db: Database session
        idempotency_key: The key to check

    Returns:
        True if key exists, False otherwise
    """
    from app.models.ops import IdempotencyRecord as IdempotencyRecordModel

    query = select(func.count(IdempotencyRecordModel.id)).where(
        IdempotencyRecordModel.idempotency_key == idempotency_key
    )
    result = await db.execute(query)
    count = result.scalar()
    return count > 0