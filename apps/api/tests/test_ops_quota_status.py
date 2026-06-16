"""Ops quota status regression tests."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-ops-quota-status-secret"

import app.db.init_schema  # noqa: F401
import app.domains.ops.models  # noqa: F401
import app.models.identity  # noqa: F401
import app.models.projects  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.ops.models import QuotaUsage
from app.domains.ops.router import get_quota_status
from app.models.identity import Tenant, User
from app.services.quota_service import QuotaType


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


async def _seed_user(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    db_session.add_all(
        [
            Tenant(id=tenant_id, name="Quota Tenant", slug=f"quota-{tenant_id.hex[:8]}"),
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=f"quota-{user_id.hex[:8]}@example.com",
                full_name="Quota User",
                hashed_password="hashed",
            ),
        ]
    )
    await db_session.flush()
    return await db_session.get(User, user_id)


@pytest.mark.asyncio
async def test_quota_status_does_not_synthesize_reset_time_without_api_quota(db_session):
    user = await _seed_user(db_session)

    response = await get_quota_status(db=db_session, current_user=user)

    assert response.used == 0
    assert response.limit == 1000
    assert response.resetAt is None


@pytest.mark.asyncio
async def test_quota_status_preserves_null_reset_time_from_api_quota(db_session):
    user = await _seed_user(db_session)
    db_session.add(
        QuotaUsage(
            tenant_id=user.tenant_id,
            quota_type=QuotaType.API_CALLS,
            used_amount=42,
            limit_amount=500,
            period="monthly",
            reset_at=None,
        )
    )
    await db_session.flush()

    response = await get_quota_status(db=db_session, current_user=user)

    assert response.used == 42
    assert response.limit == 500
    assert response.resetAt is None


@pytest.mark.asyncio
async def test_quota_status_returns_authoritative_reset_time_from_api_quota(db_session):
    user = await _seed_user(db_session)
    reset_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    db_session.add(
        QuotaUsage(
            tenant_id=user.tenant_id,
            quota_type=QuotaType.API_CALLS,
            used_amount=10,
            limit_amount=100,
            period="monthly",
            reset_at=reset_at,
        )
    )
    await db_session.flush()

    response = await get_quota_status(db=db_session, current_user=user)

    assert response.used == 10
    assert response.limit == 100
    assert response.resetAt is not None
    assert response.resetAt.replace(tzinfo=timezone.utc) == reset_at
