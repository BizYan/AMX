"""Tests for controlled document review and release flow."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-secret"

import pytest
from fastapi import HTTPException

from app.core.settings import settings
from app.domains.documents import router as document_router
from app.domains.documents.schemas import DocumentStatusUpdate
from app.domains.documents.service import DocumentService
from app.domains.projects.lifecycle import default_document_lifecycle_policy

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class OptionalResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


@pytest.mark.asyncio
async def test_publish_requires_approved_status_and_resolved_comments():
    document_id = UUID("12345678-1234-1234-1234-123456789012")
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    user_id = UUID("11111111-1111-1111-1111-111111111111")
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        status="pending_review",
        approved_by=None,
        metadata_json={},
    )

    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    service = DocumentService(db)
    service.get_document = AsyncMock(return_value=document)

    with pytest.raises(ValueError, match="approved"):
        await service.transition_status(
            document_id=document_id,
            tenant_id=tenant_id,
            status_update=DocumentStatusUpdate(status="published", reason="Release candidate"),
            changed_by=user_id,
        )

    document.status = "approved"
    db.execute.return_value = ScalarResult(2)
    with pytest.raises(ValueError, match="unresolved"):
        await service.transition_status(
            document_id=document_id,
            tenant_id=tenant_id,
            status_update=DocumentStatusUpdate(status="published", reason="Release candidate"),
            changed_by=user_id,
        )

    db.execute.return_value = ScalarResult(0)
    updated = await service.transition_status(
        document_id=document_id,
        tenant_id=tenant_id,
        status_update=DocumentStatusUpdate(status="published", reason="Release candidate"),
        changed_by=user_id,
    )

    assert updated is document
    assert document.status == "published"
    history = document.metadata_json["review_flow"]["status_history"]
    assert history[-1]["from_status"] == "approved"
    assert history[-1]["to_status"] == "published"
    assert history[-1]["reason"] == "Release candidate"
    assert history[-1]["changed_by"] == str(user_id)
    assert history[-1]["unresolved_comment_count"] == 0
    assert history[-1]["transition_id"]


@pytest.mark.asyncio
async def test_status_history_backfills_stable_transition_ids_for_legacy_entries():
    document_id = UUID("12345678-1234-1234-1234-123456789012")
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        metadata_json={
            "review_flow": {
                "status_history": [
                    {
                        "from_status": "draft",
                        "to_status": "review",
                        "action": "status_transition",
                        "reason": "Ready for review",
                        "changed_by": "11111111-1111-1111-1111-111111111111",
                        "changed_at": "2026-06-17T00:00:00+00:00",
                        "unresolved_comment_count": 0,
                        "policy_revision": 1,
                    }
                ]
            }
        },
    )

    service = DocumentService(AsyncMock())
    service.get_document = AsyncMock(return_value=document)

    first = await service.list_status_history(document_id, tenant_id)
    second = await service.list_status_history(document_id, tenant_id)

    assert first[0]["transition_id"].startswith("legacy-")
    assert second[0]["transition_id"] == first[0]["transition_id"]
    assert "transition_id" not in document.metadata_json["review_flow"]["status_history"][0]


@pytest.mark.asyncio
async def test_review_flow_rejects_invalid_transition_and_records_reason():
    document_id = UUID("12345678-1234-1234-1234-123456789012")
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    user_id = UUID("11111111-1111-1111-1111-111111111111")
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        status="draft",
        approved_by=None,
        metadata_json={"source": "unit-test"},
    )

    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    service = DocumentService(db)
    service.get_document = AsyncMock(return_value=document)

    with pytest.raises(ValueError, match="Invalid status transition"):
        await service.transition_status(
            document_id=document_id,
            tenant_id=tenant_id,
            status_update=DocumentStatusUpdate(status="approved", reason="Skip review"),
            changed_by=user_id,
        )

    updated = await service.transition_status(
        document_id=document_id,
        tenant_id=tenant_id,
        status_update=DocumentStatusUpdate(status="writing", reason="Start authoring"),
        changed_by=user_id,
    )

    assert updated.status == "writing"
    assert updated.metadata_json["source"] == "unit-test"
    assert updated.metadata_json["review_flow"]["status_history"][-1]["reason"] == "Start authoring"


@pytest.mark.asyncio
async def test_owner_required_access_rejects_plain_project_member(monkeypatch):
    document_id = UUID("12345678-1234-1234-1234-123456789012")
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    user_id = UUID("22222222-2222-2222-2222-222222222222")
    project_id = UUID("33333333-3333-3333-3333-333333333333")
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        project_id=project_id,
        created_by=UUID("11111111-1111-1111-1111-111111111111"),
    )

    class FakeDocumentService:
        def __init__(self, db):
            self.db = db

        async def get_document(self, requested_document_id, requested_tenant_id):
            assert requested_document_id == document_id
            assert requested_tenant_id == tenant_id
            return document

    monkeypatch.setattr(document_router, "DocumentService", FakeDocumentService)

    db = AsyncMock()
    db.execute.side_effect = [
        OptionalResult(None),
        OptionalResult(SimpleNamespace(project_id=project_id, user_id=user_id)),
    ]

    with pytest.raises(HTTPException) as error:
        await document_router.check_document_access(
            document_id=document_id,
            user_id=user_id,
            db=db,
            tenant_id=tenant_id,
            require_owner=True,
        )

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_document_owner_cannot_bypass_explicit_approval_permission(monkeypatch):
    user_id = UUID("11111111-1111-1111-1111-111111111111")
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    document = SimpleNamespace(
        created_by=user_id,
        project_id=UUID("33333333-3333-3333-3333-333333333333"),
    )
    current_user = SimpleNamespace(id=user_id, tenant_id=tenant_id)

    class FakePermissionEvaluator:
        def __init__(self, db):
            self.db = db

        async def explain_permission(self, user, action, resource, scoped_tenant_id):
            assert action == "approve"
            assert resource == "documents"
            assert scoped_tenant_id == tenant_id
            return {"allowed": False, "reason": "no_grant"}

        def permissions_allow(self, permissions, action, resource):
            return False

    monkeypatch.setattr(document_router, "PermissionEvaluator", FakePermissionEvaluator)
    db = AsyncMock()
    db.execute.return_value = OptionalResult(None)

    decision = await document_router.get_document_status_permission_decision(
        document,
        current_user,
        db,
        "approved",
    )

    assert decision == {
        "allowed": False,
        "reason": "no_grant",
        "permission_action": "documents.approve",
    }
    with pytest.raises(HTTPException) as error:
        await document_router.require_document_status_permission(
            document,
            current_user,
            db,
            "approved",
        )
    assert error.value.status_code == 403
    assert "documents.approve" in error.value.detail


@pytest.mark.asyncio
async def test_document_owner_can_manage_review_transition_without_role_grant(monkeypatch):
    user_id = UUID("11111111-1111-1111-1111-111111111111")
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    document = SimpleNamespace(
        created_by=user_id,
        project_id=UUID("33333333-3333-3333-3333-333333333333"),
    )
    current_user = SimpleNamespace(id=user_id, tenant_id=tenant_id)

    class FakePermissionEvaluator:
        def __init__(self, db):
            self.db = db

        async def explain_permission(self, user, action, resource, scoped_tenant_id):
            return {"allowed": False, "reason": "no_grant"}

        def permissions_allow(self, permissions, action, resource):
            return False

    monkeypatch.setattr(document_router, "PermissionEvaluator", FakePermissionEvaluator)
    db = AsyncMock()
    db.execute.return_value = OptionalResult(None)

    decision = await document_router.get_document_status_permission_decision(
        document,
        current_user,
        db,
        "review",
    )

    assert decision == {
        "allowed": True,
        "reason": "document_or_project_owner",
        "permission_action": "documents.review",
    }


@pytest.mark.asyncio
async def test_delegated_project_role_can_publish_with_explicit_permission(monkeypatch):
    user_id = UUID("22222222-2222-2222-2222-222222222222")
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    document = SimpleNamespace(
        created_by=UUID("11111111-1111-1111-1111-111111111111"),
        project_id=UUID("33333333-3333-3333-3333-333333333333"),
    )
    current_user = SimpleNamespace(id=user_id, tenant_id=tenant_id)

    class FakePermissionEvaluator:
        def __init__(self, db):
            self.db = db

        async def explain_permission(self, user, action, resource, scoped_tenant_id):
            assert action == "publish"
            return {"allowed": False, "reason": "no_grant"}

        def permissions_allow(self, permissions, action, resource):
            return action in permissions.get(resource, [])

    monkeypatch.setattr(document_router, "PermissionEvaluator", FakePermissionEvaluator)
    db = AsyncMock()
    db.execute.return_value = OptionalResult(
        SimpleNamespace(permissions={"documents": ["publish"]})
    )

    decision = await document_router.get_document_status_permission_decision(
        document,
        current_user,
        db,
        "published",
    )

    assert decision == {
        "allowed": True,
        "reason": "project_role",
        "permission_action": "documents.publish",
    }


@pytest.mark.asyncio
async def test_status_capabilities_combine_permission_and_workflow_blockers(monkeypatch):
    document_id = UUID("12345678-1234-1234-1234-123456789012")
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    user_id = UUID("22222222-2222-2222-2222-222222222222")
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        project_id=UUID("33333333-3333-3333-3333-333333333333"),
        created_by=UUID("11111111-1111-1111-1111-111111111111"),
        status="pending_review",
        metadata_json={},
    )
    current_user = SimpleNamespace(id=user_id, tenant_id=tenant_id)

    async def fake_check_document_access(*args, **kwargs):
        return document

    async def fake_permission_decision(document_arg, user_arg, db_arg, next_status):
        return {
            "allowed": next_status in {"approved", "published"},
            "reason": "rbac" if next_status in {"approved", "published"} else "no_grant",
            "permission_action": f"documents.{next_status}",
        }

    monkeypatch.setattr(document_router, "check_document_access", fake_check_document_access)
    monkeypatch.setattr(
        document_router,
        "get_document_status_permission_decision",
        fake_permission_decision,
    )

    async def fake_lifecycle_policy(self, document_arg):
        return default_document_lifecycle_policy()

    monkeypatch.setattr(DocumentService, "get_document_lifecycle_policy", fake_lifecycle_policy)

    response = await document_router.get_document_status_capabilities(
        document_id=document_id,
        db=AsyncMock(),
        current_user=current_user,
    )
    capabilities = {item.status: item for item in response.capabilities}

    assert capabilities["approved"].allowed is True
    assert capabilities["approved"].blockers == []
    assert capabilities["published"].allowed is False
    assert capabilities["published"].blockers == [
        "Document must be approved before it can be published"
    ]
    assert capabilities["archived"].allowed is False
    assert capabilities["archived"].authorization_reason == "no_grant"


@pytest.mark.asyncio
async def test_publish_rejects_unresolved_template_placeholders():
    document_id = UUID("12345678-1234-1234-1234-123456789012")
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        status="approved",
        content="Client: {{client_name}}",
        metadata_json={},
    )
    service = DocumentService(AsyncMock())

    blockers = await service.get_status_transition_blockers(document, "published")

    assert blockers == [
        "Document contains unresolved template placeholders and cannot be published: client_name"
    ]
