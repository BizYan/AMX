"""Tests for project launch blueprints and idempotent initialization."""

import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-project-launch-blueprints-secret"

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401
import app.domains.agent.models  # noqa: F401
import app.domains.documents.models  # noqa: F401
import app.domains.identity.models  # noqa: F401
import app.domains.projects.models  # noqa: F401
import app.models.identity  # noqa: F401
import app.models.projects  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.agent.models import WorkflowDefinition
from app.domains.documents.models import Document
from app.domains.identity.models import AuditLog
from app.domains.projects import router as project_router
from app.domains.projects.launch_service import ProjectLaunchService
from app.domains.projects.models import ProjectLaunchPlan
from app.domains.projects.schemas import ProjectLaunchCreate
from app.models.identity import Tenant, User
from app.models.projects import ProjectMember


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


async def _seed_users(db_session):
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    owner_id = uuid4()
    member_id = uuid4()
    inactive_id = uuid4()
    outsider_id = uuid4()
    tenants = [
        Tenant(id=tenant_id, name="Launch Tenant", slug=f"launch-{tenant_id.hex[:8]}"),
        Tenant(id=other_tenant_id, name="Other Tenant", slug=f"other-{other_tenant_id.hex[:8]}"),
    ]
    users = [
        User(
            id=owner_id,
            tenant_id=tenant_id,
            email=f"owner-{owner_id.hex[:8]}@example.com",
            full_name="Project Owner",
            hashed_password="hashed",
        ),
        User(
            id=member_id,
            tenant_id=tenant_id,
            email=f"member-{member_id.hex[:8]}@example.com",
            full_name="Delivery Member",
            hashed_password="hashed",
        ),
        User(
            id=inactive_id,
            tenant_id=tenant_id,
            email=f"inactive-{inactive_id.hex[:8]}@example.com",
            full_name="Inactive Member",
            hashed_password="hashed",
            is_active=False,
        ),
        User(
            id=outsider_id,
            tenant_id=other_tenant_id,
            email=f"outsider-{outsider_id.hex[:8]}@example.com",
            full_name="Other Tenant Member",
            hashed_password="hashed",
        ),
    ]
    db_session.add_all([*tenants, *users])
    await db_session.flush()
    return users


def _launch_request(*, member_ids=None, document_types=None, workflow_template_ids=None):
    return ProjectLaunchCreate(
        blueprint_key="product-delivery",
        name="Customer Portal Upgrade",
        slug=f"customer-portal-{uuid4().hex[:8]}",
        description="Launch a governed product delivery project.",
        member_ids=member_ids or [],
        document_types=document_types,
        workflow_template_ids=workflow_template_ids,
    )


def test_blueprint_catalog_exposes_stable_delivery_options():
    catalog = ProjectLaunchService.list_blueprints()

    assert [item.key for item in catalog] == [
        "consulting-discovery",
        "product-delivery",
        "system-modernization",
    ]
    product = next(item for item in catalog if item.key == "product-delivery")
    assert {"urs", "brd", "prd", "detailed_design", "test_case"} <= set(product.document_types)
    assert "document-quality-assessment" in product.workflow_template_ids
    assert product.checks
    assert product.next_actions


@pytest.mark.asyncio
async def test_launch_creates_persistent_plan_members_documents_workflows_and_settings(db_session):
    owner, member, *_ = await _seed_users(db_session)
    service = ProjectLaunchService(db_session)

    result = await service.launch(
        tenant_id=owner.tenant_id,
        created_by=owner.id,
        data=_launch_request(member_ids=[member.id]),
    )

    assert result.plan.status == "ready"
    assert result.plan.blueprint_key == "product-delivery"
    assert result.plan.completed_at is not None
    assert result.plan.results_json["documents"]["created"] == 5
    assert result.plan.results_json["members"]["added"] == 1
    assert all(check["status"] == "passed" for check in result.plan.checks_json)

    memberships = (
        await db_session.execute(
            select(ProjectMember).where(ProjectMember.project_id == result.project.id)
        )
    ).scalars().all()
    assert {membership.user_id for membership in memberships} == {owner.id, member.id}

    documents = (
        await db_session.execute(
            select(Document).where(Document.project_id == result.project.id)
        )
    ).scalars().all()
    assert {document.doc_type for document in documents} == {
        "urs",
        "brd",
        "prd",
        "detailed_design",
        "test_case",
    }
    assert all(document.status == "draft" for document in documents)
    assert all(document.metadata_json["generation_status"] == "planned" for document in documents)
    assert all(document.metadata_json["launch_blueprint"] == "product-delivery" for document in documents)

    workflows = (
        await db_session.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.tenant_id == owner.tenant_id)
        )
    ).scalars().all()
    assert workflows
    assert result.plan.config_json["workflow_template_ids"]
    assert result.plan.config_json["project_settings"]["launch_blueprint"] == "product-delivery"


