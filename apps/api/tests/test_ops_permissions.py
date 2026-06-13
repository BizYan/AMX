"""Ops permission dependency regression tests."""

import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-ops-permission-secret"

import app.db.init_schema  # noqa: F401 - registers sqlite compilers for UUID/JSONB
import app.models.identity  # noqa: F401 - registers tenant/user/role tables
import app.models.projects  # noqa: F401 - resolves User.owned_projects relationship
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.ops.router import (
    require_ops_manager,
    require_ops_reader,
    require_tenant_scope,
)
from app.models.identity import Role, Tenant, User, UserRole


@pytest.fixture
async def db_session():
    deduplicate_indexes()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()


async def _seed_user_with_role(db_session, *, permissions: dict | None, tenant_id=None):
    tenant_id = tenant_id or uuid4()
    user_id = uuid4()
    role_id = uuid4()
    db_session.add_all(
        [
            Tenant(id=tenant_id, name=f"Tenant {tenant_id}", slug=f"tenant-{tenant_id.hex[:8]}"),
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=f"user-{user_id.hex[:8]}@example.com",
                full_name="Ops User",
                hashed_password="hashed",
            ),
        ]
    )
    if permissions is not None:
        db_session.add_all(
            [
                Role(
                    id=role_id,
                    tenant_id=tenant_id,
                    name="Ops Role",
                    description="Ops permission test role",
                    permissions=permissions,
                ),
                UserRole(user_id=user_id, role_id=role_id),
            ]
        )
    await db_session.flush()
    return await db_session.get(User, user_id)


@pytest.mark.asyncio
async def test_ops_read_permission_allows_read_dependency(db_session):
    user = await _seed_user_with_role(db_session, permissions={"ops": ["read"]})

    resolved = await require_ops_reader(db_session, user)

    assert resolved.id == user.id


@pytest.mark.asyncio
async def test_ops_manage_permission_allows_manage_dependency(db_session):
    user = await _seed_user_with_role(db_session, permissions={"ops": ["manage"]})

    resolved = await require_ops_manager(db_session, user)

    assert resolved.id == user.id


@pytest.mark.asyncio
async def test_ops_dependency_rejects_authenticated_user_without_ops_permission(db_session):
    user = await _seed_user_with_role(db_session, permissions={"documents": ["read"]})

    with pytest.raises(Exception) as exc_info:
        await require_ops_reader(db_session, user)

    assert getattr(exc_info.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_ops_tenant_scope_blocks_cross_tenant_access_for_non_admin(db_session):
    user = await _seed_user_with_role(db_session, permissions={"ops": ["read"]})
    other_tenant_id = uuid4()

    with pytest.raises(Exception) as exc_info:
        await require_tenant_scope(db=db_session, user=user, tenant_id=other_tenant_id)

    assert getattr(exc_info.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_ops_tenant_scope_allows_cross_tenant_access_for_global_admin(db_session):
    user = await _seed_user_with_role(db_session, permissions={"*": "*"})
    other_tenant_id = uuid4()

    await require_tenant_scope(db=db_session, user=user, tenant_id=other_tenant_id)
