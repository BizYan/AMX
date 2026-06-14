"""Tests for the governed project invitation lifecycle."""

import hashlib
import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-project-invitation-secret"

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401
import app.domains.identity.models  # noqa: F401
import app.domains.projects.models  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.projects import router as project_router
from app.domains.projects.models import ProjectInvitation
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


async def _seed(db_session):
    tenant_id = uuid4()
    tenant = Tenant(id=tenant_id, name="Invitation Tenant", slug=f"invite-{tenant_id.hex[:8]}")
    owner = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email="owner@example.com",
        full_name="Project Owner",
        hashed_password="hashed",
    )
    invitee = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email="invitee@example.com",
        full_name="Invited Consultant",
        hashed_password="hashed",
    )
    other = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email="other@example.com",
        full_name="Other User",
        hashed_password="hashed",
    )
    project = Project(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_id=owner.id,
        name="Invitation Project",
        slug=f"invitation-{uuid4().hex[:8]}",
        status="active",
    )
    db_session.add_all([tenant, owner, invitee, other, project, ProjectMember(project_id=project.id, user_id=owner.id)])
    await db_session.flush()
    return owner, invitee, other, project


@pytest.mark.asyncio
async def test_owner_can_create_list_and_resend_hashed_invitation(db_session):
    owner, invitee, _, project = await _seed(db_session)

    created = await project_router.create_project_invitation(project.id, invitee.email, db_session, owner)
    stored = (await db_session.execute(select(ProjectInvitation))).scalar_one()

    assert stored.token == hashlib.sha256(created.token.encode("utf-8")).hexdigest()
    assert stored.token != created.token
    assert created.invite_path == f"/invitations/{created.token}"

    invitations = await project_router.list_project_invitations(project.id, db_session, owner)
    assert invitations.total == 1
    assert invitations.items[0].status == "active"
    assert invitations.items[0].email == invitee.email

    resent = await project_router.resend_project_invitation(project.id, stored.id, db_session, owner)
    await db_session.refresh(stored)
    assert resent.token != created.token
    assert stored.token == hashlib.sha256(resent.token.encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_matching_user_accepts_invitation_and_becomes_member(db_session):
    owner, invitee, _, project = await _seed(db_session)
    created = await project_router.create_project_invitation(project.id, invitee.email, db_session, owner)

    accepted = await project_router.accept_project_invitation(created.token, db_session, invitee)

    assert accepted.status == "accepted"
    assert accepted.project_id == project.id
    membership = (
        await db_session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == invitee.id,
            )
        )
    ).scalar_one_or_none()
    assert membership is not None
    invitation = (await db_session.execute(select(ProjectInvitation))).scalar_one()
    assert invitation.accepted_at is not None


@pytest.mark.asyncio
async def test_invitation_rejects_wrong_email_and_revoked_token(db_session):
    owner, invitee, other, project = await _seed(db_session)
    created = await project_router.create_project_invitation(project.id, invitee.email, db_session, owner)
    invitation = (await db_session.execute(select(ProjectInvitation))).scalar_one()

    with pytest.raises(HTTPException, match="Invitation email does not match"):
        await project_router.accept_project_invitation(created.token, db_session, other)

    await project_router.revoke_project_invitation(project.id, invitation.id, db_session, owner)
    with pytest.raises(HTTPException, match="Invitation has been revoked"):
        await project_router.accept_project_invitation(created.token, db_session, invitee)
