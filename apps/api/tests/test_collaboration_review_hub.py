"""Collaboration review hub tests."""

import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-collaboration-review-hub.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-collaboration-review-hub-secret"

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

import app.db.init_schema  # noqa: F401 - registers sqlite compilers for UUID/JSONB
import app.domains.collaboration.models  # noqa: F401 - registers collaboration tables
import app.domains.documents.models  # noqa: F401 - registers document tables
import app.domains.identity.models  # noqa: F401 - registers audit tables
import app.domains.notifications.models  # noqa: F401 - registers notification tables
import app.models.identity  # noqa: F401 - registers tenant/user/role tables
import app.models.projects  # noqa: F401 - registers project tables
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.collaboration.models import CollaborationWorkItem, DocumentComment, DocumentSnapshot
from app.domains.documents.models import Document, DocumentStatus, DocumentVersion
from app.models.identity import Role, Tenant, User, UserRole
from app.models.projects import Project, ProjectMember
from app.services.audit_service import create_audit_service
from app.services.collaboration_service import CollaborationService


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


async def _seed_review_fixture(db_session):
    tenant_id = uuid4()
    lead_id = uuid4()
    reviewer_id = uuid4()
    project_id = uuid4()
    review_doc_id = uuid4()
    approved_doc_id = uuid4()
    role_id = uuid4()

    db_session.add(Tenant(id=tenant_id, name="Avenir Matrix", slug="avenir-matrix"))
    db_session.add(
        User(
            id=lead_id,
            tenant_id=tenant_id,
            email="lead@example.test",
            hashed_password="hashed",
            full_name="项目负责人",
            is_active=True,
        )
    )
    db_session.add(
        User(
            id=reviewer_id,
            tenant_id=tenant_id,
            email="reviewer@example.test",
            hashed_password="hashed",
            full_name="客户评审人",
            is_active=True,
        )
    )
    db_session.add(Role(id=role_id, tenant_id=tenant_id, name="客户评审人", permissions={"documents": ["review"]}))
    db_session.add(UserRole(user_id=reviewer_id, role_id=role_id))
    db_session.add(
        Project(
            id=project_id,
            tenant_id=tenant_id,
            name="协同验收项目",
            slug="collaboration-review",
            status="active",
            owner_id=lead_id,
        )
    )
    db_session.add(ProjectMember(project_id=project_id, user_id=reviewer_id))
    db_session.add(
        Document(
            id=review_doc_id,
            tenant_id=tenant_id,
            project_id=project_id,
            doc_type="prd",
            title="履约监控 PRD",
            content="# PRD",
            status=DocumentStatus.REVIEW.value,
            version=2,
            created_by=reviewer_id,
            metadata_json={},
        )
    )
    db_session.add(
        Document(
            id=approved_doc_id,
            tenant_id=tenant_id,
            project_id=project_id,
            doc_type="brd",
            title="仓储升级 BRD",
            content="# BRD",
            status=DocumentStatus.APPROVED.value,
            version=1,
            created_by=lead_id,
            approved_by=lead_id,
            metadata_json={},
        )
    )
    db_session.add(
        DocumentComment(
            tenant_id=tenant_id,
            document_id=review_doc_id,
            user_id=lead_id,
            content="请补充接口超时策略。",
            resolved=False,
        )
    )
    db_session.add(
        DocumentComment(
            tenant_id=tenant_id,
            document_id=review_doc_id,
            user_id=lead_id,
            content="请确认追溯字段。",
            resolved=False,
        )
    )
    db_session.add(
        DocumentSnapshot(
            tenant_id=tenant_id,
            document_id=review_doc_id,
            user_id=reviewer_id,
            snapshot_data={"title": "履约监控 PRD", "content": "# PRD"},
            snapshot_type="manual",
            version=2,
        )
    )
    await db_session.flush()
    return tenant_id, lead_id, reviewer_id, review_doc_id, approved_doc_id


@pytest.mark.asyncio
async def test_review_hub_builds_cross_project_queue_members_and_todos(db_session):
    tenant_id, lead_id, reviewer_id, review_doc_id, _ = await _seed_review_fixture(db_session)

    hub = await CollaborationService(db_session, create_audit_service(db_session)).build_review_hub(
        tenant_id=tenant_id,
        current_user_id=lead_id,
    )

    members = {item["id"]: item for item in hub["members"]}
    reviews = {item["document_id"]: item for item in hub["review_queue"]}

    assert members[lead_id]["status"] == "online"
    assert members[reviewer_id]["role"] == "客户评审人"
    assert reviews[review_doc_id]["status"] == "PASSED_WITH_FOLLOW_UPS"
    assert reviews[review_doc_id]["pending_comments"] == 2
    assert reviews[review_doc_id]["snapshot_count"] == 1
    assert hub["comment_todos"][0]["document_title"] == "履约监控 PRD"
    assert {item["status"] for item in hub["acceptance_decisions"]} == {
        "PASSED",
        "BLOCKED",
        "PASSED_WITH_FOLLOW_UPS",
    }


