"""GitNexus runtime configuration helpers."""

from dataclasses import dataclass
from typing import Any


ENDPOINT_KEYS = ("endpoint", "base_url", "server_url", "api_url", "url")
SECRET_KEYS = ("api_key", "service_key", "token", "access_token", "secret")


@dataclass(frozen=True)
class GitNexusRuntimeConfig:
    endpoint: str
    api_key: str | None
    health_path: str
    timeout: float


def _first_string(config: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_path(value: Any, default: str) -> str:
    path = value if isinstance(value, str) and value.strip() else default
    path = path.strip()
    return path if path.startswith("/") else f"/{path}"


def load_gitnexus_runtime_config(config: dict[str, Any] | None) -> GitNexusRuntimeConfig:
    """Normalize AMX GitNexus provider config for all runtime call sites."""
    raw_config = config or {}
    endpoint = (_first_string(raw_config, ENDPOINT_KEYS) or "http://localhost:8001").rstrip("/")
    api_key = _first_string(raw_config, SECRET_KEYS)
    health_path = _normalize_path(raw_config.get("health_path"), "/api/health")

    timeout_value = raw_config.get("timeout", 30)
    try:
        timeout = float(timeout_value)
    except (TypeError, ValueError):
        timeout = 30.0

    return GitNexusRuntimeConfig(
        endpoint=endpoint,
        api_key=api_key,
        health_path=health_path,
        timeout=timeout,
    )
