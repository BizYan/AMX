"""Provider credential persistence and redaction boundary."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from typing import Any

REDACTED_SECRET = "[REDACTED]"

RAW_CREDENTIAL_KEYS = {
    "api_key",
    "token",
    "access_token",
    "secret",
    "service_key",
    "password",
    "client_secret",
    "private_key",
    "refresh_token",
}

CREDENTIAL_REF_KEYS = (
    "credential_ref",
    "secret_ref",
    "runtime_secret_ref",
    "env_secret_ref",
)

_ENV_REF_PATTERN = re.compile(r"^env:([A-Z_][A-Z0-9_]*)$")
_BEARER_PATTERN = re.compile(r"(?i)\b(Bearer\s+)([A-Za-z0-9._~+/=-]{6,})")
_ASSIGNMENT_PATTERN = re.compile(
    rf"(?i)\b({'|'.join(re.escape(key) for key in RAW_CREDENTIAL_KEYS)})"
    r"(\s*[:=]\s*)(['\"]?)([^'\"\s,;}}]+)"
)


def _normalize_key(key: Any) -> str:
    return str(key).strip().lower()


def find_raw_credential_paths(value: Any, prefix: str = "config") -> list[str]:
    """Return JSON paths that would persist raw credential material."""
    paths: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}"
            if _normalize_key(key) in RAW_CREDENTIAL_KEYS and nested not in (None, ""):
                paths.append(path)
            paths.extend(find_raw_credential_paths(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(find_raw_credential_paths(nested, f"{prefix}[{index}]"))
    return paths


def validate_provider_config_boundary(config: dict[str, Any] | None) -> dict[str, Any]:
    """Reject provider config that attempts to persist raw credentials."""
    config = config or {}
    raw_paths = find_raw_credential_paths(config)
    if raw_paths:
        raise ValueError(
            "Provider config must not persist raw credentials; use credential_ref/secret_ref. "
            f"Rejected fields: {', '.join(raw_paths)}"
        )
    return config


def redact_secrets(value: Any) -> Any:
    """Recursively redact legacy credential material before API/log/audit output."""
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, nested in value.items():
            if _normalize_key(key) in RAW_CREDENTIAL_KEYS and nested not in (None, ""):
                redacted[key] = REDACTED_SECRET
            else:
                redacted[key] = redact_secrets(nested)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return sanitize_error_message(value)
    return value


def sanitize_error_message(message: str | None) -> str | None:
    """Scrub credential-like values from strings persisted or returned as evidence."""
    if message is None:
        return None
    sanitized = _BEARER_PATTERN.sub(rf"\1{REDACTED_SECRET}", str(message))
    sanitized = _ASSIGNMENT_PATTERN.sub(rf"\1\2\3{REDACTED_SECRET}", sanitized)
    return sanitized


def provider_credential_ref(config: dict[str, Any] | None) -> str:
    """Return the configured non-secret credential reference."""
    config = config or {}
    for key in CREDENTIAL_REF_KEYS:
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def resolve_credential_ref(reference: str) -> str:
    """Resolve approved runtime credential references.

    Only environment references are supported here. Other secret-manager reference
    schemes remain non-secret metadata until a concrete resolver is added.
    """
    match = _ENV_REF_PATTERN.match(reference.strip())
    if not match:
        return ""
    return os.getenv(match.group(1), "").strip()


def provider_resolved_credential(provider: Any) -> str:
    """Resolve a provider credential without reading raw persisted secret fields."""
    return resolve_credential_ref(provider_credential_ref(getattr(provider, "config_json", None)))


def provider_runtime_config(provider: Any, *, credential_key: str = "api_key") -> dict[str, Any]:
    """Build ephemeral provider runtime config with a resolved credential.

    The returned dict is never written back to Provider.config_json.
    """
    config = deepcopy(getattr(provider, "config_json", None) or {})
    credential = provider_resolved_credential(provider)
    if credential:
        config[credential_key] = credential
    return config