@pytest.mark.asyncio
async def test_acceptance_command_center_blocks_release_for_pending_reviews_and_comments(db_session):
    tenant_id, lead_id, _, review_doc_id, _ = await _seed_review_fixture(db_session)
    review_document = await db_session.get(Document, review_doc_id)
    db_session.add(
        CollaborationWorkItem(
            tenant_id=tenant_id,
            project_id=review_document.project_id,
            document_id=review_doc_id,
            assigned_to=None,
            created_by=lead_id,
            work_type="manual",
            status="open",
            priority="high",
            title="确认客户验收会议",
            description="需要客户侧确认验收会时间。",
        )
    )
    await db_session.flush()
    service = CollaborationService(db_session, create_audit_service(db_session))

    command_center = await service.build_acceptance_command_center(
        tenant_id=tenant_id,
        current_user_id=lead_id,
    )

    assert command_center["release_gate"]["status"] == "blocked"
    assert command_center["summary"]["total_reviews"] == 2
    assert command_center["summary"]["follow_up_reviews"] == 1
    assert command_center["summary"]["pending_comments"] == 2
    assert command_center["summary"]["open_work_items"] == 3
    assert command_center["summary"]["unassigned_work_items"] == 1
    assert {item["code"] for item in command_center["risk_items"]} >= {
        "pending_comments",
        "follow_up_reviews",
        "unassigned_work_items",
    }
    assert command_center["priority_actions"][0]["href"] == "/collaboration"
    assert any(item["document_id"] == review_doc_id for item in command_center["review_queue"])


@pytest.mark.asyncio
async def test_review_actions_update_document_comments_and_audit_log(db_session):
    tenant_id, lead_id, _, review_doc_id, approved_doc_id = await _seed_review_fixture(db_session)
    service = CollaborationService(db_session, create_audit_service(db_session))

    passed = await service.perform_review_action(
        tenant_id=tenant_id,
        document_id=review_doc_id,
        user_id=lead_id,
        action="pass-acceptance",
    )
    returned = await service.perform_review_action(
        tenant_id=tenant_id,
        document_id=approved_doc_id,
        user_id=lead_id,
        action="return-revision",
    )

    comments = (
        await db_session.execute(select(DocumentComment).where(DocumentComment.document_id == review_doc_id))
    ).scalars().all()

    assert passed["status"] == "PASSED"
    assert all(comment.resolved for comment in comments)
    assert returned["status"] == "BLOCKED"
    assert "退回修订" in returned["acceptance_decision"]


@pytest.mark.asyncio
async def test_auto_snapshot_preserves_unsaved_draft_and_deduplicates(db_session):
    tenant_id, lead_id, _, review_doc_id, _ = await _seed_review_fixture(db_session)
    service = CollaborationService(db_session, create_audit_service(db_session))
    draft_data = {
        "title": "履约监控 PRD 草稿",
        "content": "# PRD\n\n尚未正式保存的自动保存内容",
    }

    first = await service.create_snapshot(
        tenant_id=tenant_id,
        document_id=review_doc_id,
        user_id=lead_id,
        snapshot_type="auto",
        draft_data=draft_data,
    )
    second = await service.create_snapshot(
        tenant_id=tenant_id,
        document_id=review_doc_id,
        user_id=lead_id,
        snapshot_type="auto",
        draft_data=draft_data,
    )

    snapshots = (
        await db_session.execute(
            select(DocumentSnapshot).where(
                DocumentSnapshot.document_id == review_doc_id,
                DocumentSnapshot.snapshot_type == "auto",
            )
        )
    ).scalars().all()
    document = await db_session.get(Document, review_doc_id)

    assert first.id == second.id
    assert len(snapshots) == 1
    assert first.snapshot_data["title"] == draft_data["title"]
    assert first.snapshot_data["content"] == draft_data["content"]
    assert document.title == "履约监控 PRD"
    assert document.content == "# PRD"
    assert document.version == 2


@pytest.mark.asyncio
async def test_restore_snapshot_records_pre_restore_version(db_session):
    tenant_id, lead_id, _, review_doc_id, _ = await _seed_review_fixture(db_session)
    service = CollaborationService(db_session, create_audit_service(db_session))
    snapshot = await service.create_snapshot(
        tenant_id=tenant_id,
        document_id=review_doc_id,
        user_id=lead_id,
        snapshot_type="auto",
        draft_data={
            "title": "恢复后的标题",
            "content": "# PRD\n\n自动保存恢复内容",
        },
    )

    await service.restore_snapshot(snapshot.id, tenant_id, lead_id)

    document = await db_session.get(Document, review_doc_id)
    versions = (
        await db_session.execute(
            select(DocumentVersion).where(DocumentVersion.document_id == review_doc_id)
        )
    ).scalars().all()

    assert document.title == "恢复后的标题"
    assert document.content == "# PRD\n\n自动保存恢复内容"
    assert document.version == 3
    assert len(versions) == 1
    assert versions[0].version == 2
    assert versions[0].content == "# PRD"
    assert "Before restore from snapshot" in versions[0].changes_summary


