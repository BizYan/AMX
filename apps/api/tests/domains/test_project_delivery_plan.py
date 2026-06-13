"""Tests for executable project delivery plans and milestone gates."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-project-delivery-plan-secret"

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401
import app.domains.agent.models  # noqa: F401
import app.domains.collaboration.models  # noqa: F401
import app.domains.documents.models  # noqa: F401
import app.domains.identity.models  # noqa: F401
import app.domains.projects.models  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.collaboration.models import CollaborationWorkItem
from app.domains.documents.models import Document
from app.domains.projects.delivery_plan_service import ProjectDeliveryPlanService
from app.domains.projects.launch_service import ProjectLaunchService
from app.domains.projects.models import ProjectDeliveryPlan, ProjectMilestone
from app.domains.projects.schemas import (
    ProjectLaunchCreate,
    ProjectMilestoneCreate,
    ProjectMilestoneUpdate,
)
from app.domains.projects.service import ProjectService
from app.models.identity import Tenant, User


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


async def _seed(db):
    tenant = Tenant(name="Delivery Tenant", slug=f"delivery-{uuid4().hex[:8]}")
    owner = User(
        tenant=tenant,
        email=f"owner-{uuid4().hex[:8]}@example.com",
        full_name="Project Owner",
        hashed_password="hashed",
    )
    member = User(
        tenant=tenant,
        email=f"member-{uuid4().hex[:8]}@example.com",
        full_name="Milestone Owner",
        hashed_password="hashed",
    )
    db.add_all([tenant, owner, member])
    await db.flush()
    result = await ProjectLaunchService(db).launch(
        tenant_id=tenant.id,
        created_by=owner.id,
        data=ProjectLaunchCreate(
            blueprint_key="product-delivery",
            name="Portal Delivery",
            slug=f"portal-{uuid4().hex[:8]}",
            member_ids=[member.id],
        ),
    )
    return owner, member, result


@pytest.mark.asyncio
async def test_launch_initializes_ordered_delivery_plan_idempotently(db_session):
    owner, _, launched = await _seed(db_session)
    service = ProjectDeliveryPlanService(db_session)

    first = await service.get_plan(launched.project.id, owner.tenant_id)
    second = await service.initialize(
        project_id=launched.project.id,
        tenant_id=owner.tenant_id,
        requested_by=owner.id,
        blueprint_key="product-delivery",
    )

    assert first is not None
    assert first.id == second.id
    assert [item.key for item in first.milestones] == [
        "scope-readiness",
        "core-authoring",
        "review-traceability",
        "release-delivery",
    ]
    assert [item.order_index for item in first.milestones] == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_milestone_owner_synchronizes_responsibility_work_item(db_session):
    owner, member, launched = await _seed(db_session)
    service = ProjectDeliveryPlanService(db_session)

    milestone = await service.create_milestone(
        project_id=launched.project.id,
        tenant_id=owner.tenant_id,
        requested_by=owner.id,
        data=ProjectMilestoneCreate(
            key="customer-acceptance",
            title="Customer acceptance",
            owner_id=member.id,
            due_at=datetime.now(timezone.utc) + timedelta(days=7),
            required_document_types=["test_case"],
        ),
    )
    item = await db_session.scalar(
        select(CollaborationWorkItem).where(
            CollaborationWorkItem.source_key == f"milestone:{milestone.id}"
        )
    )

    assert item is not None
    assert item.assigned_to == member.id
    assert item.due_at.replace(tzinfo=timezone.utc) == milestone.due_at
    assert item.project_id == launched.project.id


@pytest.mark.asyncio
async def test_completion_is_blocked_until_document_gate_passes_then_can_reopen(db_session):
    owner, member, launched = await _seed(db_session)
    service = ProjectDeliveryPlanService(db_session)
    plan = await service.get_plan(launched.project.id, owner.tenant_id)
    milestone = next(item for item in plan.milestones if item.key == "review-traceability")
    milestone.owner_id = member.id
    await db_session.flush()

    await service.start(milestone.id, owner.tenant_id, member.id)
    blocked = await service.complete(milestone.id, owner.tenant_id, member.id)

    blocked_item = await db_session.scalar(
        select(CollaborationWorkItem).where(
            CollaborationWorkItem.source_key == f"milestone:{milestone.id}"
        )
    )
    assert blocked.status == "blocked"
    assert blocked_item.status == "blocked"
    assert milestone.gate_results_json[1]["action_href"].endswith("/documents")

    documents = (
        await db_session.scalars(
            select(Document).where(
                Document.project_id == launched.project.id,
                Document.doc_type.in_(milestone.required_document_types_json),
            )
        )
    ).all()
    for document in documents:
        document.status = "approved"
    await db_session.flush()

    completed = await service.complete(milestone.id, owner.tenant_id, member.id)
    assert completed.completed_at is not None
    reopened = await service.reopen(milestone.id, owner.tenant_id, owner.id)

    assert reopened.status == "planned"
    assert reopened.completed_at is None


@pytest.mark.asyncio
async def test_editing_blocked_milestone_reopens_execution_and_synchronizes_responsibility(db_session):
    owner, member, launched = await _seed(db_session)
    service = ProjectDeliveryPlanService(db_session)
    plan = await service.get_plan(launched.project.id, owner.tenant_id)
    milestone = plan.milestones[0]
    milestone.status = "blocked"
    await db_session.flush()

    updated = await service.update(
        milestone.id,
        owner.tenant_id,
        owner.id,
        ProjectMilestoneUpdate(
            owner_id=member.id,
            priority="critical",
            description="Resolve source readiness before authoring.",
        ),
        project_id=launched.project.id,
    )
    item = await db_session.scalar(
        select(CollaborationWorkItem).where(
            CollaborationWorkItem.source_key == f"milestone:{milestone.id}"
        )
    )

    assert updated.status == "planned"
    assert item.status == "open"
    assert item.assigned_to == member.id
    assert item.priority == "critical"


@pytest.mark.asyncio
async def test_owner_deletes_custom_milestone_and_reorders_remaining_plan(db_session):
    owner, _, launched = await _seed(db_session)
    service = ProjectDeliveryPlanService(db_session)
    custom = await service.create_milestone(
        project_id=launched.project.id,
        tenant_id=owner.tenant_id,
        requested_by=owner.id,
        data=ProjectMilestoneCreate(key="customer-signoff", title="Customer signoff"),
    )

    await service.delete(
        custom.id,
        owner.tenant_id,
        owner.id,
        project_id=launched.project.id,
    )
    plan = await service.get_plan(launched.project.id, owner.tenant_id)
    work_item = await db_session.scalar(
        select(CollaborationWorkItem).where(
            CollaborationWorkItem.source_key == f"milestone:{custom.id}"
        )
    )

    assert work_item is None
    assert [item.order_index for item in plan.milestones] == [0, 1, 2, 3]
    assert all(item.id != custom.id for item in plan.milestones)


@pytest.mark.asyncio
async def test_plan_summary_reports_progress_overdue_and_next_milestone(db_session):
    owner, _, launched = await _seed(db_session)
    service = ProjectDeliveryPlanService(db_session)
    plan = await service.get_plan(launched.project.id, owner.tenant_id)
    first, second = plan.milestones[:2]
    first.status = "completed"
    first.completed_at = datetime.now(timezone.utc)
    second.due_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.flush()

    response = await service.build_response(launched.project.id, owner.tenant_id)

    assert response.summary.completed_count == 1
    assert response.summary.overdue_count == 1
    assert response.summary.progress_percent == 25
    assert response.summary.next_milestone_id == second.id


@pytest.mark.asyncio
async def test_milestone_mutation_is_scoped_to_the_requested_project(db_session):
    owner, _, launched = await _seed(db_session)
    service = ProjectDeliveryPlanService(db_session)
    plan = await service.get_plan(launched.project.id, owner.tenant_id)

    with pytest.raises(ValueError, match="not found"):
        await service.start(
            plan.milestones[0].id,
            owner.tenant_id,
            owner.id,
            project_id=uuid4(),
        )
    with pytest.raises(ValueError, match="Document type"):
        await service.create_milestone(
            project_id=launched.project.id,
            tenant_id=owner.tenant_id,
            requested_by=owner.id,
            data=ProjectMilestoneCreate(
                key="invalid-document-gate",
                title="Invalid document gate",
                required_document_types=["unknown"],
            ),
        )


@pytest.mark.asyncio
async def test_portfolio_aggregation_reports_visible_overdue_and_owner_load(db_session):
    owner, _, launched = await _seed(db_session)
    plan = await ProjectDeliveryPlanService(db_session).get_plan(
        launched.project.id, owner.tenant_id
    )
    milestone = plan.milestones[0]
    milestone.status = "blocked"
    milestone.due_at = datetime.now(timezone.utc) - timedelta(days=2)
    milestone.gate_results_json = [
        {"key": "required-documents", "status": "blocked", "message": "Missing input"}
    ]
    await db_session.flush()

    portfolio = await ProjectService(db_session)._build_milestone_portfolio(
        tenant_id=owner.tenant_id,
        projects=[launched.project],
    )

    assert portfolio["totals"]["total"] == 4
    assert portfolio["totals"]["blocked"] == 1
    assert portfolio["totals"]["overdue"] == 1
    assert portfolio["upcoming"][0]["milestone_id"] == milestone.id
    assert portfolio["owner_load"][0]["owner_id"] == owner.id
