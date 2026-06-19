"""Provider capability and production-readiness helpers."""

from typing import Any

from app.domains.providers.credential_boundary import provider_resolved_credential
from app.domains.providers.models import Provider, ProviderStatus

SANDBOX_SECRET_VALUES = {
    "test_api_key",
    "test-api-key",
    "test-key",
    "test_key",
    "sandbox",
    "sandbox-key",
    "mock",
    "mock-key",
    "placeholder",
    "placeholder-key",
    "demo",
    "demo-key",
    "fake",
    "fake-key",
}
SANDBOX_NAME_MARKERS = ("sandbox",)
MOCK_NAME_MARKERS = ("mock", "test", "demo", "placeholder", "fake")
SANDBOX_SECRET_PREFIXES = ("sandbox-", "sandbox_", "sandbox.")
MOCK_SECRET_PREFIXES = (
    "demo-",
    "demo_",
    "fake-",
    "fake_",
    "mock-",
    "mock_",
    "placeholder-",
    "placeholder_",
    "sk-test",
    "test-",
    "test_",
)


def config_text(config: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty string value for any config key."""
    for key in keys:
        value = config.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def provider_secret_value(provider: Provider) -> str:
    """Return the runtime credential resolved from a non-secret reference."""
    return provider_resolved_credential(provider)


def is_sandbox_provider(provider: Provider) -> bool:
    """Whether a provider is configured only for sandbox/mock/demo use."""
    return provider_fake_configuration_kind(provider) in {"sandbox", "mock"}


def provider_fake_configuration_kind(provider: Provider) -> str | None:
    """Return sandbox/mock when provider config is not production evidence."""
    config = provider.config_json or {}
    api_key = provider_secret_value(provider).lower()
    provider_name_lower = (provider.name or "").lower()
    configured_mode = config_text(config, "mode", "environment", "profile").lower()

    if configured_mode == "sandbox" or any(marker in provider_name_lower for marker in SANDBOX_NAME_MARKERS):
        return "sandbox"
    if configured_mode in {"mock", "test", "demo", "placeholder", "fake"} or any(
        marker in provider_name_lower for marker in MOCK_NAME_MARKERS
    ):
        return "mock"
    if api_key:
        if api_key == "sandbox" or api_key.startswith(SANDBOX_SECRET_PREFIXES):
            return "sandbox"
        if api_key in SANDBOX_SECRET_VALUES or api_key.startswith(MOCK_SECRET_PREFIXES):
            return "mock"

    return None


def is_live_configured(provider: Provider) -> bool:
    """Whether a provider can be treated as live production capability evidence."""
    return (
        provider.status == ProviderStatus.ACTIVE.value
        and bool(provider_secret_value(provider))
        and not is_sandbox_provider(provider)
    )
