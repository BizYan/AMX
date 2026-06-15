"""Persistent document conflict scan tests."""

import os
from datetime import datetime, timezone
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-persisted-conflict-scan.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-persisted-conflict-scan-secret"

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

import app.db.init_schema  # noqa: F401
import app.domains.change.models  # noqa: F401
import app.domains.documents.models  # noqa: F401
import app.models.identity  # noqa: F401
import app.models.projects  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.change.conflict_service import build_conflict_fingerprint
from app.domains.change.models import DocumentConflict
from app.domains.change.schemas import DocumentConflictResponse
from app.domains.documents.models import Document, DocumentStatus, DocumentType
from app.models.identity import Tenant, User
from app.models.projects import Project


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


@pytest.mark.asyncio
async def test_document_conflict_model_persists_rule_evidence(db_session):
    tenant = Tenant(name="Test Tenant", slug=f"tenant-{uuid4()}")
    db_session.add(tenant)
    await db_session.flush()
    user = User(
        tenant_id=tenant.id,
        email=f"{uuid4()}@example.com",
        hashed_password="hashed",
    )
    db_session.add(user)
    await db_session.flush()
    project = Project(
        tenant_id=tenant.id,
        name="Conflict Project",
        slug=f"project-{uuid4()}",
        owner_id=user.id,
    )
    db_session.add(project)
    await db_session.flush()
    document = Document(
        tenant_id=tenant.id,
        project_id=project.id,
        doc_type=DocumentType.PRD.value,
        title="PRD without parent",
        content="Content",
        status=DocumentStatus.PUBLISHED.value,
        version=2,
        created_by=user.id,
        metadata_json={},
    )
    db_session.add(document)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    conflict = DocumentConflict(
        tenant_id=tenant.id,
        project_id=project.id,
        rule_key="missing_parent",
        fingerprint="a" * 64,
        severity="high",
        status="analysis",
        primary_document_id=document.id,
        primary_document_version=2,
        summary="PRD is missing an upstream document",
        evidence_json={"potential_parent_count": 1},
        first_detected_at=now,
        last_detected_at=now,
        last_scan_id=uuid4(),
    )
    db_session.add(conflict)
    await db_session.flush()

    payload = DocumentConflictResponse.model_validate(conflict)
    assert payload.rule_key == "missing_parent"
    assert payload.evidence_json == {"potential_parent_count": 1}


def test_conflict_fingerprint_is_stable_when_summary_changes():
    tenant_id = uuid4()
    project_id = uuid4()
    document_id = uuid4()
    parent_id = uuid4()

    first = build_conflict_fingerprint(
        tenant_id=tenant_id,
        project_id=project_id,
        rule_key="missing_parent",
        primary_document_id=document_id,
        related_document_id=None,
        evidence={"candidate_parent_ids": [str(parent_id)], "summary": "first"},
    )
    second = build_conflict_fingerprint(
        tenant_id=tenant_id,
        project_id=project_id,
        rule_key="missing_parent",
        primary_document_id=document_id,
        related_document_id=None,
        evidence={"candidate_parent_ids": [str(parent_id)], "summary": "changed"},
    )

    assert first == second


def test_conflict_fingerprint_changes_for_different_related_document():
    tenant_id = uuid4()
    project_id = uuid4()
    document_id = uuid4()

    first = build_conflict_fingerprint(
        tenant_id=tenant_id,
        project_id=project_id,
        rule_key="inconsistent_link",
        primary_document_id=document_id,
        related_document_id=uuid4(),
        evidence={},
    )
    second = build_conflict_fingerprint(
        tenant_id=tenant_id,
        project_id=project_id,
        rule_key="inconsistent_link",
        primary_document_id=document_id,
        related_document_id=uuid4(),
        evidence={},
    )

    assert first != second
