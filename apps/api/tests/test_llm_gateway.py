"""LLM Gateway Tests

Tests for provider fallback routing, circuit breaker integration,
and health tracking in the LLM Gateway.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from uuid import uuid4

from app.domains.providers.contracts import LLMResponse, EmbedResponse, ProviderError
from app.integrations.llm.gateway import LLMGateway, ProviderConfig, GatewayFactory
from app.services.circuit_breaker import CircuitState, CircuitOpenError


class TestProviderConfig:
    """Tests for ProviderConfig dataclass."""

    def test_provider_config_creation(self):
        """Test creating a provider config."""
        config = ProviderConfig(
            name="test-provider",
            api_key="test-key-123",
            base_url="https://api.test.com/v1",
            model="test-model",
            is_primary=True,
        )

        assert config.name == "test-provider"
        assert config.api_key == "test-key-123"
        assert config.base_url == "https://api.test.com/v1"
        assert config.model == "test-model"
        assert config.is_primary is True

    def test_provider_config_defaults(self):
        """Test provider config with default values."""
        config = ProviderConfig(
            name="test-provider",
            api_key="test-key",
            base_url="https://api.test.com",
        )

        assert config.model == "MiniMax-Text-01"
        assert config.is_primary is False


class TestLLMGateway:
    """Tests for LLMGateway with fallback routing."""

    @pytest.fixture
    def primary_provider(self):
        """Create primary provider config."""
        return ProviderConfig(
            name="primary",
            api_key="primary-key",
            base_url="https://api.primary.com/v1",
            model="primary-model",
            is_primary=True,
        )

    @pytest.fixture
    def fallback_provider(self):
        """Create fallback provider config."""
        return ProviderConfig(
            name="fallback",
            api_key="fallback-key",
            base_url="https://api.fallback.com/v1",
            model="fallback-model",
            is_primary=False,
        )

    @pytest.fixture
    def gateway_with_providers(self, primary_provider, fallback_provider):
        """Create gateway with two providers."""
        return LLMGateway(
            providers=[primary_provider, fallback_provider],
            failure_threshold=3,
        )

    @pytest.fixture
    def mock_minimax_gateway(self):
        """Create mock MiniMax gateway."""
        mock = AsyncMock()
        mock.api_key = "test-key"
        mock.base_url = "https://api.test.com"
        mock.model = "test-model"
        return mock

    def test_gateway_initialization(self, primary_provider, fallback_provider):
        """Test gateway initializes with providers."""
        gateway = LLMGateway(providers=[primary_provider, fallback_provider])

        assert len(gateway.providers) == 2
        assert gateway.primary_provider == primary_provider
        assert len(gateway._circuit_breakers) == 2
        assert len(gateway._provider_gateways) == 2

    def test_gateway_initialization_empty(self):
        """Test gateway initializes with no providers."""
        gateway = LLMGateway()

        assert len(gateway.providers) == 0
        assert gateway.primary_provider is None

    def test_get_circuit_breaker(self, gateway_with_providers):
        """Test getting circuit breaker for a provider."""
        breaker = gateway_with_providers.get_circuit_breaker("primary")

        assert breaker is not None
        assert breaker.name == "llm_provider_primary"

    def test_get_circuit_breaker_unknown(self, gateway_with_providers):
        """Test getting circuit breaker for unknown provider."""
        breaker = gateway_with_providers.get_circuit_breaker("unknown")

        assert breaker is None

    def test_get_health_status(self, gateway_with_providers):
        """Test getting health status of all providers."""
        status = gateway_with_providers.get_health_status()

        assert "primary" in status
        assert "fallback" in status
        assert status["primary"]["state"] == "healthy"
        assert status["fallback"]["state"] == "healthy"

    @pytest.mark.asyncio
    async def test_generate_single_provider_success(
        self, gateway_with_providers, primary_provider
    ):
        """Test successful generate with single provider."""
        mock_response = LLMResponse(
            text="Hello, world!",
            model="primary-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )

        with patch.object(
            gateway_with_providers._provider_gateways["primary"],
            "generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await gateway_with_providers.generate("Hello")

            assert result.text == "Hello, world!"
            assert result.model == "primary-model"

    @pytest.mark.asyncio
    async def test_generate_fallback_on_failure(
        self, primary_provider, fallback_provider
    ):
        """Test fallback to backup provider when primary fails."""
        gateway = LLMGateway(providers=[primary_provider, fallback_provider])

        mock_primary_response = ProviderError("Primary failed", provider="primary")
        mock_fallback_response = LLMResponse(
            text="Fallback response",
            model="fallback-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )

        with patch.object(
            gateway._provider_gateways["primary"],
            "generate",
            new_callable=AsyncMock,
            side_effect=mock_primary_response,
        ), patch.object(
            gateway._provider_gateways["fallback"],
            "generate",
            new_callable=AsyncMock,
            return_value=mock_fallback_response,
        ):
            result = await gateway.generate("Hello")

            assert result.text == "Fallback response"
            assert result.model == "fallback-model"

    @pytest.mark.asyncio
    async def test_generate_preferred_provider_first(
        self, primary_provider, fallback_provider
    ):
        """Test preferred provider is tried first."""
        gateway = LLMGateway(providers=[primary_provider, fallback_provider])

        mock_response = LLMResponse(
            text="Preferred response",
            model="fallback-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )

        with patch.object(
            gateway._provider_gateways["fallback"],
            "generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ), patch.object(
            gateway._provider_gateways["primary"],
            "generate",
            new_callable=AsyncMock,
            side_effect=ProviderError("Should not be called"),
        ):
            result = await gateway.generate(
                "Hello", preferred_provider="fallback"
            )

            assert result.text == "Preferred response"

    @pytest.mark.asyncio
    async def test_generate_all_providers_fail(self, primary_provider):
        """Test error when all providers fail."""
        gateway = LLMGateway(providers=[primary_provider])

        with patch.object(
            gateway._provider_gateways["primary"],
            "generate",
            new_callable=AsyncMock,
            side_effect=ProviderError("All failed"),
        ):
            with pytest.raises(ProviderError) as exc_info:
                await gateway.generate("Hello")

            assert "All LLM providers failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_embed_fallback_on_failure(
        self, primary_provider, fallback_provider
    ):
        """Test fallback to backup provider when primary embed fails."""
        gateway = LLMGateway(providers=[primary_provider, fallback_provider])

        mock_fallback_response = EmbedResponse(
            embeddings=[[0.1, 0.2, 0.3]],
            model="fallback-model",
            usage={"total_tokens": 10},
        )

        with patch.object(
            gateway._provider_gateways["primary"],
            "embed",
            new_callable=AsyncMock,
            side_effect=ProviderError("Primary embed failed"),
        ), patch.object(
            gateway._provider_gateways["fallback"],
            "embed",
            new_callable=AsyncMock,
            return_value=mock_fallback_response,
        ):
            result = await gateway.embed(["Hello", "World"])

            assert len(result.embeddings) == 1
            assert result.model == "fallback-model"

    @pytest.mark.asyncio
    async def test_stream_generate_fallback(
        self, primary_provider, fallback_provider
    ):
        """Test streaming with fallback on failure."""
        gateway = LLMGateway(providers=[primary_provider, fallback_provider])

        async def primary_stream(*args, **kwargs):
            raise ProviderError("Primary streaming failed")

        async def fallback_stream(*args, **kwargs):
            yield "Hello"
            yield " "
            yield "World"

        with patch.object(
            gateway._provider_gateways["primary"],
            "stream_generate",
            side_effect=primary_stream,
        ), patch.object(
            gateway._provider_gateways["fallback"],
            "stream_generate",
            side_effect=fallback_stream,
        ):
            chunks = []
            async for chunk in gateway.stream_generate("Hello"):
                chunks.append(chunk)

            assert "".join(chunks) == "Hello World"

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_skips_provider(
        self, primary_provider, fallback_provider
    ):
        """Test provider is skipped when circuit breaker is open."""
        gateway = LLMGateway(providers=[primary_provider, fallback_provider])

        # Open the primary provider's circuit breaker
        gateway._circuit_breakers["primary"]._state = CircuitState.OPEN

        mock_fallback_response = LLMResponse(
            text="Fallback response",
            model="fallback-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )

        with patch.object(
            gateway._provider_gateways["fallback"],
            "generate",
            new_callable=AsyncMock,
            return_value=mock_fallback_response,
        ):
            result = await gateway.generate("Hello")

            assert result.text == "Fallback response"

    @pytest.mark.asyncio
    async def test_provider_health_tracking_on_success(
        self, gateway_with_providers, primary_provider
    ):
        """Test health tracking records success."""
        mock_response = LLMResponse(
            text="Success",
            model="primary-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )

        with patch.object(
            gateway_with_providers._provider_gateways["primary"],
            "generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            await gateway_with_providers.generate("Hello")

        status = gateway_with_providers.get_health_status()
        assert status["primary"]["state"] == "healthy"
        assert status["primary"]["last_success"] is not None

    @pytest.mark.asyncio
    async def test_provider_health_tracking_on_failure(
        self, gateway_with_providers, primary_provider
    ):
        """Test health tracking records failures."""
        with patch.object(
            gateway_with_providers._provider_gateways["primary"],
            "generate",
            new_callable=AsyncMock,
            side_effect=ProviderError("Test failure"),
        ):
            try:
                await gateway_with_providers.generate("Hello")
            except ProviderError:
                pass

        status = gateway_with_providers.get_health_status()
        assert status["primary"]["failure_count"] >= 1
        assert status["primary"]["last_failure"] is not None


class TestGatewayFactory:
    """Tests for GatewayFactory."""

    def test_from_settings_no_fallback(self):
        """Test creating gateway from settings without fallback."""
        with patch("app.core.settings.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = "test-key"
            mock_settings.OPENAI_BASE_URL = "https://api.test.com"
            mock_settings.OPENAI_MODEL = "test-model"

            gateway = GatewayFactory.from_settings()

            assert len(gateway.providers) == 1
            assert gateway.providers[0].name == "primary"
            assert gateway.providers[0].api_key == "test-key"

    def test_from_settings_with_fallback(self):
        """Test creating gateway from settings with fallback."""
        with patch("app.core.settings.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = "primary-key"
            mock_settings.OPENAI_BASE_URL = "https://api.primary.com"
            mock_settings.OPENAI_MODEL = "primary-model"

            gateway = GatewayFactory.from_settings(
                fallback_api_key="fallback-key",
                fallback_base_url="https://api.fallback.com",
                fallback_model="fallback-model",
            )

            assert len(gateway.providers) == 2
            assert gateway.providers[0].name == "primary"
            assert gateway.providers[1].name == "fallback"

    def test_create_with_openai_fallback(self):
        """Test creating gateway with MiniMax primary and OpenAI fallback."""
        gateway = GatewayFactory.create_with_openai_fallback(
            minimax_api_key="minimax-key",
            openai_api_key="openai-key",
        )

        assert len(gateway.providers) == 2
        assert gateway.providers[0].name == "minimax"
        assert gateway.providers[1].name == "openai"

    def test_create_with_openai_fallback_no_openai_key(self):
        """Test creating gateway without OpenAI key doesn't add fallback."""
        gateway = GatewayFactory.create_with_openai_fallback(
            minimax_api_key="minimax-key",
        )

        assert len(gateway.providers) == 1
        assert gateway.providers[0].name == "minimax"


