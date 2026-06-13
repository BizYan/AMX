"""Production behavior tests for persistent collaboration work items."""

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-collaboration-work-items-secret"

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401
import app.domains.collaboration.models  # noqa: F401
import app.domains.documents.models  # noqa: F401
import app.domains.identity.models  # noqa: F401
import app.domains.notifications.models  # noqa: F401
import app.models.identity  # noqa: F401
import app.models.projects  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.collaboration.models import CollaborationWorkItem, DocumentComment
from app.domains.collaboration.work_item_service import CollaborationWorkItemService
from app.domains.documents.models import Document
from app.domains.notifications.models import UserNotification
from app.models.identity import Tenant, User
from app.models.projects import Project, ProjectMember


TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = UUID("00000000-0000-0000-0000-000000000002")
OWNER_ID = UUID("11111111-1111-1111-1111-111111111111")
MEMBER_ID = UUID("22222222-2222-2222-2222-222222222222")
OBSERVER_ID = UUID("33333333-3333-3333-3333-333333333333")
OTHER_USER_ID = UUID("44444444-4444-4444-4444-444444444444")
PROJECT_ID = UUID("55555555-5555-5555-5555-555555555555")
DOCUMENT_ID = UUID("66666666-6666-6666-6666-666666666666")
COMMENT_ID = UUID("77777777-7777-7777-7777-777777777777")
OTHER_PROJECT_ID = UUID("88888888-8888-8888-8888-888888888888")


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
async def work_item_context(db_session):
    tenant = Tenant(id=TENANT_ID, name="协同租户", slug="collaboration-tenant")
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
        full_name="评审成员",
        hashed_password="hashed",
    )
    observer = User(
        id=OBSERVER_ID,
        tenant_id=TENANT_ID,
        email="observer@example.com",
        full_name="非项目成员",
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
        name="协同工作项项目",
        slug="collaboration-work-items",
    )
    other_project = Project(
        id=OTHER_PROJECT_ID,
        tenant_id=OTHER_TENANT_ID,
        owner_id=OTHER_USER_ID,
        name="其他租户项目",
        slug="other-collaboration-work-items",
    )
    membership = ProjectMember(project_id=PROJECT_ID, user_id=MEMBER_ID)
    document = Document(
        id=DOCUMENT_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        title="协同工作项 PRD",
        content="# PRD",
        doc_type="prd",
        status="review",
        created_by=OWNER_ID,
    )
    comment = DocumentComment(
        id=COMMENT_ID,
        tenant_id=TENANT_ID,
        document_id=DOCUMENT_ID,
        user_id=MEMBER_ID,
        content="请补充验收指标。",
    )
    db_session.add_all(
        [tenant, other_tenant, owner, member, observer, other_user, project, other_project, membership, document, comment]
    )
    await db_session.flush()
    return owner, member, observer, other_user, project, document, comment, other_project


@pytest.mark.asyncio
async def test_work_items_are_tenant_scoped_and_source_events_are_idempotent(
    db_session,
    work_item_context,
):
    owner, member, _, other_user, project, document, comment, other_project = work_item_context
    service = CollaborationWorkItemService(db_session)

    first = await service.create_work_item(
        tenant_id=TENANT_ID,
        created_by=member.id,
        project_id=project.id,
        document_id=document.id,
        comment_id=comment.id,
        assigned_to=owner.id,
        title="处理评审评论",
        description="补充验收指标并回复评论。",
        work_type="comment_resolution",
        priority="high",
        source_key=f"comment:{comment.id}",
    )
    duplicate = await service.create_work_item(
        tenant_id=TENANT_ID,
        created_by=member.id,
        project_id=project.id,
        document_id=document.id,
        comment_id=comment.id,
        assigned_to=owner.id,
        title="重复事件",
        work_type="comment_resolution",
        source_key=f"comment:{comment.id}",
    )
    await service.create_work_item(
        tenant_id=OTHER_TENANT_ID,
        created_by=other_user.id,
        assigned_to=other_user.id,
        project_id=other_project.id,
        title="其他租户工作项",
    )

    board = await service.list_work_items(TENANT_ID, owner.id)

    assert duplicate.id == first.id
    assert board["total"] == 1
    assert [item.id for item in board["items"]] == [first.id]
    assert board["mine_count"] == 1


@pytest.mark.asyncio
async def test_work_item_claim_complete_reopen_and_permission_boundaries(
    db_session,
    work_item_context,
):
    owner, member, observer, _, project, document, _, _ = work_item_context
    service = CollaborationWorkItemService(db_session)
    item = await service.create_work_item(
        tenant_id=TENANT_ID,
        created_by=owner.id,
        project_id=project.id,
        document_id=document.id,
        title="领取并完成评审",
        work_type="review",
        priority="high",
    )

    with pytest.raises(PermissionError, match="project member"):
        await service.claim(item.id, TENANT_ID, observer.id)

    claimed = await service.claim(item.id, TENANT_ID, member.id)
    assert claimed.assigned_to == member.id
    assert claimed.status == "in_progress"

    completed = await service.complete(item.id, TENANT_ID, member.id)
    assert completed.status == "done"
    assert completed.completed_at is not None

    reopened = await service.reopen(item.id, TENANT_ID, owner.id)

    assert reopened.status == "open"
    assert reopened.completed_at is None


