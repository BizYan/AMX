"""LLM Gateway with Provider Fallback Routing

Multi-provider gateway that automatically falls back to backup providers
on failure, with circuit breaker integration for fault isolation.
"""

import asyncio
import logging
from typing import Any, AsyncIterator

from app.domains.providers.contracts import LLMResponse, EmbedResponse, ProviderError
from app.integrations.llm.minimax_gateway import MiniMaxGateway
from app.services.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    get_provider_circuit_breaker,
)

logger = logging.getLogger(__name__)


class ProviderConfig:
    """Configuration for a single LLM provider."""

    def __init__(
        self,
        name: str,
        api_key: str,
        base_url: str,
        model: str = "MiniMax-Text-01",
        is_primary: bool = False,
    ):
        self.name = name
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.is_primary = is_primary


class LLMGateway:
    """LLM Gateway with automatic provider fallback routing.

    Wraps multiple LLM providers and automatically routes requests to backup
    providers when the primary provider fails or its circuit breaker opens.

    Features:
    - Primary and fallback provider configuration
    - Automatic fallback on failure or circuit breaker open
    - Per-provider circuit breaker isolation
    - Health tracking and provider switching logs
    - Non-breaking addition of new providers
    - Optional prompt caching to reduce API costs

    Example:
        gateway = LLMGateway()
        response = await gateway.generate("Hello, world!", tenant_id="tenant-123")
    """

    def __init__(
        self,
        providers: list[ProviderConfig] | None = None,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 3,
        prompt_cache: Any = None,
    ):
        """Initialize LLM Gateway with fallback routing.

        Args:
            providers: List of provider configurations, ordered by priority.
                      First provider is primary, rest are fallbacks.
            failure_threshold: Failures before opening circuit breaker
            recovery_timeout: Seconds before attempting circuit recovery
            half_open_max_calls: Test calls allowed in half-open state
            prompt_cache: Optional PromptCacheService instance for response caching
        """
        self._providers = providers or []
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls
        self._prompt_cache = prompt_cache
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._provider_gateways: dict[str, MiniMaxGateway] = {}
        self._health_status: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

        # Initialize circuit breakers for each provider
        for provider in self._providers:
            self._circuit_breakers[provider.name] = CircuitBreaker(
                name=f"llm_provider_{provider.name}",
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                half_open_max_calls=half_open_max_calls,
            )
            self._provider_gateways[provider.name] = MiniMaxGateway(
                api_key=provider.api_key,
                base_url=provider.base_url,
                model=provider.model,
            )
            self._health_status[provider.name] = {
                "state": "healthy",
                "failure_count": 0,
                "last_failure": None,
                "last_success": None,
            }

        logger.info(
            f"LLM Gateway initialized with {len(self._providers)} providers: "
            f"{[p.name for p in self._providers]}"
        )

    @property
    def providers(self) -> list[ProviderConfig]:
        """Get list of configured providers."""
        return self._providers

    @property
    def prompt_cache(self) -> Any:
        """Get prompt cache service if configured."""
        return self._prompt_cache

    @property
    def primary_provider(self) -> ProviderConfig | None:
        """Get primary provider configuration."""
        return self._providers[0] if self._providers else None

    def get_circuit_breaker(self, provider_name: str) -> CircuitBreaker | None:
        """Get circuit breaker for a provider.

        Args:
            provider_name: Name of the provider

        Returns:
            CircuitBreaker instance or None if provider not found
        """
        return self._circuit_breakers.get(provider_name)

    def get_health_status(self) -> dict[str, dict[str, Any]]:
        """Get health status of all providers.

        Returns:
            Dictionary mapping provider names to their health status
        """
        return {
            name: {
                "state": status["state"],
                "failure_count": status["failure_count"],
                "last_failure": status["last_failure"],
                "last_success": status["last_success"],
                "circuit_state": self._circuit_breakers[name].state.value
                if name in self._circuit_breakers
                else "unknown",
            }
            for name, status in self._health_status.items()
        }

    def _get_available_providers(self) -> list[ProviderConfig]:
        """Get providers in priority order, skipping those with open circuits.

        Returns:
            List of available providers
        """
        available = []
        for provider in self._providers:
            breaker = self._circuit_breakers.get(provider.name)
            if breaker is None or breaker.state != CircuitState.OPEN:
                available.append(provider)
        return available

    async def _call_provider(
        self,
        provider: ProviderConfig,
        method: str,
        *args,
        **kwargs,
    ) -> Any:
        """Call a specific provider method through its circuit breaker.

        Args:
            provider: Provider configuration
            method: Method name to call ("generate", "embed", "stream_generate")
            *args: Positional arguments for the method
            **kwargs: Keyword arguments for the method

        Returns:
            Result from the provider method

        Raises:
            ProviderError: If the call fails
        """
        breaker = self._circuit_breakers[provider.name]
        gateway = self._provider_gateways[provider.name]

        async def _call():
            method_func = getattr(gateway, method)
            return await method_func(*args, **kwargs)

        return await breaker.call(_call)

    async def _record_provider_success(self, provider_name: str) -> None:
        """Record successful call for a provider."""
        async with self._lock:
            if provider_name in self._health_status:
                self._health_status[provider_name]["state"] = "healthy"
                self._health_status[provider_name]["last_success"] = asyncio.get_event_loop().time()

    async def _record_provider_failure(self, provider_name: str, error: Exception) -> None:
        """Record failed call for a provider."""
        async with self._lock:
            if provider_name in self._health_status:
                self._health_status[provider_name]["failure_count"] += 1
                self._health_status[provider_name]["last_failure"] = asyncio.get_event_loop().time()
                if self._health_status[provider_name]["failure_count"] >= self._failure_threshold:
                    self._health_status[provider_name]["state"] = "degraded"

    async def generate(
        self,
        prompt: str,
        params: dict[str, Any] | None = None,
        stream: bool = False,
        preferred_provider: str | None = None,
        tenant_id: str | None = None,
    ) -> LLMResponse:
        """Generate text with automatic provider fallback.

        Tries providers in priority order until one succeeds.
        If preferred_provider is specified, tries that provider first.
        If prompt_cache is configured, checks cache before making API calls.

        Args:
            prompt: Input prompt text
            params: Generation parameters
            stream: Whether to stream the response
            preferred_provider: Provider name to try first
            tenant_id: Optional tenant ID for cache key generation

        Returns:
            LLMResponse with generated text

        Raises:
            ProviderError: If all providers fail
        """
        params = params or {}

        # Check prompt cache first if configured and tenant_id provided
        if self._prompt_cache and tenant_id:
            cached_response = await self._prompt_cache.get_cached_response(
                prompt, tenant_id, params.get("model", self.primary_provider.model if self.primary_provider else "default")
            )
            if cached_response is not None:
                logger.info(f"cache_hit: tenant={tenant_id}, model={params.get('model', 'default')}")
                # Return cached response wrapped in LLMResponse
                return LLMResponse(
                    text=cached_response,
                    model=params.get("model", self.primary_provider.model if self.primary_provider else "default"),
                    usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    finish_reason="cached",
                    raw_response=None,
                )

        # Determine provider order
        if preferred_provider:
            providers_to_try = [
                p for p in self._providers if p.name == preferred_provider
            ] + [p for p in self._providers if p.name != preferred_provider]
        else:
            providers_to_try = self._get_available_providers()

        last_error: Exception | None = None

        for provider in providers_to_try:
            try:
                logger.debug(f"Attempting generate with provider: {provider.name}")
                result = await self._call_provider(
                    provider, "generate", prompt, params, stream
                )
                await self._record_provider_success(provider.name)
                logger.info(f"Generate succeeded with provider: {provider.name}")

                # Cache the response if prompt_cache is configured and tenant_id provided
                if self._prompt_cache and tenant_id:
                    await self._prompt_cache.cache_response(
                        prompt, tenant_id, result.model, result.text
                    )
                    logger.debug(f"Cached response for tenant={tenant_id}")

                return result
            except CircuitOpenError as e:
                logger.warning(f"Circuit open for provider {provider.name}: {e}")
                last_error = e
                await self._record_provider_failure(provider.name, e)
            except ProviderError as e:
                logger.warning(f"Provider error from {provider.name}: {e}")
                last_error = e
                await self._record_provider_failure(provider.name, e)
            except Exception as e:
                logger.error(f"Unexpected error from provider {provider.name}: {e}")
                last_error = e
                await self._record_provider_failure(provider.name, e)

        # All providers failed
        error_msg = f"All LLM providers failed. Last error: {last_error}"
        logger.error(error_msg)
        raise ProviderError(message=error_msg, details={"providers_尝试": [p.name for p in providers_to_try]})

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
        preferred_provider: str | None = None,
    ) -> EmbedResponse:
        """Generate embeddings with automatic provider fallback.

        Tries providers in priority order until one succeeds.

        Args:
            texts: List of texts to embed
            model: Optional embedding model override
            preferred_provider: Provider name to try first

        Returns:
            EmbedResponse with embedding vectors

        Raises:
            ProviderError: If all providers fail
        """
        # Determine provider order
        if preferred_provider:
            providers_to_try = [
                p for p in self._providers if p.name == preferred_provider
            ] + [p for p in self._providers if p.name != preferred_provider]
        else:
            providers_to_try = self._get_available_providers()

        last_error: Exception | None = None

        for provider in providers_to_try:
            try:
                logger.debug(f"Attempting embed with provider: {provider.name}")
                result = await self._call_provider(provider, "embed", texts, model)
                await self._record_provider_success(provider.name)
                logger.info(f"Embed succeeded with provider: {provider.name}")
                return result
            except CircuitOpenError as e:
                logger.warning(f"Circuit open for provider {provider.name}: {e}")
                last_error = e
                await self._record_provider_failure(provider.name, e)
            except ProviderError as e:
                logger.warning(f"Provider error from {provider.name}: {e}")
                last_error = e
                await self._record_provider_failure(provider.name, e)
            except Exception as e:
                logger.error(f"Unexpected error from provider {provider.name}: {e}")
                last_error = e
                await self._record_provider_failure(provider.name, e)

        # All providers failed
        error_msg = f"All LLM providers failed for embedding. Last error: {last_error}"
        logger.error(error_msg)
        raise ProviderError(message=error_msg, details={"providers_tried": [p.name for p in providers_to_try]})

    async def stream_generate(
        self,
        prompt: str,
        params: dict[str, Any] | None = None,
        preferred_provider: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream generate text with automatic provider fallback.

        Args:
            prompt: Input prompt text
            params: Generation parameters
            preferred_provider: Provider name to try first

        Yields:
            Text chunks as they are generated

        Raises:
            ProviderError: If all providers fail
        """
        params = params or {}

        # Determine provider order
        if preferred_provider:
            providers_to_try = [
                p for p in self._providers if p.name == preferred_provider
            ] + [p for p in self._providers if p.name != preferred_provider]
        else:
            providers_to_try = self._get_available_providers()

        last_error: Exception | None = None

        for provider in providers_to_try:
            try:
                logger.debug(f"Attempting stream_generate with provider: {provider.name}")
                gateway = self._provider_gateways[provider.name]
                async for chunk in gateway.stream_generate(prompt, params):
                    await self._record_provider_success(provider.name)
                    yield chunk
                return
            except CircuitOpenError as e:
                logger.warning(f"Circuit open for provider {provider.name}: {e}")
                last_error = e
                await self._record_provider_failure(provider.name, e)
            except ProviderError as e:
                logger.warning(f"Provider error from {provider.name}: {e}")
                last_error = e
                await self._record_provider_failure(provider.name, e)
            except Exception as e:
                logger.error(f"Unexpected error from provider {provider.name}: {e}")
                last_error = e
                await self._record_provider_failure(provider.name, e)

        # All providers failed
        error_msg = f"All LLM providers failed for streaming. Last error: {last_error}"
        logger.error(error_msg)
        raise ProviderError(message=error_msg, details={"providers_tried": [p.name for p in providers_to_try]})

    async def close(self) -> None:
        """Close all provider connections."""
        for gateway in self._provider_gateways.values():
            await gateway.close()
        logger.info("LLM Gateway closed")

    def reset_circuit_breaker(self, provider_name: str | None = None) -> None:
        """Reset circuit breaker for a provider or all providers.

        Args:
            provider_name: Provider name to reset, or None for all
        """
        if provider_name:
            if provider_name in self._circuit_breakers:
                asyncio.create_task(self._circuit_breakers[provider_name].reset())
                logger.info(f"Circuit breaker reset for provider: {provider_name}")
        else:
            for name, breaker in self._circuit_breakers.items():
                asyncio.create_task(breaker.reset())
            logger.info("All circuit breakers reset")


# Import CircuitState for type checking
from app.services.circuit_breaker import CircuitState


class GatewayFactory:
    """Factory for creating LLM Gateway instances with configuration."""

    @staticmethod
    def from_settings(
        primary_api_key: str | None = None,
        primary_base_url: str | None = None,
        primary_model: str | None = None,
        fallback_api_key: str | None = None,
        fallback_base_url: str | None = None,
        fallback_model: str | None = None,
        **kwargs,
    ) -> LLMGateway:
        """Create LLM Gateway from settings or environment.

        Args:
            primary_api_key: Primary provider API key (defaults to settings.OPENAI_API_KEY)
            primary_base_url: Primary provider base URL
            primary_model: Primary model name
            fallback_api_key: Fallback provider API key (optional)
            fallback_base_url: Fallback provider base URL (optional)
            fallback_model: Fallback model name (optional)
            **kwargs: Additional arguments for LLM Gateway

        Returns:
            Configured LLMGateway instance
        """
        from app.core.settings import settings

        providers = []

        # Primary provider (MiniMax)
        providers.append(
            ProviderConfig(
                name="primary",
                api_key=primary_api_key or settings.OPENAI_API_KEY,
                base_url=primary_base_url or settings.OPENAI_BASE_URL,
                model=primary_model or settings.OPENAI_MODEL,
                is_primary=True,
            )
        )

        # Fallback provider (if configured)
        if fallback_api_key:
            providers.append(
                ProviderConfig(
                    name="fallback",
                    api_key=fallback_api_key,
                    base_url=fallback_base_url or "https://api.openai.com/v1",
                    model=fallback_model or "gpt-4o",
                    is_primary=False,
                )
            )

        return LLMGateway(providers=providers, **kwargs)

    @staticmethod
    def create_with_openai_fallback(
        minimax_api_key: str,
        minimax_base_url: str = "https://api.minimax.chat/v1",
        minimax_model: str = "MiniMax-Text-01",
        openai_api_key: str | None = None,
        openai_base_url: str = "https://api.openai.com/v1",
        openai_model: str = "gpt-4o",
        **kwargs,
    ) -> LLMGateway:
        """Create LLM Gateway with MiniMax as primary and OpenAI as fallback.

        Args:
            minimax_api_key: MiniMax API key
            minimax_base_url: MiniMax base URL
            minimax_model: MiniMax model
            openai_api_key: OpenAI API key (required for fallback)
            openai_base_url: OpenAI base URL
            openai_model: OpenAI model
            **kwargs: Additional arguments for LLM Gateway

        Returns:
            Configured LLMGateway with MiniMax primary and OpenAI fallback
        """
        providers = [
            ProviderConfig(
                name="minimax",
                api_key=minimax_api_key,
                base_url=minimax_base_url,
                model=minimax_model,
                is_primary=True,
            )
        ]

        if openai_api_key:
            providers.append(
                ProviderConfig(
                    name="openai",
                    api_key=openai_api_key,
                    base_url=openai_base_url,
                    model=openai_model,
                    is_primary=False,
                )
            )

        return LLMGateway(providers=providers, **kwargs)

    @staticmethod
    async def create_with_cache(
        primary_api_key: str | None = None,
        primary_base_url: str | None = None,
        primary_model: str | None = None,
        fallback_api_key: str | None = None,
        fallback_base_url: str | None = None,
        fallback_model: str | None = None,
        **kwargs,
    ) -> LLMGateway:
        """Create LLM Gateway with prompt caching enabled.

        Args:
            primary_api_key: Primary provider API key (defaults to settings.OPENAI_API_KEY)
            primary_base_url: Primary provider base URL
            primary_model: Primary model name
            fallback_api_key: Fallback provider API key (optional)
            fallback_base_url: Fallback provider base URL (optional)
            fallback_model: Fallback model name (optional)
            **kwargs: Additional arguments for LLM Gateway

        Returns:
            Configured LLMGateway with PromptCacheService integrated
        """
        from app.services.prompt_cache import get_prompt_cache_service

        prompt_cache = await get_prompt_cache_service()
        return GatewayFactory.from_settings(
            primary_api_key=primary_api_key,
            primary_base_url=primary_base_url,
            primary_model=primary_model,
            fallback_api_key=fallback_api_key,
            fallback_base_url=fallback_base_url,
            fallback_model=fallback_model,
            prompt_cache=prompt_cache,
            **kwargs,
        )