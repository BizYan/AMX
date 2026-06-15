"""Change audit command center aggregation tests."""

import os
from datetime import datetime, timedelta, timezone
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
    ConflictStatus,
    DocumentImpactAnalysis,
    DocumentConflict,
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
async def test_change_audit_command_center_blocks_release_for_persisted_conflict_risks(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    document_id = uuid4()
    now = datetime.now(timezone.utc)

    tenant = Tenant(id=tenant_id, name="Conflict Tenant", slug="conflict-tenant")
    user = User(
        id=user_id,
        tenant_id=tenant_id,
        email="conflict-owner@example.com",
        hashed_password="test",
        full_name="Conflict Owner",
    )
    project = Project(
        id=project_id,
        tenant_id=tenant_id,
        owner_id=user_id,
        name="Conflict Project",
        slug="conflict-project",
    )
    document = Document(
        id=document_id,
        tenant_id=tenant_id,
        project_id=project_id,
        doc_type=DocumentType.BRD.value,
        title="BRD Conflict Source",
        content="Business requirements with unresolved traceability.",
        status=DocumentStatus.PUBLISHED.value,
        version=1,
        created_by=user_id,
        metadata_json={},
    )
    high_decision_conflict = DocumentConflict(
        tenant_id=tenant_id,
        project_id=project_id,
        rule_key="missing_parent",
        fingerprint="a" * 64,
        severity="high",
        status=ConflictStatus.DECISION.value,
        primary_document_id=document_id,
        primary_document_version=1,
        related_document_id=None,
        related_document_version=None,
        summary="BRD has no parent URS.",
        evidence_json={"rule": "missing_parent"},
        first_detected_at=now,
        last_detected_at=now,
        last_scan_id=uuid4(),
    )
    expired_risk_conflict = DocumentConflict(
        tenant_id=tenant_id,
        project_id=project_id,
        rule_key="stale_reference",
        fingerprint="b" * 64,
        severity="medium",
        status=ConflictStatus.RISK_ACCEPTED.value,
        primary_document_id=document_id,
        primary_document_version=1,
        related_document_id=None,
        related_document_version=None,
        summary="Accepted risk has expired.",
        evidence_json={"rule": "stale_reference"},
        first_detected_at=now,
        last_detected_at=now,
        last_scan_id=uuid4(),
        risk_accepted_by=user_id,
        risk_accepted_at=now - timedelta(days=10),
        risk_acceptance_expires_at=now - timedelta(days=1),
        risk_acceptance_json={"mitigation_plan": "Temporary exception."},
    )
    accepted_revision_conflict = DocumentConflict(
        tenant_id=tenant_id,
        project_id=project_id,
        rule_key="conflicting_parent",
        fingerprint="c" * 64,
        severity="medium",
        status=ConflictStatus.REVISION_ACCEPTED.value,
        primary_document_id=document_id,
        primary_document_version=1,
        related_document_id=None,
        related_document_version=None,
        summary="Accepted revision still needs applied-change rescan closure.",
        evidence_json={"rule": "conflicting_parent"},
        first_detected_at=now,
        last_detected_at=now,
        last_scan_id=uuid4(),
        linked_change_request_id=uuid4(),
        accepted_revision_json={"suggested_revision": "Update parent link."},
        revision_accepted_at=now - timedelta(hours=1),
    )
    db_session.add_all([
        tenant,
        user,
        project,
        document,
        high_decision_conflict,
        expired_risk_conflict,
        accepted_revision_conflict,
    ])
    await db_session.flush()

    command_center = await ChangeAuditCommandCenterService(db_session).get_command_center(
        tenant_id=tenant_id,
        project_id=project_id,
    )

    assert command_center.release_gate.status == "blocked"
    assert command_center.summary.open_document_conflicts == 3
    assert command_center.summary.high_open_document_conflicts == 1
    assert command_center.summary.expired_conflict_risk_acceptances == 1
    assert command_center.summary.revision_accepted_conflicts == 1
    assert {item.code for item in command_center.risk_items} >= {
        "high_open_document_conflicts",
        "expired_conflict_risk_acceptances",
        "revision_accepted_conflicts",
    }
    assert command_center.priority_actions[0].code == "resolve_document_conflicts"
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
