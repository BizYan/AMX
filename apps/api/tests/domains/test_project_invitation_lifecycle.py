"""Tests for the governed project invitation lifecycle."""

import hashlib
import os
from types import SimpleNamespace
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
from app.core.security import decode_token, verify_password
from app.domains.identity.models import AuditLog
from app.domains.projects import router as project_router
from app.domains.projects.models import ProjectInvitation
from app.models.identity import Role, Tenant, User, UserRole
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
    assert stored.delivery_status == "pending"


@pytest.mark.asyncio
async def test_owner_records_delivery_failure_and_success_without_exposing_token(db_session):
    owner, invitee, _, project = await _seed(db_session)
    created = await project_router.create_project_invitation(project.id, invitee.email, db_session, owner)
    invitation = (await db_session.execute(select(ProjectInvitation))).scalar_one()

    failed = await project_router.record_project_invitation_delivery(
        project.id,
        invitation.id,
        SimpleNamespace(status="failed", channel="email", error="mailbox unavailable"),
        db_session,
        owner,
    )
    sent = await project_router.record_project_invitation_delivery(
        project.id,
        invitation.id,
        SimpleNamespace(status="sent", channel="manual", error=None),
        db_session,
        owner,
    )

    assert failed.delivery_status == "failed"
    assert sent.delivery_status == "sent"
    assert sent.delivery_attempt_count == 2
    assert sent.last_delivered_at is not None
    audits = list(
        (
            await db_session.scalars(
                select(AuditLog).where(AuditLog.action.like("project.invitation.delivery_%"))
            )
        ).all()
    )
    assert len(audits) == 2
    assert created.token not in str(audits)


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


@pytest.mark.asyncio
async def test_public_preview_hides_invalid_tokens_and_exposes_active_invitation(db_session):
    owner, _, _, project = await _seed(db_session)
    created = await project_router.create_project_invitation(
        project.id, "new.consultant@example.com", db_session, owner
    )

    preview = await project_router.preview_project_invitation(created.token, db_session)
    invalid = await project_router.preview_project_invitation("unknown-token", db_session)

    assert preview.status == "active"
    assert preview.project_name == project.name
    assert preview.masked_email == "n************t@example.com"
    assert preview.expires_at == created.expires_at
    assert invalid.status == "invalid"
    assert invalid.project_name is None
    assert invalid.masked_email is None


@pytest.mark.asyncio
async def test_external_invitee_activates_account_with_lowest_role_and_session(db_session):
    owner, _, _, project = await _seed(db_session)
    created = await project_router.create_project_invitation(
        project.id, "new.consultant@example.com", db_session, owner
    )

    activated = await project_router.activate_project_invitation(
        created.token,
        SimpleNamespace(full_name="New Consultant", password="SecurePass123!"),
        db_session,
    )

    user = (
        await db_session.execute(select(User).where(User.email == "new.consultant@example.com"))
    ).scalar_one()
    role = (
        await db_session.execute(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        )
    ).scalar_one()
    membership = (
        await db_session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user.id,
            )
        )
    ).scalar_one()
    invitation = (await db_session.execute(select(ProjectInvitation))).scalar_one()
    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "project.invitation.activate")
        )
    ).scalar_one()

    assert activated.project_id == project.id
    assert activated.user_id == user.id
    assert activated.status == "accepted"
    assert activated.access_token
    assert decode_token(activated.access_token)["sub"] == str(user.id)
    assert verify_password("SecurePass123!", user.hashed_password)
    assert user.tenant_id == project.tenant_id
    assert role.name == "project_member"
    assert role.permissions == {
        "projects": ["read"],
        "documents": ["read", "comment"],
        "collaboration": ["read", "write"],
    }
    assert membership.role_id == role.id
    assert invitation.accepted_at is not None
    assert audit.user_id == user.id
    assert created.token not in str(audit.extra_data)
    assert "SecurePass123!" not in str(audit.extra_data)

    with pytest.raises(HTTPException, match="already been accepted"):
        await project_router.activate_project_invitation(
            created.token,
            SimpleNamespace(full_name="Second User", password="OtherPass123!"),
            db_session,
        )


@pytest.mark.asyncio
async def test_activation_requires_existing_account_to_sign_in(db_session):
    owner, invitee, _, project = await _seed(db_session)
    created = await project_router.create_project_invitation(project.id, invitee.email, db_session, owner)

    with pytest.raises(HTTPException, match="Existing account must sign in"):
        await project_router.activate_project_invitation(
            created.token,
            SimpleNamespace(full_name="Duplicate User", password="SecurePass123!"),
            db_session,
        )

    invitation = (await db_session.execute(select(ProjectInvitation))).scalar_one()
    assert invitation.accepted_at is None


@pytest.mark.asyncio
async def test_activation_rejects_email_owned_by_another_tenant(db_session):
    owner, _, _, project = await _seed(db_session)
    created = await project_router.create_project_invitation(
        project.id, "external@example.com", db_session, owner
    )
    other_tenant = Tenant(id=uuid4(), name="Other Tenant", slug=f"other-{uuid4().hex[:8]}")
    db_session.add_all(
        [
            other_tenant,
            User(
                id=uuid4(),
                tenant_id=other_tenant.id,
                email="External@Example.com",
                full_name="External User",
                hashed_password="hashed",
            ),
        ]
    )
    await db_session.flush()

    with pytest.raises(HTTPException, match="Email belongs to another tenant"):
        await project_router.activate_project_invitation(
            created.token,
            SimpleNamespace(full_name="External User", password="SecurePass123!"),
            db_session,
        )
