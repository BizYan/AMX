"""Circuit Breaker Service Module

Implements circuit breaker pattern for provider/llm calls with Redis sync.
"""

import asyncio
import time
from enum import Enum
from typing import Any, Callable, TypeVar, ParamSpec

from redis.asyncio import Redis

from app.core.settings import settings


T = TypeVar("T")
P = ParamSpec("P")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests flow through
    OPEN = "open"  # Failure threshold exceeded, requests are blocked
    HALF_OPEN = "half_open"  # Testing recovery, limited requests allowed


class CircuitBreaker:
    """Circuit breaker for protecting services from cascading failures.

    Implements the circuit breaker pattern with three states:
    - CLOSED: Normal operation, failures are tracked
    - OPEN: Circuit is tripped, requests are blocked
    - HALF_OPEN: Testing if service has recovered

    Thread-safe for single-instance. For distributed deployment, state
    is synchronized via Redis.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 3,
    ):
        """Initialize circuit breaker.

        Args:
            name: Identifier for this circuit breaker
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
            half_open_max_calls: Max test calls in half-open state
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0

        self._lock = asyncio.Lock()
        self._redis: Redis | None = None

    @property
    def state(self) -> CircuitState:
        """Get current circuit state.

        Returns:
            Current CircuitState
        """
        return self._state

    async def _sync_state_to_redis(self) -> None:
        """Synchronize state to Redis for distributed deployment."""
        if self._redis is None and settings.REDIS_URL:
            self._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)

        if self._redis:
            try:
                key = f"circuit_breaker:{self.name}"
                state_data = {
                    "state": self._state.value,
                    "failure_count": self._failure_count,
                    "success_count": self._success_count,
                    "last_failure_time": self._last_failure_time,
                    "half_open_calls": self._half_open_calls,
                }
                import json
                await self._redis.hset(key, mapping={k: json.dumps(v) for k, v in state_data.items()})
                await self._redis.expire(key, 300)  # 5 minute TTL
            except Exception:
                pass

    async def _load_state_from_redis(self) -> None:
        """Load state from Redis for distributed deployment."""
        if self._redis is None and settings.REDIS_URL:
            self._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)

        if self._redis:
            try:
                key = f"circuit_breaker:{self.name}"
                data = await self._redis.hgetall(key)
                if data:
                    import json
                    self._state = CircuitState(data.get("state", "closed"))
                    self._failure_count = int(data.get("failure_count", 0))
                    self._success_count = int(data.get("success_count", 0))
                    last_failure = data.get("last_failure_time")
                    self._last_failure_time = float(last_failure) if last_failure else None
                    self._half_open_calls = int(data.get("half_open_calls", 0))
            except Exception:
                pass

    async def call(self, func: Callable[P, Any], *args: P.args, **kwargs: P.kwargs) -> Any:
        """Execute function through circuit breaker.

        Args:
            func: Async function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Result from function

        Raises:
            Exception: Re-raises exception from function
            CircuitOpenError: If circuit is open and blocking requests
        """
        async with self._lock:
            # Check if circuit should transition
            await self._check_state_transition()

            # Block if circuit is open
            if self._state == CircuitState.OPEN:
                raise CircuitOpenError(f"Circuit {self.name} is open")

            # Allow limited calls in half-open state
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._half_open_max_calls:
                    raise CircuitOpenError(f"Circuit {self.name} is half-open, max calls reached")

        try:
            result = await func(*args, **kwargs)
            await self._record_success()
            return result
        except Exception as e:
            await self._record_failure()
            raise e

    async def _check_state_transition(self) -> None:
        """Check if circuit should transition states based on timeout."""
        if self._state == CircuitState.OPEN and self._last_failure_time:
            # Check if recovery timeout has passed
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._success_count = 0
                await self._sync_state_to_redis()

    async def _record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                self._half_open_calls += 1

                # If enough successes in half-open, close the circuit
                if self._success_count >= self.half_open_max_calls:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._half_open_calls = 0
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

            await self._sync_state_to_redis()

    async def _record_failure(self) -> None:
        """Record a failed call."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open opens the circuit again
                self._state = CircuitState.OPEN
                self._success_count = 0
            elif self._failure_count >= self.failure_threshold:
                # Threshold exceeded, open the circuit
                self._state = CircuitState.OPEN

            await self._sync_state_to_redis()

    async def reset(self) -> None:
        """Manually reset circuit breaker to closed state."""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            self._half_open_calls = 0
            await self._sync_state_to_redis()


class CircuitOpenError(Exception):
    """Exception raised when circuit is open and blocking requests."""

    pass


class ProviderCircuitBreaker:
    """Circuit breaker manager for LLM and provider calls.

    Maintains separate circuit breakers per provider for fault isolation.
    """

    def __init__(self):
        """Initialize provider circuit breaker manager."""
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    def get_breaker(
        self,
        provider_name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 3,
    ) -> CircuitBreaker:
        """Get or create circuit breaker for a provider.

        Args:
            provider_name: Name of the provider (e.g., "openai", "anthropic")
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
            half_open_max_calls: Max test calls in half-open state

        Returns:
            CircuitBreaker instance for the provider
        """
        if provider_name not in self._breakers:
            self._breakers[provider_name] = CircuitBreaker(
                name=f"provider_{provider_name}",
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                half_open_max_calls=half_open_max_calls,
            )
        return self._breakers[provider_name]

    async def call_provider(
        self,
        provider_name: str,
        func: Callable[P, Any],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> Any:
        """Execute a provider call through its circuit breaker.

        Args:
            provider_name: Name of the provider
            func: Async function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result from provider function
        """
        breaker = self.get_breaker(provider_name)
        return await breaker.call(func, *args, **kwargs)

    def get_all_states(self) -> dict[str, dict[str, Any]]:
        """Get state of all circuit breakers.

        Returns:
            Dictionary mapping provider names to their circuit states
        """
        return {
            name: {
                "state": breaker.state.value,
                "failure_count": breaker._failure_count,
                "last_failure_time": breaker._last_failure_time,
            }
            for name, breaker in self._breakers.items()
        }


# Global circuit breaker registry
_provider_circuit_breakers = ProviderCircuitBreaker()


def get_provider_circuit_breaker() -> ProviderCircuitBreaker:
    """Get global provider circuit breaker registry.

    Returns:
        Global ProviderCircuitBreaker instance
    """
    return _provider_circuit_breakers


# Convenience decorator for provider calls
def circuit_breaker_protected(provider_name: str):
    """Decorator to wrap provider calls with circuit breaker.

    Args:
        provider_name: Name of the provider

    Returns:
        Decorator function
    """
    def decorator(func: Callable[P, Any]) -> Callable[P, Any]:
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            breaker = get_provider_circuit_breaker()
            return await breaker.call_provider(provider_name, func, *args, **kwargs)
        return wrapper
    return decorator