class TestLLMGatewayLogging:
    """Tests for logging behavior in LLM Gateway."""

    @pytest.fixture
    def provider(self):
        """Create single provider config."""
        return ProviderConfig(
            name="test-provider",
            api_key="test-key",
            base_url="https://api.test.com/v1",
            model="test-model",
        )

    @pytest.fixture
    def gateway(self, provider):
        """Create gateway with single provider."""
        return LLMGateway(providers=[provider])

    @pytest.mark.asyncio
    async def test_logs_provider_switch(self, gateway, caplog):
        """Test that provider switches are logged."""
        mock_response = LLMResponse(
            text="Success",
            model="test-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )

        with patch.object(
            gateway._provider_gateways["test-provider"],
            "generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ), caplog.at_level("INFO"):
            await gateway.generate("Hello")

            assert any("succeeded with provider" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_provider_with_open_circuit_is_skipped(self, gateway, caplog):
        """Test that provider with open circuit breaker is skipped."""
        # Open the circuit breaker
        gateway._circuit_breakers["test-provider"]._state = CircuitState.OPEN

        # Provider should be skipped, not tried
        assert CircuitState.OPEN == gateway._circuit_breakers["test-provider"].state

        mock_response = LLMResponse(
            text="Success",
            model="test-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )

        with patch.object(
            gateway._provider_gateways["test-provider"],
            "generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            # All providers failed since the only one has open circuit
            with pytest.raises(ProviderError):
                await gateway.generate("Hello")


class TestLLMGatewayPromptCache:
    """Tests for prompt caching in LLM Gateway."""

    @pytest.fixture
    def provider(self):
        """Create single provider config."""
        return ProviderConfig(
            name="test-provider",
            api_key="test-key",
            base_url="https://api.test.com/v1",
            model="test-model",
        )

    @pytest.fixture
    def mock_prompt_cache(self):
        """Create mock prompt cache service."""
        mock = AsyncMock()
        mock.get_cached_response = AsyncMock(return_value=None)
        mock.cache_response = AsyncMock()
        return mock

    @pytest.mark.asyncio
    async def test_generate_checks_cache_before_provider_call(
        self, provider, mock_prompt_cache, caplog
    ):
        """Test that cache is checked before making LLM API call."""
        gateway = LLMGateway(providers=[provider], prompt_cache=mock_prompt_cache)

        mock_response = LLMResponse(
            text="Hello, world!",
            model="test-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )

        with patch.object(
            gateway._provider_gateways["test-provider"],
            "generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            await gateway.generate("Hello", tenant_id="tenant-123")

            # Verify cache was checked first
            mock_prompt_cache.get_cached_response.assert_called_once()
            call_args = mock_prompt_cache.get_cached_response.call_args
            assert call_args[0][0] == "Hello"  # prompt
            assert call_args[0][1] == "tenant-123"  # tenant_id

    @pytest.mark.asyncio
    async def test_generate_returns_cached_response_on_hit(
        self, provider, mock_prompt_cache
    ):
        """Test that cached response is returned on cache hit."""
        gateway = LLMGateway(providers=[provider], prompt_cache=mock_prompt_cache)

        # Set up cache to return a cached response
        cached_text = "Cached response"
        mock_prompt_cache.get_cached_response = AsyncMock(return_value=cached_text)

        # Mock the provider gateway generate method at the instance level
        with patch.object(
            gateway._provider_gateways["test-provider"],
            "generate",
            new_callable=AsyncMock,
        ) as mock_generate:
            result = await gateway.generate("Hello", tenant_id="tenant-123")

            assert result.text == cached_text
            assert result.finish_reason == "cached"
            # Provider should NOT be called when there's a cache hit
            mock_generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_caches_response_on_miss(
        self, provider, mock_prompt_cache, caplog
    ):
        """Test that response is cached after successful provider call."""
        gateway = LLMGateway(providers=[provider], prompt_cache=mock_prompt_cache)

        mock_response = LLMResponse(
            text="Fresh response",
            model="test-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )

        with patch.object(
            gateway._provider_gateways["test-provider"],
            "generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            await gateway.generate("Hello", tenant_id="tenant-123")

            # Verify cache was checked (returned None = miss)
            mock_prompt_cache.get_cached_response.assert_called_once()

            # Verify response was cached
            mock_prompt_cache.cache_response.assert_called_once_with(
                "Hello", "tenant-123", "test-model", "Fresh response"
            )

    @pytest.mark.asyncio
    async def test_generate_without_tenant_id_skips_cache(
        self, provider, mock_prompt_cache
    ):
        """Test that cache is skipped when tenant_id is not provided."""
        gateway = LLMGateway(providers=[provider], prompt_cache=mock_prompt_cache)

        mock_response = LLMResponse(
            text="Hello, world!",
            model="test-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )

        with patch.object(
            gateway._provider_gateways["test-provider"],
            "generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            await gateway.generate("Hello")  # No tenant_id

            # Cache should NOT be checked
            mock_prompt_cache.get_cached_response.assert_not_called()

            # Response should NOT be cached
            mock_prompt_cache.cache_response.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_logs_cache_hit(self, provider, mock_prompt_cache, caplog):
        """Test that cache hit is logged."""
        gateway = LLMGateway(providers=[provider], prompt_cache=mock_prompt_cache)

        cached_text = "Cached response"
        mock_prompt_cache.get_cached_response = AsyncMock(return_value=cached_text)

        with caplog.at_level("INFO"):
            await gateway.generate("Hello", tenant_id="tenant-123")

            assert any("cache_hit" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_generate_with_different_model_uses_model_in_cache_key(
        self, provider, mock_prompt_cache
    ):
        """Test that model is included in cache key via params."""
        gateway = LLMGateway(providers=[provider], prompt_cache=mock_prompt_cache)

        mock_response = LLMResponse(
            text="Response",
            model="custom-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )

        with patch.object(
            gateway._provider_gateways["test-provider"],
            "generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            await gateway.generate("Hello", tenant_id="tenant-123", params={"model": "custom-model"})

            # Verify cache check used the correct model
            call_args = mock_prompt_cache.get_cached_response.call_args
            assert call_args[0][2] == "custom-model"  # model parameter

    @pytest.mark.asyncio
    async def test_generate_no_cache_when_cache_not_configured(
        self, provider
    ):
        """Test that cache is not used when prompt_cache is None."""
        gateway = LLMGateway(providers=[provider], prompt_cache=None)

        mock_response = LLMResponse(
            text="Hello, world!",
            model="test-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )

        with patch.object(
            gateway._provider_gateways["test-provider"],
            "generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await gateway.generate("Hello", tenant_id="tenant-123")

            # Should still work and return the response
            assert result.text == "Hello, world!"

    def test_gateway_prompt_cache_property(self, provider, mock_prompt_cache):
        """Test prompt_cache property accessor."""
        gateway = LLMGateway(providers=[provider], prompt_cache=mock_prompt_cache)

        assert gateway.prompt_cache is mock_prompt_cache

    def test_gateway_prompt_cache_property_none_when_not_set(self, provider):
        """Test prompt_cache property returns None when not configured."""
        gateway = LLMGateway(providers=[provider])

        assert gateway.prompt_cache is None