@pytest.mark.asyncio
async def test_comment_reply_inherits_anchor_and_root_resolution_closes_thread(db_session):
    tenant_id, lead_id, reviewer_id, review_doc_id, _ = await _seed_review_fixture(db_session)
    service = CollaborationService(db_session, create_audit_service(db_session))

    root = await service.create_comment(
        tenant_id=tenant_id,
        document_id=review_doc_id,
        entity_id=None,
        user_id=lead_id,
        content="请补充验收指标。",
        anchor="## 验收标准",
    )
    reply = await service.create_comment(
        tenant_id=tenant_id,
        document_id=review_doc_id,
        entity_id=None,
        user_id=reviewer_id,
        content="已补充首轮指标。",
        parent_id=root.id,
    )

    assert reply.parent_comment_id == root.id
    assert reply.anchor == "## 验收标准"

    await service.resolve_comment(root.id, tenant_id, lead_id)
    await db_session.refresh(reply)

    assert root.resolved is True
    assert reply.resolved is True

    follow_up = await service.create_comment(
        tenant_id=tenant_id,
        document_id=review_doc_id,
        entity_id=None,
        user_id=reviewer_id,
        content="还有一项需要确认。",
        parent_id=reply.id,
    )
    await db_session.refresh(root)

    assert follow_up.parent_comment_id == root.id
    assert follow_up.anchor == "## 验收标准"
    assert root.resolved is False


@pytest.mark.asyncio
async def test_comment_reply_rejects_parent_from_another_document(db_session):
    tenant_id, lead_id, reviewer_id, review_doc_id, approved_doc_id = await _seed_review_fixture(db_session)
    service = CollaborationService(db_session, create_audit_service(db_session))
    foreign_parent = await service.create_comment(
        tenant_id=tenant_id,
        document_id=approved_doc_id,
        entity_id=None,
        user_id=lead_id,
        content="另一个文档的评论。",
    )

    with pytest.raises(ValueError, match="Parent comment not found"):
        await service.create_comment(
            tenant_id=tenant_id,
            document_id=review_doc_id,
            entity_id=None,
            user_id=reviewer_id,
            content="不允许跨文档回复。",
            parent_id=foreign_parent.id,
        )


@pytest.mark.asyncio
async def test_review_hub_materializes_comment_work_items_and_actions_keep_them_in_sync(db_session):
    tenant_id, lead_id, _, review_doc_id, approved_doc_id = await _seed_review_fixture(db_session)
    service = CollaborationService(db_session, create_audit_service(db_session))

    hub = await service.build_review_hub(tenant_id=tenant_id, current_user_id=lead_id)
    await service.build_review_hub(tenant_id=tenant_id, current_user_id=lead_id)

    comment_items = list(
        (
            await db_session.scalars(
                select(CollaborationWorkItem).where(
                    CollaborationWorkItem.tenant_id == tenant_id,
                    CollaborationWorkItem.work_type == "comment_resolution",
                )
            )
        ).all()
    )
    assert len(comment_items) == 2
    assert hub["comment_todos"][0]["count"] == 2
    assert hub["comment_todos"][0]["id"].startswith("work-item-")

    await service.perform_review_action(
        tenant_id=tenant_id,
        document_id=review_doc_id,
        user_id=lead_id,
        action="assign-me",
    )
    review_item = await db_session.scalar(
        select(CollaborationWorkItem).where(
            CollaborationWorkItem.tenant_id == tenant_id,
            CollaborationWorkItem.source_key == f"review:{review_doc_id}",
        )
    )
    assert review_item is not None
    assert review_item.assigned_to == lead_id
    assert review_item.status == "in_progress"

    await service.perform_review_action(
        tenant_id=tenant_id,
        document_id=review_doc_id,
        user_id=lead_id,
        action="pass-acceptance",
    )
    document_items = list(
        (
            await db_session.scalars(
                select(CollaborationWorkItem).where(
                    CollaborationWorkItem.tenant_id == tenant_id,
                    CollaborationWorkItem.document_id == review_doc_id,
                )
            )
        ).all()
    )
    assert document_items
    assert {item.status for item in document_items} == {"done"}

    await service.perform_review_action(
        tenant_id=tenant_id,
        document_id=approved_doc_id,
        user_id=lead_id,
        action="return-revision",
    )
    follow_up = await db_session.scalar(
        select(CollaborationWorkItem).where(
            CollaborationWorkItem.tenant_id == tenant_id,
            CollaborationWorkItem.source_key == f"follow-up:{approved_doc_id}",
        )
    )
    assert follow_up is not None
    assert follow_up.assigned_to == lead_id
    assert follow_up.status == "blocked"
