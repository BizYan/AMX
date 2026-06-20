"""Bootstrap Module

Creates the initial bootstrap admin user on application startup.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.core.settings import settings
from app.domains.providers.capability import (
    MOCK_SECRET_PREFIXES,
    SANDBOX_SECRET_PREFIXES,
    SANDBOX_SECRET_VALUES,
    is_live_configured,
)
from app.domains.providers.models import Provider, ProviderStatus, ProviderType
from app.domains.providers.registry import ProviderRegistry
from app.models.identity import Role, Tenant, User, UserRole


UNSAFE_BOOTSTRAP_PASSWORDS = {
    "",
    "admin",
    "admin123",
    "change-me",
    "change-me-in-production",
    "changeme",
    "consultant",
    "consultant123",
    "password",
    "password123",
    "test",
    "test-password",
    "test_password",
}
UNSAFE_RUNTIME_LLM_KEYS = SANDBOX_SECRET_VALUES | {
    "your-openai-api-key",
    "your-minimax-api-key",
    "openai-api-key",
}


def _is_production_environment() -> bool:
    return str(getattr(settings, "ENVIRONMENT", "development")).strip().lower() == "production"


def _validate_bootstrap_admin_config() -> None:
    if not _is_production_environment():
        return

    password = str(settings.BOOTSTRAP_ADMIN_PASSWORD or "").strip()
    if password.lower() in UNSAFE_BOOTSTRAP_PASSWORDS:
        raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD must be a real non-placeholder password in production")


def _runtime_llm_provider_config() -> dict[str, str] | None:
    api_key = getattr(settings, "OPENAI_API_KEY", "")
    if not isinstance(api_key, str) or not api_key.strip():
        return None
    normalized_key = api_key.strip().lower()
    if (
        normalized_key in UNSAFE_RUNTIME_LLM_KEYS
        or normalized_key.startswith(SANDBOX_SECRET_PREFIXES)
        or normalized_key.startswith(MOCK_SECRET_PREFIXES)
    ):
        return None

    base_url = getattr(settings, "OPENAI_BASE_URL", "")
    model = getattr(settings, "OPENAI_MODEL", "")
    return {
        "credential_ref": "env:OPENAI_API_KEY",
        "base_url": base_url if isinstance(base_url, str) and base_url.strip() else "https://api.minimax.chat/v1",
        "model": model if isinstance(model, str) and model.strip() else "MiniMax-Text-01",
        "source": "runtime_bootstrap",
    }


async def _ensure_runtime_llm_provider(db: AsyncSession, tenant_id) -> None:
    """Ensure configured runtime LLM credentials are visible to readiness gates."""
    config = _runtime_llm_provider_config()
    if config is None:
        return

    result = await db.execute(
        select(Provider).where(
            Provider.tenant_id == tenant_id,
            Provider.provider_type == ProviderType.LLM.value,
            Provider.deleted_at.is_(None),
        )
    )
    providers = list(result.scalars().all())
    if any(is_live_configured(provider) for provider in providers):
        return

    bootstrap_provider = next(
        (
            provider
            for provider in providers
            if (provider.config_json or {}).get("source") == "runtime_bootstrap"
            or provider.name == "Runtime LLM Provider"
        ),
        None,
    )
    capabilities = {"text_generation": True, "embedding": True}
    registry = ProviderRegistry(db)

    if bootstrap_provider is not None:
        bootstrap_provider.name = "Runtime LLM Provider"
        bootstrap_provider.status = ProviderStatus.ACTIVE.value
        bootstrap_provider.config_json = config
        bootstrap_provider.capabilities_json = capabilities
        await registry.create_version(
            provider_id=bootstrap_provider.id,
            config=config,
            capabilities=capabilities,
            set_active=True,
        )
        await db.flush()
        return

    await registry.register_provider(
        tenant_id=tenant_id,
        name="Runtime LLM Provider",
        provider_type=ProviderType.LLM,
        config=config,
        capabilities=capabilities,
    )


async def create_bootstrap_admin(db: AsyncSession) -> None:
    """Create the bootstrap admin user if not exists.

    Reads BOOTSTRAP_ADMIN_EMAIL, BOOTSTRAP_ADMIN_PASSWORD, BOOTSTRAP_ADMIN_NAME
    from settings and creates the admin user with a corresponding tenant.

    Args:
        db: Async database session
    """
    # Check if bootstrap admin email is configured
    if not settings.BOOTSTRAP_ADMIN_EMAIL:
        return

    _validate_bootstrap_admin_config()

    # Check if admin user already exists.
    result = await db.execute(
        select(User).where(User.email == settings.BOOTSTRAP_ADMIN_EMAIL)
    )
    existing_admin = result.scalar_one_or_none()

    if existing_admin is not None:
        await _ensure_runtime_llm_provider(db, existing_admin.tenant_id)
        await db.commit()
        return  # Admin already exists, skip

    # Create tenant for the admin
    tenant = Tenant(
        name="Default Tenant",
        slug="default",
    )
    db.add(tenant)
    await db.flush()  # Get the tenant ID

    # Create admin role
    admin_role = Role(
        name="admin",
        description="Administrator role with full permissions",
        permissions={"*": "*"},
        tenant_id=tenant.id,
    )
    db.add(admin_role)
    await db.flush()

    # Create admin user
    admin_user = User(
        email=settings.BOOTSTRAP_ADMIN_EMAIL,
        hashed_password=hash_password(settings.BOOTSTRAP_ADMIN_PASSWORD),
        full_name=settings.BOOTSTRAP_ADMIN_NAME,
        tenant_id=tenant.id,
        is_active=True,
    )
    db.add(admin_user)
    await db.flush()

    # Assign admin role to user
    user_role = UserRole(
        user_id=admin_user.id,
        role_id=admin_role.id,
    )
    db.add(user_role)

    await _ensure_runtime_llm_provider(db, tenant.id)

    await db.commit()
