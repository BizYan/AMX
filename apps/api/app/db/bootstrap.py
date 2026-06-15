"""Bootstrap Module

Creates the initial bootstrap admin user on application startup.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.core.settings import settings
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


def _is_production_environment() -> bool:
    return str(getattr(settings, "ENVIRONMENT", "development")).strip().lower() == "production"


def _validate_bootstrap_admin_config() -> None:
    if not _is_production_environment():
        return

    password = str(settings.BOOTSTRAP_ADMIN_PASSWORD or "").strip()
    if password.lower() in UNSAFE_BOOTSTRAP_PASSWORDS:
        raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD must be a real non-placeholder password in production")


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

    await db.commit()
