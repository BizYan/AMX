"""Runtime security settings validation tests."""

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/postgres")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ARQ_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("JWT_SECRET_KEY", "test-runtime-security-secret")


@pytest.mark.parametrize(
    "secret",
    [
        "",
        "test-secret",
        "change-me-in-production",
        "your-super-secret-jwt-key-change-in-production",
    ],
)
def test_production_rejects_missing_placeholder_or_short_jwt_secret(secret):
    from app.core.runtime_security import validate_runtime_security_settings

    with patch("app.core.runtime_security.settings") as mock_settings:
        mock_settings.ENVIRONMENT = "production"
        mock_settings.JWT_SECRET_KEY = secret

        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            validate_runtime_security_settings()


def test_production_accepts_real_jwt_secret():
    from app.core.runtime_security import validate_runtime_security_settings

    with patch("app.core.runtime_security.settings") as mock_settings:
        mock_settings.ENVIRONMENT = "production"
        mock_settings.JWT_SECRET_KEY = "prod-jwt-secret-with-at-least-32-bytes-2026"

        validate_runtime_security_settings()


def test_non_production_allows_placeholder_jwt_secret():
    from app.core.runtime_security import validate_runtime_security_settings

    with patch("app.core.runtime_security.settings") as mock_settings:
        mock_settings.ENVIRONMENT = "development"
        mock_settings.JWT_SECRET_KEY = "test-secret"

        validate_runtime_security_settings()