@pytest.mark.asyncio
async def test_work_item_board_reports_overdue_and_status_counts(
    db_session,
    work_item_context,
):
    owner, member, _, _, project, document, _, _ = work_item_context
    service = CollaborationWorkItemService(db_session)
    await service.create_work_item(
        tenant_id=TENANT_ID,
        created_by=owner.id,
        assigned_to=member.id,
        project_id=project.id,
        document_id=document.id,
        title="已逾期工作项",
        due_at=datetime.now(timezone.utc) - timedelta(hours=2),
        priority="critical",
    )
    completed = await service.create_work_item(
        tenant_id=TENANT_ID,
        created_by=owner.id,
        assigned_to=member.id,
        project_id=project.id,
        document_id=document.id,
        title="已完成工作项",
    )
    await service.complete(completed.id, TENANT_ID, member.id)

    board = await service.list_work_items(
        TENANT_ID,
        member.id,
        assignment="mine",
        overdue_only=True,
    )

    assert board["total"] == 1
    assert board["overdue_count"] == 1
    assert board["mine_count"] == 1
    assert board["status_counts"]["open"] == 1
    assert board["status_counts"]["done"] == 1
    assert isinstance(board["items"][0], CollaborationWorkItem)
    assert board["items"][0].assigned_to_name == member.full_name
    assert board["items"][0].project_name == project.name


@pytest.mark.asyncio
async def test_comment_event_creates_and_resolution_completes_real_work_item(
    db_session,
    work_item_context,
):
    owner, member, _, _, _, _, comment, _ = work_item_context
    service = CollaborationWorkItemService(db_session)

    item = await service.create_from_comment(
        tenant_id=TENANT_ID,
        comment_id=comment.id,
        actor_id=member.id,
    )
    completed = await service.complete_for_comment(
        tenant_id=TENANT_ID,
        comment_id=comment.id,
    )

    assert item is not None
    assert item.assigned_to == owner.id
    assert item.work_type == "comment_resolution"
    assert completed is not None
    assert completed.status == "done"


@pytest.mark.asyncio
async def test_assignment_update_notifies_recipient_and_rejects_unauthorized_user(
    db_session,
    work_item_context,
):
    owner, member, observer, _, project, document, _, _ = work_item_context
    service = CollaborationWorkItemService(db_session)
    item = await service.create_work_item(
        tenant_id=TENANT_ID,
        created_by=owner.id,
        project_id=project.id,
        document_id=document.id,
        title="分派评审工作项",
    )

    with pytest.raises(PermissionError, match="cannot manage"):
        await service.update_work_item(
            item.id,
            TENANT_ID,
            observer.id,
            {"title": "越权修改"},
        )

    updated = await service.update_work_item(
        item.id,
        TENANT_ID,
        owner.id,
        {"assigned_to": member.id, "priority": "critical"},
    )
    notifications = list(
        (
            await db_session.scalars(
                select(UserNotification).where(
                    UserNotification.tenant_id == TENANT_ID,
                    UserNotification.user_id == member.id,
                    UserNotification.entity_type == "collaboration_work_item",
                )
            )
        ).all()
    )

    assert updated.assigned_to == member.id
    assert updated.priority == "critical"
    assert len(notifications) == 1
    assert notifications[0].title == "协同工作项已分派给你"
    assert notifications[0].action_url == "/collaboration"


@pytest.mark.asyncio
async def test_historical_comment_from_tenant_user_materializes_without_project_membership(
    db_session,
    work_item_context,
):
    owner, _, observer, _, _, _, comment, _ = work_item_context
    comment.user_id = observer.id
    await db_session.flush()

    item = await CollaborationWorkItemService(db_session).create_from_comment(
        tenant_id=TENANT_ID,
        comment_id=comment.id,
        actor_id=observer.id,
    )

    assert item is not None
    assert item.created_by == observer.id
    assert item.assigned_to == owner.id


@pytest.mark.asyncio
async def test_work_item_board_only_exposes_projects_visible_to_current_user(
    db_session,
    work_item_context,
):
    owner, member, observer, _, project, document, _, _ = work_item_context
    private_project = Project(
        tenant_id=TENANT_ID,
        owner_id=observer.id,
        name="Private project",
        slug="private-project",
    )
    db_session.add(private_project)
    await db_session.flush()
    service = CollaborationWorkItemService(db_session)
    visible = await service.create_work_item(
        tenant_id=TENANT_ID,
        created_by=owner.id,
        project_id=project.id,
        document_id=document.id,
        title="Visible work item",
    )
    await service.create_work_item(
        tenant_id=TENANT_ID,
        created_by=observer.id,
        project_id=private_project.id,
        title="Private work item",
    )

    board = await service.list_work_items(TENANT_ID, member.id)

    assert board["total"] == 1
    assert [item.id for item in board["items"]] == [visible.id]


@pytest.mark.asyncio
async def test_work_item_rejects_document_from_another_project(
    db_session,
    work_item_context,
):
    owner, _, observer, _, project, _, _, _ = work_item_context
    other_project = Project(
        tenant_id=TENANT_ID,
        owner_id=observer.id,
        name="Other project",
        slug="other-visible-project",
    )
    db_session.add(other_project)
    await db_session.flush()
    other_document = Document(
        tenant_id=TENANT_ID,
        project_id=other_project.id,
        title="Other document",
        content="# Other",
        doc_type="prd",
        status="draft",
        created_by=observer.id,
    )
    db_session.add(other_document)
    await db_session.flush()

    with pytest.raises(ValueError, match="Document does not belong"):
        await CollaborationWorkItemService(db_session).create_work_item(
            tenant_id=TENANT_ID,
            created_by=owner.id,
            project_id=project.id,
            document_id=other_document.id,
            title="Invalid linked document",
        )
