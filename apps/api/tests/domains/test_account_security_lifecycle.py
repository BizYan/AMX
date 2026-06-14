"""Account security lifecycle tests."""

import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-account-security-secret"

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401
import app.domains.identity.models  # noqa: F401
from app.core.security import hash_password
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.identity.schemas import LoginRequest, UserUpdate
from app.domains.identity.service import AuthService, UserService
from app.models.identity import Tenant, User


@pytest.fixture
async def db_session():
    deduplicate_indexes()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _seed(db_session):
    tenant = Tenant(id=uuid4(), name="Security Tenant", slug=f"security-{uuid4().hex[:8]}")
    user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email="security@example.com",
        full_name="Security User",
        hashed_password=hash_password("OldPassword-2026"),
        is_active=True,
    )
    db_session.add_all([tenant, user])
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_change_password_revokes_existing_token_and_allows_new_login(db_session):
    user = await _seed(db_session)
    service = AuthService(db_session)
    _, old_token = await service.login(LoginRequest(email=user.email, password="OldPassword-2026"))

    await service.change_password(user, "OldPassword-2026", "NewPassword-2026")

    assert user.security_version == 2
    assert user.password_changed_at is not None
    assert await service.get_current_user(old_token) is None
    _, new_token = await service.login(LoginRequest(email=user.email, password="NewPassword-2026"))
    assert await service.get_current_user(new_token) == user


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_or_reused_password(db_session):
    user = await _seed(db_session)
    service = AuthService(db_session)

    with pytest.raises(ValueError, match="Current password"):
        await service.change_password(user, "wrong-password", "NewPassword-2026")
    with pytest.raises(ValueError, match="different"):
        await service.change_password(user, "OldPassword-2026", "OldPassword-2026")


@pytest.mark.asyncio
async def test_revoke_sessions_invalidates_current_token(db_session):
    user = await _seed(db_session)
    service = AuthService(db_session)
    _, token = await service.login(LoginRequest(email=user.email, password="OldPassword-2026"))

    await service.revoke_all_sessions(user)

    assert await service.get_current_user(token) is None


@pytest.mark.asyncio
async def test_deactivation_invalidates_tokens_and_blocks_login(db_session):
    user = await _seed(db_session)
    service = AuthService(db_session)
    _, token = await service.login(LoginRequest(email=user.email, password="OldPassword-2026"))

    await service.deactivate_account(user, "OldPassword-2026")

    assert await service.get_current_user(token) is None
    with pytest.raises(ValueError, match="disabled"):
        await service.login(LoginRequest(email=user.email, password="OldPassword-2026"))


@pytest.mark.asyncio
async def test_admin_deactivation_or_password_reset_revokes_sessions(db_session):
    user = await _seed(db_session)
    service = UserService(db_session)

    await service.update_user(user.id, UserUpdate(is_active=False), user.tenant_id)
    assert user.security_version == 2

    await service.update_user(user.id, UserUpdate(password="AdminReset-2026"), user.tenant_id)
    assert user.security_version == 3
    assert user.password_changed_at is not None
