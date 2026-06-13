"""Production behavior tests for the in-app notification center."""

import os
from uuid import UUID

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-user-notifications-secret"

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401
import app.domains.agent.models  # noqa: F401
import app.domains.collaboration.models  # noqa: F401
import app.domains.documents.models  # noqa: F401
import app.domains.identity.models  # noqa: F401
import app.domains.notifications.models  # noqa: F401
import app.domains.projects.models  # noqa: F401
import app.models.identity  # noqa: F401
import app.models.projects  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.notifications.service import UserNotificationService
from app.domains.agent.service import AgentRunService
from app.domains.collaboration.models import DocumentComment
from app.domains.documents.models import Document
from app.models.identity import Tenant, User
from app.models.projects import Project, ProjectMember


TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = UUID("00000000-0000-0000-0000-000000000002")
OWNER_ID = UUID("11111111-1111-1111-1111-111111111111")
MEMBER_ID = UUID("22222222-2222-2222-2222-222222222222")
OTHER_USER_ID = UUID("33333333-3333-3333-3333-333333333333")
PROJECT_ID = UUID("44444444-4444-4444-4444-444444444444")


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


@pytest.fixture
async def notification_context(db_session):
    tenant = Tenant(id=TENANT_ID, name="通知租户", slug="notification-tenant")
    other_tenant = Tenant(id=OTHER_TENANT_ID, name="其他租户", slug="other-tenant")
    owner = User(
        id=OWNER_ID,
        tenant_id=TENANT_ID,
        email="owner@example.com",
        full_name="项目负责人",
        hashed_password="hashed",
    )
    member = User(
        id=MEMBER_ID,
        tenant_id=TENANT_ID,
        email="member@example.com",
        full_name="项目成员",
        hashed_password="hashed",
    )
    other_user = User(
        id=OTHER_USER_ID,
        tenant_id=OTHER_TENANT_ID,
        email="other@example.com",
        full_name="其他租户成员",
        hashed_password="hashed",
    )
    project = Project(
        id=PROJECT_ID,
        tenant_id=TENANT_ID,
        owner_id=OWNER_ID,
        name="通知项目",
        slug="notification-project",
    )
    membership = ProjectMember(project_id=PROJECT_ID, user_id=MEMBER_ID)
    db_session.add_all([tenant, other_tenant, owner, member, other_user, project, membership])
    await db_session.flush()
    return owner, member, other_user, project


@pytest.mark.asyncio
async def test_targeted_and_tenant_broadcast_notifications_are_isolated_and_deduplicated(
    db_session,
    notification_context,
):
    owner, member, other_user, _ = notification_context
    service = UserNotificationService(db_session)

    targeted = await service.create_notification(
        tenant_id=TENANT_ID,
        user_id=MEMBER_ID,
        title="文档待评审",
        body="PRD 已进入待评审状态。",
        category="document_review",
        priority="high",
        action_url=f"/projects/{PROJECT_ID}/documents/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        dedupe_key="document:aaaaaaaa:review:member",
    )
    duplicate = await service.create_notification(
        tenant_id=TENANT_ID,
        user_id=MEMBER_ID,
        title="重复事件不会产生第二条通知",
        body="重复",
        category="document_review",
        dedupe_key="document:aaaaaaaa:review:member",
    )
    broadcasts = await service.broadcast_to_tenant(
        tenant_id=TENANT_ID,
        title="租户维护通知",
        body="今晚进行维护。",
        category="system",
        priority="normal",
        dedupe_key="maintenance:2026-06-07",
    )
    await service.create_notification(
        tenant_id=OTHER_TENANT_ID,
        user_id=OTHER_USER_ID,
        title="其他租户通知",
        body="不应跨租户可见。",
        category="system",
    )

    member_page = await service.list_notifications(TENANT_ID, MEMBER_ID)
    owner_page = await service.list_notifications(TENANT_ID, OWNER_ID)
    other_page = await service.list_notifications(OTHER_TENANT_ID, OTHER_USER_ID)

    assert duplicate.id == targeted.id
    member_broadcast = next(item for item in broadcasts if item.user_id == MEMBER_ID)
    owner_broadcast = next(item for item in broadcasts if item.user_id == OWNER_ID)
    assert {item.id for item in member_page.items} == {targeted.id, member_broadcast.id}
    assert {item.id for item in owner_page.items} == {owner_broadcast.id}
    assert len(other_page.items) == 1
    assert other_page.items[0].title == "其他租户通知"
    assert member_page.unread_count == 2


