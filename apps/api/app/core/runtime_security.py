"""Runtime security validation for production startup."""

from app.core.settings import settings


MINIMUM_PRODUCTION_JWT_SECRET_LENGTH = 32

UNSAFE_JWT_SECRETS = {
    "",
    "change-me",
    "change-me-in-production",
    "changeme",
    "development-secret",
    "dev-secret",
    "jwt-secret",
    "secret",
    "test",
    "test-secret",
    "your-super-secret-jwt-key-change-in-production",
}
UNSAFE_JWT_SECRET_PREFIXES = (
    "demo-",
    "fake-",
    "mock-",
    "placeholder-",
    "sandbox-",
    "test-",
)


def _is_production_environment() -> bool:
    return str(getattr(settings, "ENVIRONMENT", "development")).strip().lower() == "production"


def validate_runtime_security_settings() -> None:
    """Reject unsafe production settings before startup side effects."""
    if not _is_production_environment():
        return

    jwt_secret = str(settings.JWT_SECRET_KEY or "").strip()
    jwt_secret_lower = jwt_secret.lower()
    if (
        jwt_secret_lower in UNSAFE_JWT_SECRETS
        or jwt_secret_lower.startswith(UNSAFE_JWT_SECRET_PREFIXES)
        or len(jwt_secret) < MINIMUM_PRODUCTION_JWT_SECRET_LENGTH
    ):
        raise RuntimeError("JWT_SECRET_KEY must be a real non-placeholder secret in production")