@pytest.mark.asyncio
async def test_launch_rejects_invalid_members_documents_and_workflows(db_session):
    owner, _, inactive, outsider = await _seed_users(db_session)
    service = ProjectLaunchService(db_session)

    with pytest.raises(ValueError, match="active users in the current tenant"):
        await service.launch(
            tenant_id=owner.tenant_id,
            created_by=owner.id,
            data=_launch_request(member_ids=[inactive.id, outsider.id]),
        )

    with pytest.raises(ValueError, match="Document type"):
        await service.launch(
            tenant_id=owner.tenant_id,
            created_by=owner.id,
            data=_launch_request(document_types=["brd", "unknown"]),
        )

    with pytest.raises(ValueError, match="Workflow template"):
        await service.launch(
            tenant_id=owner.tenant_id,
            created_by=owner.id,
            data=_launch_request(workflow_template_ids=["missing-workflow"]),
        )


@pytest.mark.asyncio
async def test_retry_is_idempotent_and_repairs_missing_planned_assets(db_session):
    owner, *_ = await _seed_users(db_session)
    service = ProjectLaunchService(db_session)
    result = await service.launch(
        tenant_id=owner.tenant_id,
        created_by=owner.id,
        data=_launch_request(),
    )
    documents = (
        await db_session.execute(
            select(Document).where(Document.project_id == result.project.id)
        )
    ).scalars().all()
    await db_session.execute(delete(Document).where(Document.id == documents[0].id))
    await db_session.flush()

    retried = await service.retry(
        project_id=result.project.id,
        tenant_id=owner.tenant_id,
        requested_by=owner.id,
    )
    final_documents = (
        await db_session.execute(
            select(Document).where(Document.project_id == result.project.id)
        )
    ).scalars().all()

    assert retried.plan.status == "ready"
    assert len(final_documents) == 5
    assert len({document.doc_type for document in final_documents}) == 5
    assert retried.plan.attempt_count == 2
    assert retried.plan.results_json["documents"]["created"] == 1
    assert retried.plan.results_json["documents"]["existing"] == 4


@pytest.mark.asyncio
async def test_launch_persists_failed_plan_for_visible_retry(db_session, monkeypatch):
    owner, *_ = await _seed_users(db_session)
    service = ProjectLaunchService(db_session)

    async def fail_documents(**kwargs):
        raise RuntimeError("document initialization unavailable")

    monkeypatch.setattr(service, "_ensure_documents", fail_documents)
    result = await service.launch(
        tenant_id=owner.tenant_id,
        created_by=owner.id,
        data=_launch_request(),
    )
    persisted = await service.get_plan(result.project.id, owner.tenant_id)

    assert result.plan.status == "failed"
    assert result.plan.error_message == "document initialization unavailable"
    assert result.plan.attempt_count == 1
    assert persisted is result.plan


@pytest.mark.asyncio
async def test_launch_api_records_audit_and_owner_only_retry(db_session):
    owner, member, *_ = await _seed_users(db_session)
    response = await project_router.launch_project(
        data=_launch_request(member_ids=[member.id]),
        db=db_session,
        current_user=owner,
    )

    persisted = await db_session.scalar(
        select(ProjectLaunchPlan).where(ProjectLaunchPlan.project_id == response.project.id)
    )
    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "project.launch")
    )
    assert persisted is not None
    assert audit is not None
    assert audit.resource_id == response.project.id

    with pytest.raises(HTTPException) as error:
        await project_router.retry_project_launch(
            project_id=response.project.id,
            db=db_session,
            current_user=member,
        )
    assert error.value.status_code == 403