@pytest.mark.asyncio
async def test_read_archive_and_summary_only_mutate_current_users_inbox(
    db_session,
    notification_context,
):
    _, member, _, _ = notification_context
    service = UserNotificationService(db_session)

    first = await service.create_notification(
        tenant_id=TENANT_ID,
        user_id=MEMBER_ID,
        title="第一条",
        body="第一条通知",
        category="comment",
    )
    second = await service.create_notification(
        tenant_id=TENANT_ID,
        user_id=MEMBER_ID,
        title="第二条",
        body="第二条通知",
        category="agent_run",
    )

    marked = await service.mark_read(first.id, TENANT_ID, MEMBER_ID)
    summary = await service.get_summary(TENANT_ID, MEMBER_ID, limit=5)
    archived = await service.archive(first.id, TENANT_ID, MEMBER_ID)
    changed = await service.mark_all_read(TENANT_ID, MEMBER_ID)
    active = await service.list_notifications(TENANT_ID, MEMBER_ID)
    archived_only = await service.list_notifications(
        TENANT_ID,
        MEMBER_ID,
        archived_only=True,
    )

    assert marked.read_at is not None
    assert summary.unread_count == 1
    assert archived.archived_at is not None
    assert changed == 1
    assert [item.id for item in active.items] == [second.id]
    assert archived_only.total == 1
    assert [item.id for item in archived_only.items] == [first.id]
    assert active.unread_count == 0


@pytest.mark.asyncio
async def test_project_event_notifies_owner_and_members_except_actor(
    db_session,
    notification_context,
):
    owner, member, _, project = notification_context
    service = UserNotificationService(db_session)

    created = await service.notify_project_members(
        tenant_id=TENANT_ID,
        project_id=project.id,
        actor_id=member.id,
        title="文档已发布",
        body="项目 PRD 已发布。",
        category="document_lifecycle",
        priority="high",
        action_url=f"/projects/{project.id}/documents/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        entity_type="document",
        entity_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        dedupe_key="document:aaaaaaaa:published",
    )

    assert [item.user_id for item in created] == [owner.id]
    owner_summary = await service.get_summary(TENANT_ID, owner.id)
    member_summary = await service.get_summary(TENANT_ID, member.id)
    assert owner_summary.unread_count == 1
    assert member_summary.unread_count == 0


@pytest.mark.asyncio
async def test_comment_and_agent_terminal_events_reach_the_responsible_user(
    db_session,
    notification_context,
):
    owner, member, _, project = notification_context
    document_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    comment_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    document = Document(
        id=document_id,
        tenant_id=TENANT_ID,
        project_id=project.id,
        title="WMS 升级 PRD",
        content="正文",
        doc_type="prd",
        status="review",
        created_by=owner.id,
    )
    comment = DocumentComment(
        id=comment_id,
        tenant_id=TENANT_ID,
        document_id=document.id,
        user_id=member.id,
        content="请补充验收指标。",
    )
    db_session.add_all([document, comment])
    await db_session.flush()

    notification_service = UserNotificationService(db_session)
    comment_notifications = await notification_service.notify_document_comment(
        tenant_id=TENANT_ID,
        document_id=document.id,
        comment_id=comment.id,
        actor_id=member.id,
    )
    run = await AgentRunService(db_session).create_run(
        tenant_id=TENANT_ID,
        project_id=project.id,
        created_by=member.id,
        input_data={"goal": "评审 PRD"},
    )
    terminal_run = await AgentRunService(db_session).update_run_status(
        run.id,
        TENANT_ID,
        "failed",
        error_message="Provider 暂不可用",
    )
    member_summary = await notification_service.get_summary(TENANT_ID, member.id)
    terminal = next(item for item in member_summary.recent if item.entity_type == "agent_run")

    assert [item.user_id for item in comment_notifications] == [owner.id]
    assert run.metadata_json["created_by"] == str(member.id)
    assert terminal_run is not None
    assert terminal.user_id == member.id
    assert terminal.priority == "urgent"


@pytest.mark.asyncio
async def test_agent_terminal_notification_failure_does_not_revert_run_status(
    db_session,
    notification_context,
    monkeypatch,
):
    _, member, _, project = notification_context
    run_service = AgentRunService(db_session)
    run = await run_service.create_run(
        tenant_id=TENANT_ID,
        project_id=project.id,
        created_by=member.id,
        input_data={"goal": "验证通知隔离"},
    )

    async def fail_notification(*args, **kwargs):
        raise RuntimeError("notification store unavailable")

    monkeypatch.setattr(UserNotificationService, "notify_agent_run_terminal", fail_notification)

    updated = await run_service.update_run_status(run.id, TENANT_ID, "completed")

    assert updated is not None
    assert updated.status == "completed"
