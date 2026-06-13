"""Operational delivery evidence and retry behavior tests."""

import os
from uuid import UUID

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-notification-delivery-secret"

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401
import app.domains.ops.models  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.ops.models import NotificationEvent
from app.domains.ops.notification_delivery_service import NotificationDeliveryService
from app.models.identity import Tenant
from app.services.notification_service import NotificationChannel, NotificationResult


TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture
async def db_session():
    deduplicate_indexes()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        session.add_all(
            [
                Tenant(id=TENANT_ID, name="通知租户", slug="notification-delivery"),
                Tenant(id=OTHER_TENANT_ID, name="其他租户", slug="other-delivery"),
            ]
        )
        await session.flush()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_delivery_list_is_tenant_scoped_and_summarized(db_session):
    db_session.add_all(
        [
            NotificationEvent(
                tenant_id=TENANT_ID,
                channel="email",
                recipient="ops@example.com",
                title="失败邮件",
                body="需要人工重试",
                status="failed",
                retry_count="3",
                error_message="SMTP unavailable",
            ),
            NotificationEvent(
                tenant_id=TENANT_ID,
                channel="system",
                recipient="system",
                title="成功站内通知",
                body="已投递",
                status="sent",
                retry_count="0",
            ),
            NotificationEvent(
                tenant_id=OTHER_TENANT_ID,
                channel="email",
                recipient="other@example.com",
                title="其他租户",
                body="不可见",
                status="failed",
                retry_count="1",
            ),
        ]
    )
    await db_session.flush()

    result = await NotificationDeliveryService(db_session).list_deliveries(TENANT_ID)

    assert result.total == 2
    assert result.failed_count == 1
    assert result.sent_count == 1
    assert {item.title for item in result.items} == {"失败邮件", "成功站内通知"}


@pytest.mark.asyncio
async def test_failed_delivery_can_be_retried_and_updates_same_evidence_record(db_session, monkeypatch):
    event = NotificationEvent(
        tenant_id=TENANT_ID,
        channel="email",
        recipient="ops@example.com",
        title="失败邮件",
        body="需要人工重试",
        status="failed",
        retry_count="3",
        error_message="SMTP unavailable",
        metadata_json={"rule_id": "rule-1"},
    )
    db_session.add(event)
    await db_session.flush()

    async def successful_send(self, **kwargs):
        from app.services.notification_service import NotificationMessage, NotificationPriority

        message = NotificationMessage(
            title=kwargs["title"],
            body=kwargs["body"],
            channel=kwargs["channel"],
            recipient=kwargs["recipient"],
            priority=NotificationPriority.HIGH,
        )
        return NotificationResult(success=True, channel=NotificationChannel.EMAIL, message=message)

    monkeypatch.setattr("app.services.notification_service.NotificationService.send", successful_send)

    retried = await NotificationDeliveryService(db_session).retry_delivery(event.id, TENANT_ID)

    assert retried is event
    assert retried.status == "sent"
    assert retried.retry_count == "4"
    assert retried.error_message is None
    assert retried.sent_at is not None
