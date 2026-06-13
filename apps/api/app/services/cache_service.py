"""Cache Service Module

Provides Redis-based caching with tenant isolation and distributed locking.
"""

import json
from typing import Any, Callable, Awaitable

import redis.asyncio as redis
from redis.asyncio.lock import Lock

from app.core.settings import settings


class CacheService:
    """Redis-based caching service with tenant isolation.

    All keys are namespaced as cache:{tenant_id}:{key} to ensure tenant separation.
    """

    _instance: "CacheService | None" = None
    _redis: redis.Redis | None = None

    def __init__(self):
        """Initialize cache service."""
        self._local_cache: dict[str, tuple[Any, float]] = {}  # For in-memory fallback
        self._local_cache_ttl: float = 5.0  # 5 second local cache

    @classmethod
    async def get_instance(cls) -> "CacheService":
        """Get singleton cache service instance.

        Returns:
            CacheService: Singleton instance
        """
        if cls._instance is None:
            cls._instance = cls()
            await cls._instance._connect()
        return cls._instance

    async def _connect(self) -> None:
        """Establish Redis connection."""
        if settings.REDIS_URL:
            self._redis = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        else:
            self._redis = None

    def _get_key(self, key: str, tenant_id: str) -> str:
        """Get namespaced cache key.

        Args:
            key: Base key
            tenant_id: Tenant UUID string

        Returns:
            Namespaced key: cache:{tenant_id}:{key}
        """
        return f"cache:{tenant_id}:{key}"

    async def get(self, key: str, tenant_id: str) -> Any | None:
        """Get value from cache.

        Args:
            key: Cache key
            tenant_id: Tenant UUID string

        Returns:
            Cached value or None if not found/expired
        """
        namespaced_key = self._get_key(key, tenant_id)

        # Try local cache first
        import time
        now = time.time()
        if namespaced_key in self._local_cache:
            value, expires_at = self._local_cache[namespaced_key]
            if expires_at > now:
                return value
            del self._local_cache[namespaced_key]

        # Try Redis
        if self._redis:
            try:
                value = await self._redis.get(namespaced_key)
                if value is not None:
                    # Update local cache
                    self._local_cache[namespaced_key] = (value, now + self._local_cache_ttl)
                    return json.loads(value)
            except Exception:
                pass

        return None

    async def set(self, key: str, value: Any, tenant_id: str, ttl: int = 3600) -> None:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            tenant_id: Tenant UUID string
            ttl: Time-to-live in seconds (default 1 hour)
        """
        namespaced_key = self._get_key(key, tenant_id)

        # Update local cache
        import time
        now = time.time()
        self._local_cache[namespaced_key] = (value, now + self._local_cache_ttl)

        # Set in Redis
        if self._redis:
            try:
                serialized = json.dumps(value)
                await self._redis.setex(namespaced_key, ttl, serialized)
            except Exception:
                pass

    async def delete(self, key: str, tenant_id: str) -> None:
        """Delete value from cache.

        Args:
            key: Cache key
            tenant_id: Tenant UUID string
        """
        namespaced_key = self._get_key(key, tenant_id)

        # Remove from local cache
        self._local_cache.pop(namespaced_key, None)

        # Delete from Redis
        if self._redis:
            try:
                await self._redis.delete(namespaced_key)
            except Exception:
                pass

    async def get_or_set(
        self,
        key: str,
        tenant_id: str,
        factory: Callable[[], Awaitable[Any]],
        ttl: int = 3600,
    ) -> Any:
        """Get value from cache or set using factory function.

        Args:
            key: Cache key
            tenant_id: Tenant UUID string
            factory: Async function to generate value on cache miss
            ttl: Time-to-live in seconds

        Returns:
            Cached or newly generated value
        """
        cached = await self.get(key, tenant_id)
        if cached is not None:
            return cached

        value = await factory()
        await self.set(key, value, tenant_id, ttl)
        return value


# Distributed Lock Functions

_lock_instances: dict[str, Lock] = {}


async def acquire_lock(
    lock_name: str,
    tenant_id: str,
    timeout: int = 10,
    ttl: int = 60,
) -> bool:
    """Acquire a distributed lock.

    Uses Redis-based distributed locking with automatic expiration.
    Lock key format: lock:{tenant_id}:{lock_name}

    Args:
        lock_name: Name of the lock
        tenant_id: Tenant UUID string
        timeout: Maximum time to wait for lock acquisition
        ttl: Lock expiration time in seconds

    Returns:
        True if lock acquired, False otherwise
    """
    cache_service = await CacheService.get_instance()

    if cache_service._redis is None:
        # No Redis, use in-memory simulation
        import time
        lock_key = f"lock:{tenant_id}:{lock_name}"
        current_time = time.time()

        if lock_key in _lock_instances:
            lock_data = _lock_instances[lock_key]
            if lock_data[1] > current_time:
                return False  # Lock already held

        _lock_instances[lock_key] = (True, current_time + ttl)
        return True

    lock_key = f"lock:{tenant_id}:{lock_name}"

    try:
        lock = cache_service._redis.lock(
            lock_key,
            timeout=timeout,
            blocking=True,
            blocking_timeout=timeout,
        )
        result = await lock.acquire(blocking_timeout=timeout)
        if result:
            _lock_instances[f"{tenant_id}:{lock_name}"] = lock
        return result
    except Exception:
        return False


async def release_lock(lock_name: str, tenant_id: str) -> None:
    """Release a distributed lock.

    Args:
        lock_name: Name of the lock
        tenant_id: Tenant UUID string
    """
    cache_service = await CacheService.get_instance()

    # Clean up in-memory lock
    lock_key = f"{tenant_id}:{lock_name}"
    _lock_instances.pop(lock_key, None)

    if cache_service._redis:
        try:
            full_lock_name = f"lock:{tenant_id}:{lock_name}"
            lock = cache_service._redis.lock(full_lock_name)
            await lock.release()
        except Exception:
            pass