"""Integration tests for document status authorization and project roles."""

import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-document-status-permissions-secret"

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401
import app.domains.collaboration.models  # noqa: F401
import app.domains.documents.models  # noqa: F401
import app.domains.identity.models  # noqa: F401
import app.models.identity  # noqa: F401
import app.models.projects  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.documents import router as document_router
from app.domains.documents.models import Document
from app.domains.documents.schemas import DocumentStatusUpdate
from app.models.identity import Role, Tenant, User
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


@pytest.mark.asyncio
async def test_project_roles_authorize_approve_and_publish_but_owner_cannot_bypass(db_session):
    tenant_id = uuid4()
    owner_id = uuid4()
    reviewer_id = uuid4()
    project_id = uuid4()
    reviewer_role_id = uuid4()
    publisher_role_id = uuid4()
    document_id = uuid4()

    tenant = Tenant(id=tenant_id, name="Delivery Tenant", slug="delivery-tenant")
    owner = User(
        id=owner_id,
        tenant_id=tenant_id,
        email="owner@example.com",
        full_name="Project Owner",
        hashed_password="hashed",
    )
    reviewer = User(
        id=reviewer_id,
        tenant_id=tenant_id,
        email="reviewer@example.com",
        full_name="Delegated Reviewer",
        hashed_password="hashed",
    )
    reviewer_role = Role(
        id=reviewer_role_id,
        tenant_id=tenant_id,
        name="Project Reviewer",
        permissions={"documents": ["review", "approve"]},
    )
    publisher_role = Role(
        id=publisher_role_id,
        tenant_id=tenant_id,
        name="Project Publisher",
        permissions={"documents": ["publish"]},
    )
    project = Project(
        id=project_id,
        tenant_id=tenant_id,
        owner_id=owner_id,
        name="Governed Delivery",
        slug="governed-delivery",
    )
    reviewer_membership = ProjectMember(
        project_id=project_id,
        user_id=reviewer_id,
        role_id=reviewer_role_id,
    )
    document = Document(
        id=document_id,
        tenant_id=tenant_id,
        project_id=project_id,
        doc_type="brd",
        title="Governed BRD",
        content="Approved content",
        status="review",
        created_by=owner_id,
        metadata_json={},
    )
    db_session.add_all([
        tenant,
        owner,
        reviewer,
        reviewer_role,
        publisher_role,
        project,
        reviewer_membership,
        document,
    ])
    await db_session.flush()

    with pytest.raises(HTTPException) as error:
        await document_router.update_document_status(
            document_id=document_id,
            data=DocumentStatusUpdate(status="invalid-status"),
            db=db_session,
            current_user=owner,
        )
    assert error.value.status_code == 400

    with pytest.raises(HTTPException) as error:
        await document_router.update_document_status(
            document_id=document_id,
            data=DocumentStatusUpdate(status="approved", reason="Owner approval attempt"),
            db=db_session,
            current_user=owner,
        )
    assert error.value.status_code == 403
    assert "documents.approve" in error.value.detail

    approved = await document_router.update_document_status(
        document_id=document_id,
        data=DocumentStatusUpdate(status="approved", reason="Delegated approval"),
        db=db_session,
        current_user=reviewer,
    )
    assert approved.status == "approved"
    assert approved.approved_by == reviewer_id

    reviewer_membership.role_id = publisher_role_id
    await db_session.flush()
    published = await document_router.update_document_status(
        document_id=document_id,
        data=DocumentStatusUpdate(status="published", reason="Delegated release"),
        db=db_session,
        current_user=reviewer,
    )
    assert published.status == "published"
    assert published.metadata_json["review_flow"]["status_history"][-1]["reason"] == "Delegated release"
