"""Shared placeholder parsing and substitution helpers."""

from __future__ import annotations

import re
from typing import Any


PLACEHOLDER_PATTERN = re.compile(
    r"\{\{([A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff.-]*)\}\}"
)
RAW_PLACEHOLDER_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")


def is_valid_placeholder_name(name: str) -> bool:
    """Return whether a placeholder name follows the production template contract."""
    if not name or name[0].isdigit():
        return False
    if "{{" in name or "}}" in name:
        return False
    if any(char.isspace() for char in name):
        return False
    return all(char.isalnum() or char in {"_", "-", "."} for char in name)


def contains_placeholder(text: str | None) -> bool:
    """Return whether text contains a supported placeholder token."""
    return bool(text and PLACEHOLDER_PATTERN.search(text))


def extract_placeholders(text: str | None) -> list[str]:
    """Extract supported placeholder names from text."""
    if not text:
        return []
    return PLACEHOLDER_PATTERN.findall(text)


def extract_raw_placeholders(text: str | None) -> list[str]:
    """Extract raw placeholder bodies, including invalid names for validation evidence."""
    if not text:
        return []
    return RAW_PLACEHOLDER_PATTERN.findall(text)


def substitute_placeholders(content: str | None, variables: dict[str, Any]) -> str:
    """Substitute supported placeholders while preserving unresolved placeholders."""
    if not content:
        return ""

    normalized_variables = {str(key): value for key, value in (variables or {}).items()}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in normalized_variables:
            return match.group(0)
        return str(normalized_variables[name])

    return PLACEHOLDER_PATTERN.sub(replace, content)
