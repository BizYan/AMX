"""Prompt Cache Service Tests

Tests for Redis-based LLM prompt caching with tenant isolation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.prompt_cache import PromptCacheService, get_prompt_cache_service


class TestPromptCacheService:
    """Tests for PromptCacheService."""

    @pytest.fixture
    def mock_cache_service(self):
        """Create mock cache service."""
        mock = MagicMock()
        mock._redis = AsyncMock()
        return mock

    @pytest.fixture
    def cache_service(self, mock_cache_service):
        """Create prompt cache service with mock."""
        return PromptCacheService(mock_cache_service, default_ttl=3600)

    def test_cache_key_format(self, cache_service):
        """Test cache key generation format."""
        tenant_id = "tenant-123"
        prompt = "Hello, world!"
        model = "test-model"

        key = cache_service._generate_cache_key(tenant_id, prompt, model)

        assert key.startswith("prompt_cache:tenant-123:")
        assert len(key.split(":")) == 3

    def test_cache_key_consistency(self, cache_service):
        """Test same inputs produce same cache key."""
        tenant_id = "tenant-123"
        prompt = "Hello, world!"
        model = "test-model"

        key1 = cache_service._generate_cache_key(tenant_id, prompt, model)
        key2 = cache_service._generate_cache_key(tenant_id, prompt, model)

        assert key1 == key2

    def test_cache_key_different_for_different_prompts(self, cache_service):
        """Test different prompts produce different cache keys."""
        tenant_id = "tenant-123"
        model = "test-model"

        key1 = cache_service._generate_cache_key(tenant_id, "Prompt 1", model)
        key2 = cache_service._generate_cache_key(tenant_id, "Prompt 2", model)

        assert key1 != key2

    def test_cache_key_different_for_different_tenants(self, cache_service):
        """Test different tenants produce different cache keys."""
        prompt = "Hello, world!"
        model = "test-model"

        key1 = cache_service._generate_cache_key("tenant-1", prompt, model)
        key2 = cache_service._generate_cache_key("tenant-2", prompt, model)

        assert key1 != key2

    def test_cache_key_different_for_different_models(self, cache_service):
        """Test different models produce different cache keys."""
        tenant_id = "tenant-123"
        prompt = "Hello, world!"

        key1 = cache_service._generate_cache_key(tenant_id, prompt, "model-a")
        key2 = cache_service._generate_cache_key(tenant_id, prompt, "model-b")

        assert key1 != key2

    @pytest.mark.asyncio
    async def test_get_cached_response_hit(self, cache_service, mock_cache_service):
        """Test cache hit returns cached response."""
        mock_cache_service.get = AsyncMock(return_value="cached response")

        result = await cache_service.get_cached_response(
            prompt="Hello",
            tenant_id="tenant-123",
            model="test-model",
        )

        assert result == "cached response"

    @pytest.mark.asyncio
    async def test_get_cached_response_miss(self, cache_service, mock_cache_service):
        """Test cache miss returns None."""
        mock_cache_service.get = AsyncMock(return_value=None)

        result = await cache_service.get_cached_response(
            prompt="Hello",
            tenant_id="tenant-123",
            model="test-model",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_response(self, cache_service, mock_cache_service):
        """Test caching a response."""
        mock_cache_service.set = AsyncMock()

        await cache_service.cache_response(
            prompt="Hello",
            tenant_id="tenant-123",
            model="test-model",
            response="LLM response",
        )

        mock_cache_service.set.assert_called_once()
        call_args = mock_cache_service.set.call_args
        assert call_args.kwargs["value"] == "LLM response"
        assert call_args.kwargs["tenant_id"] == "tenant-123"

    @pytest.mark.asyncio
    async def test_cache_response_custom_ttl(self, cache_service, mock_cache_service):
        """Test caching with custom TTL."""
        mock_cache_service.set = AsyncMock()

        await cache_service.cache_response(
            prompt="Hello",
            tenant_id="tenant-123",
            model="test-model",
            response="LLM response",
            ttl=7200,
        )

        call_args = mock_cache_service.set.call_args
        assert call_args.kwargs["ttl"] == 7200

    @pytest.mark.asyncio
    async def test_invalidate_tenant_cache(self, cache_service, mock_cache_service):
        """Test invalidating all cache for a tenant."""
        mock_cache_service._redis = AsyncMock()
        mock_cache_service._redis.scan = AsyncMock(
            side_effect=[(0, ["key1", "key2"])]
        )
        mock_cache_service._redis.delete = AsyncMock(return_value=2)

        deleted = await cache_service.invalidate_tenant_cache("tenant-123")

        assert deleted == 2

    @pytest.mark.asyncio
    async def test_invalidate_tenant_cache_no_redis(self, cache_service, mock_cache_service):
        """Test invalidating when Redis is unavailable."""
        mock_cache_service._redis = None

        deleted = await cache_service.invalidate_tenant_cache("tenant-123")

        assert deleted == 0

    @pytest.mark.asyncio
    async def test_get_cache_stats(self, cache_service, mock_cache_service):
        """Test getting cache statistics."""
        mock_cache_service._redis = AsyncMock()
        mock_cache_service._redis.hget = AsyncMock(
            side_effect=["10", "5", None]
        )

        stats = await cache_service.get_cache_stats("tenant-123")

        assert "hits" in stats
        assert "misses" in stats
        assert "hit_rate" in stats

    @pytest.mark.asyncio
    async def test_get_cache_stats_no_redis(self, cache_service, mock_cache_service):
        """Test getting cache stats when Redis is unavailable."""
        mock_cache_service._redis = None

        stats = await cache_service.get_cache_stats("tenant-123")

        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_get_cache_stats_empty(self, cache_service, mock_cache_service):
        """Test getting stats when no cache activity recorded."""
        mock_cache_service._redis = AsyncMock()
        mock_cache_service._redis.hget = AsyncMock(return_value=None)

        stats = await cache_service.get_cache_stats("tenant-123")

        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_hit_rate_calculation(self, cache_service, mock_cache_service):
        """Test hit rate calculation is correct."""
        mock_cache_service._redis = AsyncMock()
        mock_cache_service._redis.hget = AsyncMock(
            side_effect=["80", "20", None]
        )

        stats = await cache_service.get_cache_stats("tenant-123")

        assert stats["hits"] == 80
        assert stats["misses"] == 20
        assert stats["hit_rate"] == 80.0

    @pytest.mark.asyncio
    async def test_hit_rate_zero_on_no_data(self, cache_service, mock_cache_service):
        """Test hit rate is 0 when no data."""
        mock_cache_service._redis = AsyncMock()
        mock_cache_service._redis.hget = AsyncMock(return_value=None)

        stats = await cache_service.get_cache_stats("tenant-123")

        assert stats["hit_rate"] == 0.0


class TestGetPromptCacheService:
    """Tests for get_prompt_cache_service factory function."""

    @pytest.mark.asyncio
    async def test_returns_prompt_cache_service(self):
        """Test factory returns PromptCacheService instance."""
        with patch("app.services.prompt_cache.CacheService") as mock_cache_class:
            mock_cache_class.get_instance = AsyncMock()
            mock_cache_class.get_instance.return_value = MagicMock()

            service = await get_prompt_cache_service()

            assert isinstance(service, PromptCacheService)