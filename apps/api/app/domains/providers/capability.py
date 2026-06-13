"""Provider capability and production-readiness helpers."""

from typing import Any

from app.domains.providers.models import Provider, ProviderStatus

SANDBOX_SECRET_VALUES = {
    "test_api_key",
    "test-key",
    "test_key",
    "sandbox",
    "mock",
    "placeholder",
}
SANDBOX_NAME_MARKERS = ("sandbox", "mock", "test", "demo")


def config_text(config: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty string value for any config key."""
    for key in keys:
        value = config.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def provider_secret_value(provider: Provider) -> str:
    """Return the credential-like value used to judge live configuration."""
    config = provider.config_json or {}
    return config_text(
        config,
        "api_key",
        "token",
        "access_token",
        "secret",
        "service_key",
    )


def is_sandbox_provider(provider: Provider) -> bool:
    """Whether a provider is configured only for sandbox/mock/demo use."""
    config = provider.config_json or {}
    api_key = provider_secret_value(provider).lower()
    provider_name_lower = (provider.name or "").lower()
    configured_mode = config_text(config, "mode", "environment", "profile").lower()

    return (
        (bool(api_key) and api_key in SANDBOX_SECRET_VALUES)
        or configured_mode in {"sandbox", "mock", "test", "demo"}
        or any(marker in provider_name_lower for marker in SANDBOX_NAME_MARKERS)
    )


def is_live_configured(provider: Provider) -> bool:
    """Whether a provider can be treated as live production capability evidence."""
    return (
        provider.status == ProviderStatus.ACTIVE.value
        and bool(provider_secret_value(provider))
        and not is_sandbox_provider(provider)
    )
