"""Tests for project-scoped document lifecycle policy configuration."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-project-document-lifecycle-secret"

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401
import app.domains.collaboration.models  # noqa: F401
import app.domains.documents.models  # noqa: F401
import app.domains.identity.models  # noqa: F401
import app.domains.projects.models  # noqa: F401
import app.models.identity  # noqa: F401
import app.models.projects  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.documents.schemas import DocumentStatusUpdate
from app.domains.documents.service import DocumentService
from app.domains.documents import router as document_router
from app.domains.documents.models import Document
from app.domains.identity.models import AuditLog
from app.domains.projects import router as project_router
from app.domains.projects.lifecycle import (
    ProjectDocumentLifecyclePolicyService,
    default_document_lifecycle_policy,
)
from app.domains.projects.schemas import (
    DocumentLifecyclePolicyUpdate,
    DocumentLifecyclePublishGates,
    DocumentLifecycleStatus,
    DocumentLifecycleTransition,
)
from app.models.identity import Tenant, User
from app.models.projects import Project, ProjectMember


PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")
TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
DOCUMENT_ID = UUID("12345678-1234-1234-1234-123456789012")


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


def compact_policy_update(**overrides):
    values = {
        "statuses": [
            DocumentLifecycleStatus(key="draft", label="草稿"),
            DocumentLifecycleStatus(key="review", label="评审"),
            DocumentLifecycleStatus(key="approved", label="已批准"),
            DocumentLifecycleStatus(key="published", label="已发布"),
            DocumentLifecycleStatus(key="archived", label="已归档"),
        ],
        "transitions": [
            DocumentLifecycleTransition(from_status="draft", to_status="review"),
            DocumentLifecycleTransition(from_status="review", to_status="approved"),
            DocumentLifecycleTransition(from_status="approved", to_status="published"),
            DocumentLifecycleTransition(from_status="published", to_status="archived"),
        ],
        "require_reason_for": ["approved", "published", "archived"],
        "publish_gates": DocumentLifecyclePublishGates(),
    }
    values.update(overrides)
    return DocumentLifecyclePolicyUpdate(**values)


def test_default_policy_preserves_platform_status_flow():
    policy = default_document_lifecycle_policy()

    assert policy.revision == 1
    assert policy.statuses[0].key == "draft"
    assert {item.key for item in policy.statuses} == {
        "draft",
        "writing",
        "pending_review",
        "review",
        "in_review",
        "revision_required",
        "approved",
        "published",
        "archived",
    }
    assert any(
        item.from_status == "approved" and item.to_status == "published"
        for item in policy.transitions
    )
    assert policy.publish_gates.require_approved is True
    assert policy.publish_gates.require_resolved_comments is True
    assert policy.publish_gates.require_resolved_placeholders is True


def test_policy_validation_rejects_unknown_disconnected_and_duplicate_transitions():
    with pytest.raises(ValidationError, match="unknown status"):
        compact_policy_update(
            transitions=[
                DocumentLifecycleTransition(from_status="draft", to_status="unknown"),
            ]
        )

    with pytest.raises(ValidationError, match="inbound transition"):
        compact_policy_update(
            transitions=[
                DocumentLifecycleTransition(from_status="draft", to_status="review"),
                DocumentLifecycleTransition(from_status="review", to_status="approved"),
                DocumentLifecycleTransition(from_status="approved", to_status="published"),
            ]
        )

    duplicate = DocumentLifecycleTransition(from_status="draft", to_status="review")
    with pytest.raises(ValidationError, match="Duplicate transition"):
        compact_policy_update(transitions=[duplicate, duplicate])

    with pytest.raises(ValidationError, match="outbound transition"):
        compact_policy_update(
            transitions=[
                DocumentLifecycleTransition(from_status="draft", to_status="review"),
                DocumentLifecycleTransition(from_status="review", to_status="approved"),
                DocumentLifecycleTransition(from_status="approved", to_status="published"),
                DocumentLifecycleTransition(from_status="draft", to_status="archived"),
            ]
        )


@pytest.mark.asyncio
async def test_policy_service_preserves_other_settings_and_increments_revision():
    existing = SimpleNamespace(
        project_id=PROJECT_ID,
        settings_json={
            "notifications": {"daily_digest": True},
            "document_lifecycle": {
                **default_document_lifecycle_policy().model_dump(),
                "revision": 4,
            },
        },
    )
    db = AsyncMock()
    service = ProjectDocumentLifecyclePolicyService(db)
    service.settings_service.get_settings = AsyncMock(return_value=existing)
    service.settings_service.upsert_settings = AsyncMock(return_value=existing)
    service.find_disabled_active_statuses = AsyncMock(return_value=[])

    policy = await service.update_policy(PROJECT_ID, compact_policy_update())

    assert policy.revision == 5
    saved = service.settings_service.upsert_settings.await_args.kwargs["settings"]
    assert saved["notifications"] == {"daily_digest": True}
    assert saved["document_lifecycle"]["revision"] == 5


@pytest.mark.asyncio
async def test_policy_api_allows_member_read_owner_update_and_records_audit(db_session):
    owner_id = USER_ID
    member_id = UUID("22222222-2222-2222-2222-222222222222")
    tenant = Tenant(id=TENANT_ID, name="Lifecycle Tenant", slug="lifecycle-tenant")
    owner = User(
        id=owner_id,
        tenant_id=TENANT_ID,
        email="owner@example.com",
        full_name="Owner",
        hashed_password="hashed",
    )
    member = User(
        id=member_id,
        tenant_id=TENANT_ID,
        email="member@example.com",
        full_name="Member",
        hashed_password="hashed",
    )
    project = Project(
        id=PROJECT_ID,
        tenant_id=TENANT_ID,
        owner_id=owner_id,
        name="Lifecycle Project",
        slug="lifecycle-project",
    )
    membership = ProjectMember(project_id=PROJECT_ID, user_id=member_id)
    db_session.add_all([tenant, owner, member, project, membership])
    await db_session.flush()

    initial = await project_router.get_project_document_lifecycle_policy(
        project_id=PROJECT_ID,
        db=db_session,
        current_user=member,
    )
    assert initial.revision == 1

    with pytest.raises(HTTPException) as error:
        await project_router.update_project_document_lifecycle_policy(
            project_id=PROJECT_ID,
            data=compact_policy_update(),
            db=db_session,
            current_user=member,
        )
    assert error.value.status_code == 403

    updated = await project_router.update_project_document_lifecycle_policy(
        project_id=PROJECT_ID,
        data=compact_policy_update(),
        db=db_session,
        current_user=owner,
    )
    assert updated.revision == 1
    persisted = await project_router.get_project_document_lifecycle_policy(
        project_id=PROJECT_ID,
        db=db_session,
        current_user=member,
    )
    assert [item.key for item in persisted.statuses] == [
        "draft",
        "review",
        "approved",
        "published",
        "archived",
    ]
    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "project.document_lifecycle_policy.update")
    )
    assert audit is not None
    assert audit.user_id == owner_id
    assert audit.extra_data["revision"] == 1


@pytest.mark.asyncio
async def test_policy_api_rejects_disabling_a_status_used_by_active_documents(db_session):
    tenant = Tenant(id=TENANT_ID, name="Lifecycle Tenant", slug="lifecycle-tenant")
    owner = User(
        id=USER_ID,
        tenant_id=TENANT_ID,
        email="owner@example.com",
        full_name="Owner",
        hashed_password="hashed",
    )
    project = Project(
        id=PROJECT_ID,
        tenant_id=TENANT_ID,
        owner_id=USER_ID,
        name="Lifecycle Project",
        slug="lifecycle-project",
    )
    document = Document(
        id=DOCUMENT_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        doc_type="brd",
        title="Active Draft",
        content="Draft content",
        status="writing",
        created_by=USER_ID,
        metadata_json={},
    )
    db_session.add_all([tenant, owner, project, document])
    await db_session.flush()

    with pytest.raises(HTTPException) as error:
        await project_router.update_project_document_lifecycle_policy(
            project_id=PROJECT_ID,
            data=compact_policy_update(),
            db=db_session,
            current_user=owner,
        )

    assert error.value.status_code == 400
    assert "writing" in error.value.detail


@pytest.mark.asyncio
async def test_document_service_enforces_custom_transitions_and_required_reason():
    policy = default_document_lifecycle_policy().model_copy(
        update={
            "transitions": [
                DocumentLifecycleTransition(from_status="draft", to_status="review"),
                DocumentLifecycleTransition(from_status="review", to_status="approved"),
                DocumentLifecycleTransition(from_status="approved", to_status="published"),
            ],
            "require_reason_for": ["approved"],
        }
    )
    document = SimpleNamespace(
        id=DOCUMENT_ID,
        project_id=PROJECT_ID,
        tenant_id=TENANT_ID,
        status="draft",
        content="Ready",
        approved_by=None,
        metadata_json={},
    )
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    service = DocumentService(db)
    service.get_document = AsyncMock(return_value=document)
    service.get_document_lifecycle_policy = AsyncMock(return_value=policy)

    with pytest.raises(ValueError, match="Invalid status transition"):
        await service.transition_status(
            DOCUMENT_ID,
            TENANT_ID,
            DocumentStatusUpdate(status="writing", reason="Not enabled by this project"),
            changed_by=USER_ID,
        )

    document.status = "review"
    with pytest.raises(ValueError, match="reason is required"):
        await service.transition_status(
            DOCUMENT_ID,
            TENANT_ID,
            DocumentStatusUpdate(status="approved"),
            changed_by=USER_ID,
        )

    updated = await service.transition_status(
        DOCUMENT_ID,
        TENANT_ID,
        DocumentStatusUpdate(status="approved", reason="Business owner accepted"),
        changed_by=USER_ID,
    )
    assert updated.status == "approved"
    history = updated.metadata_json["review_flow"]["status_history"][-1]
    assert history["policy_revision"] == 1


@pytest.mark.asyncio
async def test_document_service_applies_project_publish_gates():
    policy = default_document_lifecycle_policy().model_copy(
        update={
            "publish_gates": DocumentLifecyclePublishGates(
                require_approved=False,
                require_resolved_comments=False,
                require_resolved_placeholders=False,
            ),
            "transitions": [
                DocumentLifecycleTransition(from_status="review", to_status="published"),
            ],
        }
    )
    document = SimpleNamespace(
        id=DOCUMENT_ID,
        project_id=PROJECT_ID,
        tenant_id=TENANT_ID,
        status="review",
        content="Client: {{client_name}}",
        metadata_json={},
    )
    service = DocumentService(AsyncMock())
    service.get_document_lifecycle_policy = AsyncMock(return_value=policy)
    service.count_unresolved_comments = AsyncMock(return_value=3)

    blockers = await service.get_status_transition_blockers(document, "published")

    assert blockers == []


@pytest.mark.asyncio
async def test_status_capabilities_project_enabled_statuses_labels_and_revision(monkeypatch):
    policy = default_document_lifecycle_policy().model_copy(
        update={
            "revision": 7,
            "statuses": [
                DocumentLifecycleStatus(key="draft", label="初稿"),
                DocumentLifecycleStatus(key="review", label="业务评审"),
                DocumentLifecycleStatus(key="approved", label="签批完成"),
                DocumentLifecycleStatus(key="published", label="正式交付"),
            ],
            "transitions": [
                DocumentLifecycleTransition(from_status="draft", to_status="review"),
                DocumentLifecycleTransition(from_status="review", to_status="approved"),
                DocumentLifecycleTransition(from_status="approved", to_status="published"),
            ],
        }
    )
    document = SimpleNamespace(
        id=DOCUMENT_ID,
        project_id=PROJECT_ID,
        tenant_id=TENANT_ID,
        status="draft",
        content="Ready",
        metadata_json={},
    )

    async def fake_check_document_access(*args, **kwargs):
        return document

    async def fake_permission_decision(document_arg, user_arg, db_arg, next_status):
        return {
            "allowed": True,
            "reason": "rbac",
            "permission_action": f"documents.{next_status}",
        }

    class FakeDocumentService:
        def __init__(self, db):
            self.db = db

        async def get_document_lifecycle_policy(self, document_arg):
            return policy

        async def get_status_transition_blockers(self, document_arg, next_status, policy_arg=None):
            return []

    monkeypatch.setattr(document_router, "check_document_access", fake_check_document_access)
    monkeypatch.setattr(document_router, "get_document_status_permission_decision", fake_permission_decision)
    monkeypatch.setattr(document_router, "DocumentService", FakeDocumentService)

    response = await document_router.get_document_status_capabilities(
        document_id=DOCUMENT_ID,
        db=AsyncMock(),
        current_user=SimpleNamespace(id=USER_ID, tenant_id=TENANT_ID),
    )

    assert response.policy_revision == 7
    assert [item.status for item in response.capabilities] == ["review", "approved", "published"]
    assert response.capabilities[0].label == "业务评审"
