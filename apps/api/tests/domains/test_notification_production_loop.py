"""Production-loop behavior tests for notification preferences and escalation."""

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-notification-production-loop-secret"

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401
import app.domains.notifications.models  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.notifications.schemas import NotificationPreferenceUpdate
from app.domains.notifications.service import UserNotificationService
from app.domains.ops.models import NotificationEvent
from app.models.identity import Tenant, User


TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
async def db_session():
    deduplicate_indexes()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        tenant = Tenant(id=TENANT_ID, name="通知租户", slug="notification-loop")
        user = User(
            id=USER_ID,
            tenant_id=TENANT_ID,
            email="owner@example.com",
            full_name="负责人",
            hashed_password="hashed",
        )
        session.add_all([tenant, user])
        await session.flush()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_preferences_filter_normal_notifications_but_never_suppress_urgent(db_session):
    service = UserNotificationService(db_session)
    defaults = await service.get_preferences(TENANT_ID, USER_ID)
    assert defaults.in_app_enabled is True
    assert defaults.min_priority == "low"
    assert defaults.ack_timeout_minutes == 60

    updated = await service.update_preferences(
        TENANT_ID,
        USER_ID,
        NotificationPreferenceUpdate(
            enabled_categories=["document_review"],
            min_priority="high",
            email_enabled=True,
        ),
    )
    assert updated.enabled_categories == ["document_review"]

    suppressed_category = await service.create_notification(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        title="普通系统通知",
        body="应按分类偏好过滤",
        category="system",
        priority="high",
    )
    suppressed_priority = await service.create_notification(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        title="低优先级评审",
        body="应按最低优先级过滤",
        category="document_review",
        priority="normal",
    )
    urgent = await service.create_notification(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        title="紧急系统通知",
        body="紧急通知不得被偏好关闭",
        category="system",
        priority="urgent",
    )
    allowed = await service.create_notification(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        title="高优先级评审",
        body="应进入站内收件箱并生成邮件待投递事件",
        category="document_review",
        priority="high",
    )
    pending_email = await db_session.scalar(
        select(NotificationEvent).where(
            NotificationEvent.tenant_id == TENANT_ID,
            NotificationEvent.recipient == "owner@example.com",
            NotificationEvent.title == "高优先级评审",
        )
    )
    await service.update_preferences(
        TENANT_ID,
        USER_ID,
        NotificationPreferenceUpdate(in_app_enabled=False),
    )
    email_only = await service.create_notification(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        title="仅邮件通知",
        body="关闭站内通知后仍应进入邮件投递队列",
        category="document_review",
        priority="high",
    )
    email_only_event = await db_session.scalar(
        select(NotificationEvent).where(NotificationEvent.title == "仅邮件通知")
    )

    assert suppressed_category is None
    assert suppressed_priority is None
    assert urgent is not None
    assert urgent.priority == "urgent"
    assert allowed is not None
    assert pending_email is not None
    assert pending_email.status == "pending"
    assert email_only is None
    assert email_only_event is not None


@pytest.mark.asyncio
async def test_acknowledgement_and_overdue_escalation_are_owned_and_idempotent(db_session):
    service = UserNotificationService(db_session)
    overdue = await service.create_notification(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        title="需要确认的关键通知",
        body="请在时限内确认",
        category="operations_alert",
        priority="high",
        ack_required=True,
        ack_timeout_minutes=5,
    )
    assert overdue is not None
    overdue.ack_deadline_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.flush()

    first_escalation = await service.escalate_overdue(now=datetime.now(timezone.utc))
    second_escalation = await service.escalate_overdue(now=datetime.now(timezone.utc))

    assert [item.id for item in first_escalation] == [overdue.id]
    assert second_escalation == []
    assert overdue.priority == "urgent"
    assert overdue.escalation_level == 1
    assert overdue.escalated_at is not None

    acknowledged = await service.acknowledge(overdue.id, TENANT_ID, USER_ID)
    assert acknowledged is overdue
    assert acknowledged.acknowledged_at is not None

    page = await service.list_notifications(
        TENANT_ID,
        USER_ID,
        acknowledgement="acknowledged",
        escalated=True,
    )
    assert [item.id for item in page.items] == [overdue.id]


@pytest.mark.asyncio
async def test_acknowledged_notification_never_escalates(db_session):
    service = UserNotificationService(db_session)
    notification = await service.create_notification(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        title="已确认事项",
        body="确认后不应升级",
        priority="high",
        ack_required=True,
        ack_timeout_minutes=5,
    )
    assert notification is not None
    notification.ack_deadline_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await service.acknowledge(notification.id, TENANT_ID, USER_ID)

    escalated = await service.escalate_overdue(now=datetime.now(timezone.utc))

    assert escalated == []
    assert notification.escalation_level == 0


def test_worker_registers_alert_delivery_and_periodic_escalation():
    from pathlib import Path

    queue_source = (Path(__file__).parents[2] / "app/workers/queue.py").read_text(encoding="utf-8")

    assert "evaluate_alert_rules," in queue_source
    assert "evaluate_single_rule," in queue_source
    assert "send_alert_notification," in queue_source
    assert "cron(evaluate_alert_rules" in queue_source
    assert "cron(escalate_overdue_notifications" in queue_source
    assert "cron(process_pending_notification_deliveries" in queue_source
