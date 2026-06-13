"""LLM Prompt Cache Service

Provides Redis-based caching for LLM responses to reduce API costs.
Cache key format: prompt_cache:{tenant_id}:{hash(prompt+model)}
"""

import hashlib
from typing import Any

from app.services.cache_service import CacheService


class PromptCacheService:
    """Redis-based LLM prompt cache service.

    Provides caching of LLM responses based on prompt hash and tenant context
    to reduce API costs and improve response times.
    """

    CACHE_KEY_PREFIX = "prompt_cache"

    def __init__(self, cache_service: CacheService, default_ttl: int = 3600):
        """Initialize prompt cache service.

        Args:
            cache_service: CacheService instance for Redis operations
            default_ttl: Default time-to-live in seconds (default 1 hour)
        """
        self._cache = cache_service
        self._default_ttl = default_ttl

    def _generate_cache_key(self, tenant_id: str, prompt: str, model: str) -> str:
        """Generate cache key from tenant, prompt, and model.

        Args:
            tenant_id: Tenant UUID string
            prompt: The LLM prompt text
            model: The model name

        Returns:
            Cache key in format: prompt_cache:{tenant_id}:{hash(prompt+model)}
        """
        content = f"{prompt}:{model}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
        return f"{self.CACHE_KEY_PREFIX}:{tenant_id}:{content_hash}"

    async def get_cached_response(
        self,
        prompt: str,
        tenant_id: str,
        model: str,
    ) -> str | None:
        """Get cached LLM response for the given prompt.

        Args:
            prompt: The LLM prompt text
            tenant_id: Tenant UUID string
            model: The model name

        Returns:
            Cached response string or None if not found
        """
        cache_key = self._generate_cache_key(tenant_id, prompt, model)

        # Get cached response from Redis
        cached = await self._cache.get(cache_key, tenant_id)
        if cached is not None:
            # Track hit
            await self._increment_stat(tenant_id, "hits")
            return cached

        # Track miss
        await self._increment_stat(tenant_id, "misses")
        return None

    async def cache_response(
        self,
        prompt: str,
        tenant_id: str,
        model: str,
        response: str,
        ttl: int | None = None,
    ) -> None:
        """Cache LLM response for future use.

        Args:
            prompt: The LLM prompt text
            tenant_id: Tenant UUID string
            model: The model name
            response: The LLM response text to cache
            ttl: Optional TTL in seconds, uses default if not specified
        """
        cache_key = self._generate_cache_key(tenant_id, prompt, model)
        await self._cache.set(
            key=cache_key,
            value=response,
            tenant_id=tenant_id,
            ttl=ttl or self._default_ttl,
        )

    async def invalidate_tenant_cache(self, tenant_id: str) -> int:
        """Clear all cached responses for a tenant.

        Uses Redis SCAN to find and delete all keys matching the tenant's cache.

        Args:
            tenant_id: Tenant UUID string

        Returns:
            Number of keys deleted
        """
        deleted_count = 0

        if self._cache._redis:
            try:
                pattern = f"{self.CACHE_KEY_PREFIX}:{tenant_id}:*"
                cursor = 0

                while True:
                    cursor, keys = await self._cache._redis.scan(
                        cursor=cursor,
                        match=pattern,
                        count=100,
                    )

                    if keys:
                        deleted = await self._cache._redis.delete(*keys)
                        deleted_count += deleted

                    if cursor == 0:
                        break

                # Clear tenant stats
                stats_key = f"{self.CACHE_KEY_PREFIX}:stats:{tenant_id}"
                await self._cache._redis.delete(stats_key)

            except Exception:
                pass

        return deleted_count

    async def get_cache_stats(self, tenant_id: str) -> dict[str, int]:
        """Get cache hit/miss statistics for a tenant.

        Args:
            tenant_id: Tenant UUID string

        Returns:
            Dictionary with 'hits', 'misses', and 'hit_rate' keys
        """
        hits = await self._get_stat(tenant_id, "hits")
        misses = await self._get_stat(tenant_id, "misses")

        total = hits + misses
        hit_rate = (hits / total * 100) if total > 0 else 0.0

        return {
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hit_rate, 2),
        }

    async def _increment_stat(self, tenant_id: str, stat_name: str) -> None:
        """Increment a statistic counter.

        Args:
            tenant_id: Tenant UUID string
            stat_name: Name of the statistic ('hits' or 'misses')
        """
        if self._cache._redis:
            try:
                stats_key = f"{self.CACHE_KEY_PREFIX}:stats:{tenant_id}"
                await self._cache._redis.hincrby(stats_key, stat_name, 1)
            except Exception:
                pass

    async def _get_stat(self, tenant_id: str, stat_name: str) -> int:
        """Get a statistic counter value.

        Args:
            tenant_id: Tenant UUID string
            stat_name: Name of the statistic ('hits' or 'misses')

        Returns:
            Counter value (0 if not found)
        """
        if self._cache._redis:
            try:
                stats_key = f"{self.CACHE_KEY_PREFIX}:stats:{tenant_id}"
                value = await self._cache._redis.hget(stats_key, stat_name)
                return int(value) if value else 0
            except Exception:
                pass

        return 0


async def get_prompt_cache_service() -> PromptCacheService:
    """Get singleton prompt cache service instance.

    Returns:
        PromptCacheService: Singleton instance
    """
    cache_service = await CacheService.get_instance()
    return PromptCacheService(cache_service)