"""Tests for the governed project archive and restore lifecycle."""

import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-project-archive-lifecycle-secret"

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401
import app.domains.identity.models  # noqa: F401
import app.domains.projects.models  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.identity.models import AuditLog
from app.domains.projects import router as project_router
from app.domains.projects.schemas import ProjectUpdate
from app.domains.projects.service import ProjectService
from app.models.identity import Tenant, User
from app.models.projects import Project, ProjectMember


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


async def _seed_projects(db_session):
    tenant_id = uuid4()
    owner = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email=f"owner-{uuid4().hex[:8]}@example.com",
        full_name="Project Owner",
        hashed_password="hashed",
    )
    member = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email=f"member-{uuid4().hex[:8]}@example.com",
        full_name="Project Member",
        hashed_password="hashed",
    )
    tenant = Tenant(id=tenant_id, name="Archive Tenant", slug=f"archive-{tenant_id.hex[:8]}")
    active = Project(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_id=owner.id,
        name="Active Project",
        slug="active-project",
        status="active",
    )
    archived = Project(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_id=owner.id,
        name="Archived Project",
        slug="archived-project",
        status="archived",
    )
    db_session.add_all(
        [
            tenant,
            owner,
            member,
            active,
            archived,
            ProjectMember(project_id=active.id, user_id=owner.id),
            ProjectMember(project_id=active.id, user_id=member.id),
            ProjectMember(project_id=archived.id, user_id=owner.id),
            ProjectMember(project_id=archived.id, user_id=member.id),
        ]
    )
    await db_session.flush()
    return owner, member, active, archived


@pytest.mark.asyncio
async def test_project_list_filters_active_archived_and_all(db_session):
    owner, _, active, archived = await _seed_projects(db_session)
    service = ProjectService(db_session)

    active_projects, active_total = await service.list_projects(
        owner.tenant_id, owner.id, status="active"
    )
    archived_projects, archived_total = await service.list_projects(
        owner.tenant_id, owner.id, status="archived"
    )
    all_projects, all_total = await service.list_projects(owner.tenant_id, owner.id)

    assert {project.id for project in active_projects} == {active.id}
    assert active_total == 1
    assert {project.id for project in archived_projects} == {archived.id}
    assert archived_total == 1
    assert {project.id for project in all_projects} == {active.id, archived.id}
    assert all_total == 2


@pytest.mark.asyncio
async def test_owner_can_archive_and_restore_project_with_audit_evidence(db_session):
    owner, _, active, _ = await _seed_projects(db_session)

    archived = await project_router.archive_project(active.id, db_session, owner)
    archived_status = archived.status
    restored = await project_router.restore_project(active.id, db_session, owner)

    assert archived_status == "archived"
    assert restored.status == "active"
    actions = (
        await db_session.execute(
            select(AuditLog.action)
            .where(AuditLog.resource_id == active.id)
            .order_by(AuditLog.created_at)
        )
    ).scalars().all()
    assert actions == ["project.archive", "project.restore"]


@pytest.mark.asyncio
async def test_project_member_cannot_bypass_owner_only_archive_transition(db_session):
    _, member, active, _ = await _seed_projects(db_session)

    with pytest.raises(HTTPException) as error:
        await project_router.update_project(
            active.id,
            ProjectUpdate(status="archived"),
            db_session,
            member,
        )

    assert error.value.status_code == 403


def test_project_update_rejects_unknown_lifecycle_status():
    with pytest.raises(ValidationError):
        ProjectUpdate(status="unknown")
