"""Change audit command center aggregation tests."""

import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-change-audit-command-center.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-change-audit-command-center-secret"

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

import app.db.init_schema  # noqa: F401 - registers sqlite compilers for UUID/JSONB
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.change.models import (
    ChangeRequest,
    DocumentImpactAnalysis,
    DocumentSyncProposal,
    FieldPatch,
)
from app.domains.change.service import ChangeAuditCommandCenterService
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
async def test_change_audit_command_center_blocks_release_for_open_traceability_risks(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    source_document_id = uuid4()
    target_document_id = uuid4()
    change_request_id = uuid4()
    impact_analysis_id = uuid4()

    tenant = Tenant(id=tenant_id, name="Audit Tenant", slug="audit-tenant")
    user = User(
        id=user_id,
        tenant_id=tenant_id,
        email="audit-owner@example.com",
        hashed_password="test",
        full_name="Audit Owner",
    )
    project = Project(
        id=project_id,
        tenant_id=tenant_id,
        owner_id=user_id,
        name="Change Audit Project",
        slug="change-audit-project",
    )
    source_document = Document(
        id=source_document_id,
        tenant_id=tenant_id,
        project_id=project_id,
        doc_type=DocumentType.URS.value,
        title="URS Account Controls",
        content="Account controls changed.",
        status=DocumentStatus.PUBLISHED.value,
        version=2,
        created_by=user_id,
        metadata_json={},
    )
    target_document = Document(
        id=target_document_id,
        tenant_id=tenant_id,
        project_id=project_id,
        doc_type=DocumentType.BRD.value,
        title="BRD Account Controls",
        content="Business response for account controls.",
        status=DocumentStatus.PUBLISHED.value,
        version=1,
        created_by=user_id,
        metadata_json={},
    )
    change_request = ChangeRequest(
        id=change_request_id,
        tenant_id=tenant_id,
        project_id=project_id,
        source_document_id=source_document_id,
        source_document_version=2,
        target_document_id=target_document_id,
        target_document_version=1,
        change_type="dependency",
        priority="critical",
        status="open",
        description="URS critical control changed and downstream BRD must be reviewed.",
        requested_by=user_id,
    )
    field_patch = FieldPatch(
        tenant_id=tenant_id,
        change_request_id=change_request_id,
        document_id=target_document_id,
        document_version=1,
        field_path="sections.2.content",
        old_value="old",
        new_value="new",
        patch_type="replace",
        status="pending",
    )
    impact_analysis = DocumentImpactAnalysis(
        id=impact_analysis_id,
        tenant_id=tenant_id,
        project_id=project_id,
        trigger_document_id=source_document_id,
        trigger_document_version=2,
        change_request_id=change_request_id,
        trigger_type="content_changed",
        impact_level="high",
        status="open",
        summary="Critical source change has downstream impact.",
        analysis_json={"affected_document_count": 1},
        created_by=user_id,
    )
    sync_proposal = DocumentSyncProposal(
        tenant_id=tenant_id,
        impact_analysis_id=impact_analysis_id,
        project_id=project_id,
        reference_id=None,
        source_document_id=source_document_id,
        target_document_id=target_document_id,
        target_document_version=1,
        impact_level="high",
        reason="BRD must sync with URS.",
        suggested_action="review_and_sync",
        status="pending",
        metadata_json={},
    )
    db_session.add_all([
        tenant,
        user,
        project,
        source_document,
        target_document,
        change_request,
        field_patch,
        impact_analysis,
        sync_proposal,
    ])
    await db_session.flush()

    command_center = await ChangeAuditCommandCenterService(db_session).get_command_center(
        tenant_id=tenant_id,
        project_id=project_id,
    )

    assert command_center.release_gate.status == "blocked"
    assert command_center.summary.total_changes == 1
    assert command_center.summary.critical_or_high_open_changes == 1
    assert command_center.summary.pending_field_patches == 1
    assert command_center.summary.open_impact_analyses == 1
    assert command_center.summary.pending_sync_proposals == 1
    assert command_center.change_status_counts == {"open": 1}
    assert command_center.priority_counts == {"critical": 1}
    assert {item.code for item in command_center.risk_items} >= {
        "critical_open_changes",
        "pending_field_patches",
        "open_impact_analyses",
        "pending_sync_proposals",
    }
    assert command_center.priority_actions[0].href == "/documents/contradictions"


@pytest.mark.asyncio
async def test_change_audit_command_center_passes_without_open_risks(db_session):
    tenant_id = uuid4()
    user_id = uuid4()

    db_session.add_all([
        Tenant(id=tenant_id, name="Clean Tenant", slug="clean-tenant"),
        User(
            id=user_id,
            tenant_id=tenant_id,
            email="clean-owner@example.com",
            hashed_password="test",
            full_name="Clean Owner",
        ),
    ])
    await db_session.flush()

    command_center = await ChangeAuditCommandCenterService(db_session).get_command_center(
        tenant_id=tenant_id,
    )

    assert command_center.release_gate.status == "passed"
    assert command_center.summary.total_changes == 0
    assert command_center.risk_items == []
    assert command_center.priority_actions[0].code == "maintain_audit_review"
