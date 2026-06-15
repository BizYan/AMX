"""Persistent document conflict scan tests."""

import os
from datetime import datetime, timezone
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-persisted-conflict-scan.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-persisted-conflict-scan-secret"

import pytest
from sqlalchemy import select
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
from app.domains.change.conflict_service import ConflictGovernanceService, build_conflict_fingerprint
from app.domains.change.models import ChangeRequest, ChangeStatus, ConflictStatus, DocumentConflict, DocumentConflictDecision
from app.domains.change.schemas import DocumentConflictDecisionResponse, DocumentConflictResponse
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


async def create_project_graph(db_session):
    tenant = Tenant(name="Scan Tenant", slug=f"tenant-{uuid4()}")
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
        name="Scan Project",
        slug=f"project-{uuid4()}",
        owner_id=user.id,
    )
    db_session.add(project)
    await db_session.flush()
    parent = Document(
        tenant_id=tenant.id,
        project_id=project.id,
        doc_type=DocumentType.URS.value,
        title="URS parent",
        content="Parent",
        status=DocumentStatus.PUBLISHED.value,
        version=1,
        created_by=user.id,
        metadata_json={},
    )
    child = Document(
        tenant_id=tenant.id,
        project_id=project.id,
        doc_type=DocumentType.BRD.value,
        title="BRD missing parent",
        content="Child",
        status=DocumentStatus.PUBLISHED.value,
        version=2,
        created_by=user.id,
        metadata_json={},
    )
    db_session.add_all([parent, child])
    await db_session.flush()
    return tenant, project, parent, child


async def create_user(db_session, tenant_id):
    user = User(
        tenant_id=tenant_id,
        email=f"{uuid4()}@example.com",
        hashed_password="hashed",
    )
    db_session.add(user)
    await db_session.flush()
    return user


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
        assignee_user_id=user.id,
        assignment_source="primary_document_owner",
        assigned_at=now,
    )
    db_session.add(conflict)
    await db_session.flush()

    payload = DocumentConflictResponse.model_validate(conflict)
    assert payload.rule_key == "missing_parent"
    assert payload.evidence_json == {"potential_parent_count": 1}
    assert payload.assignee_user_id == user.id
    assert payload.assignment_source == "primary_document_owner"
    assert payload.assigned_at == now


@pytest.mark.asyncio
async def test_document_conflict_decision_schema_serializes_history(db_session):
    tenant, project, _, child = await create_project_graph(db_session)
    actor = await db_session.scalar(select(User).where(User.tenant_id == tenant.id))
    assert actor is not None
    now = datetime.now(timezone.utc)
    conflict = DocumentConflict(
        tenant_id=tenant.id,
        project_id=project.id,
        rule_key="missing_parent",
        fingerprint="b" * 64,
        severity="high",
        status=ConflictStatus.DECISION.value,
        primary_document_id=child.id,
        primary_document_version=child.version,
        summary="BRD is missing an upstream document",
        evidence_json={"candidate_parent_count": 1},
        first_detected_at=now,
        last_detected_at=now,
        last_scan_id=uuid4(),
    )
    db_session.add(conflict)
    await db_session.flush()
    decision = DocumentConflictDecision(
        tenant_id=tenant.id,
        project_id=project.id,
        conflict_id=conflict.id,
        actor_id=actor.id,
        action="complete_analysis",
        previous_status=ConflictStatus.ANALYSIS.value,
        resulting_status=ConflictStatus.DECISION.value,
        reason="Ready for decision",
        evidence_json={"notes": "Reviewed rule evidence"},
    )
    db_session.add(decision)
    await db_session.flush()

    payload = DocumentConflictDecisionResponse.model_validate(decision)

    assert payload.action == "complete_analysis"
    assert payload.previous_status == ConflictStatus.ANALYSIS.value
    assert payload.resulting_status == ConflictStatus.DECISION.value
    assert payload.reason == "Ready for decision"
    assert payload.evidence_json == {"notes": "Reviewed rule evidence"}


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


@pytest.mark.asyncio
async def test_project_scan_creates_and_refreshes_same_conflict(db_session):
    tenant, project, _, _ = await create_project_graph(db_session)
    service = ConflictGovernanceService(db_session)

    first = await service.scan_project(tenant_id=tenant.id, project_id=project.id)
    second = await service.scan_project(tenant_id=tenant.id, project_id=project.id)

    assert first.created == 1
    assert second.created == 0
    assert second.refreshed == 1
    assert second.items[0].id == first.items[0].id


@pytest.mark.asyncio
async def test_project_scan_assigns_new_conflict_to_primary_document_owner(db_session):
    tenant, project, _, child = await create_project_graph(db_session)
    service = ConflictGovernanceService(db_session)

    scan = await service.scan_project(tenant_id=tenant.id, project_id=project.id)

    conflict = scan.items[0]
    assert conflict.assignee_user_id == child.created_by
    assert conflict.assignment_source == "primary_document_owner"
    assert conflict.assigned_at is not None
    assert conflict.status == ConflictStatus.ANALYSIS.value

    decisions = (
        await db_session.execute(
            select(DocumentConflictDecision).where(
                DocumentConflictDecision.conflict_id == conflict.id,
            )
        )
    ).scalars().all()
    assert len(decisions) == 1
    assert decisions[0].action == "assign"
    assert decisions[0].actor_id == child.created_by
    assert decisions[0].resulting_status == ConflictStatus.ANALYSIS.value
    assert decisions[0].evidence_json["assignment_source"] == "primary_document_owner"


@pytest.mark.asyncio
async def test_project_scan_marks_missing_fingerprint_absent_without_closing(db_session):
    tenant, project, parent, child = await create_project_graph(db_session)
    service = ConflictGovernanceService(db_session)
    first = await service.scan_project(tenant_id=tenant.id, project_id=project.id)
    child.parent_document_id = parent.id
    await db_session.flush()

    second = await service.scan_project(tenant_id=tenant.id, project_id=project.id)
    conflict = await service.get_conflict(
        tenant_id=tenant.id,
        conflict_id=first.items[0].id,
    )

    assert second.marked_absent == 1
    assert conflict is not None
    assert conflict.absent_since is not None
    assert conflict.status != ConflictStatus.CLOSED.value


@pytest.mark.asyncio
async def test_project_scan_reopens_closed_conflict_when_fingerprint_reappears(db_session):
    tenant, project, _, _ = await create_project_graph(db_session)
    service = ConflictGovernanceService(db_session)
    first = await service.scan_project(tenant_id=tenant.id, project_id=project.id)
    conflict = (
        await db_session.execute(
            select(DocumentConflict).where(DocumentConflict.id == first.items[0].id)
        )
    ).scalar_one()
    conflict.status = ConflictStatus.CLOSED.value
    conflict.closed_at = datetime.now(timezone.utc)
    await db_session.flush()

    second = await service.scan_project(tenant_id=tenant.id, project_id=project.id)

    assert second.reopened == 1
    assert second.items[0].status == ConflictStatus.ANALYSIS.value
    assert second.items[0].closed_at is None


@pytest.mark.asyncio
async def test_conflict_reads_are_tenant_isolated(db_session):
    tenant, project, _, _ = await create_project_graph(db_session)
    service = ConflictGovernanceService(db_session)
    scan = await service.scan_project(tenant_id=tenant.id, project_id=project.id)

    own_list = await service.list_project_conflicts(
        tenant_id=tenant.id,
        project_id=project.id,
    )
    other_list = await service.list_project_conflicts(
        tenant_id=uuid4(),
        project_id=project.id,
    )
    other_detail = await service.get_conflict(
        tenant_id=uuid4(),
        conflict_id=scan.items[0].id,
    )

    assert own_list.total == 1
    assert other_list.total == 0
    assert other_detail is None


@pytest.mark.asyncio
async def test_duplicate_conflict_insert_returns_existing_record(db_session):
    tenant, project, _, child = await create_project_graph(db_session)
    service = ConflictGovernanceService(db_session)
    first = await service.scan_project(tenant_id=tenant.id, project_id=project.id)
    existing = first.items[0]
    now = datetime.now(timezone.utc)
    duplicate = DocumentConflict(
        tenant_id=tenant.id,
        project_id=project.id,
        rule_key=existing.rule_key,
        fingerprint=existing.fingerprint,
        severity=existing.severity,
        status=existing.status,
        primary_document_id=child.id,
        primary_document_version=child.version,
        summary=existing.summary,
        evidence_json=existing.evidence_json,
        first_detected_at=now,
        last_detected_at=now,
        last_scan_id=uuid4(),
    )

    persisted, created = await service.persist_new_conflict(duplicate)

    assert created is False
    assert persisted.id == existing.id


@pytest.mark.asyncio
async def test_project_owner_can_reassign_conflict_and_records_history(db_session):
    tenant, project, _, _ = await create_project_graph(db_session)
    new_assignee = await create_user(db_session, tenant.id)
    service = ConflictGovernanceService(db_session)
    scan = await service.scan_project(tenant_id=tenant.id, project_id=project.id)

    updated = await service.assign_conflict(
        tenant_id=tenant.id,
        conflict_id=scan.items[0].id,
        actor_id=project.owner_id,
        assignee_user_id=new_assignee.id,
        reason="Assign to reviewer",
    )

    assert updated.assignee_user_id == new_assignee.id
    assert updated.assignment_source == "manual"
    assert updated.assigned_at is not None
    decisions = (
        await db_session.execute(
            select(DocumentConflictDecision)
            .where(DocumentConflictDecision.conflict_id == updated.id)
            .order_by(DocumentConflictDecision.created_at)
        )
    ).scalars().all()
    assert [decision.action for decision in decisions] == ["assign", "assign"]
    assert decisions[-1].actor_id == project.owner_id
    assert decisions[-1].reason == "Assign to reviewer"
    assert decisions[-1].evidence_json["assignee_user_id"] == str(new_assignee.id)


@pytest.mark.asyncio
async def test_non_owner_cannot_reassign_conflict(db_session):
    tenant, project, _, _ = await create_project_graph(db_session)
    outsider = await create_user(db_session, tenant.id)
    new_assignee = await create_user(db_session, tenant.id)
    service = ConflictGovernanceService(db_session)
    scan = await service.scan_project(tenant_id=tenant.id, project_id=project.id)

    with pytest.raises(PermissionError, match="Only project owner can assign conflicts"):
        await service.assign_conflict(
            tenant_id=tenant.id,
            conflict_id=scan.items[0].id,
            actor_id=outsider.id,
            assignee_user_id=new_assignee.id,
            reason="Take over",
        )


@pytest.mark.asyncio
async def test_assignee_can_complete_analysis_and_project_owner_can_reject(db_session):
    tenant, project, _, child = await create_project_graph(db_session)
    service = ConflictGovernanceService(db_session)
    scan = await service.scan_project(tenant_id=tenant.id, project_id=project.id)

    decision_ready = await service.complete_analysis(
        tenant_id=tenant.id,
        conflict_id=scan.items[0].id,
        actor_id=child.created_by,
        reason="Reviewed rule evidence",
        evidence={"finding": "valid"},
    )
    assert decision_ready.status == ConflictStatus.DECISION.value

    rejected = await service.reject_conflict(
        tenant_id=tenant.id,
        conflict_id=decision_ready.id,
        actor_id=project.owner_id,
        reason="False positive after review",
        evidence={"resolution": "document scope excludes parent"},
    )

    assert rejected.status == ConflictStatus.REJECTED.value
    decisions = (
        await db_session.execute(
            select(DocumentConflictDecision)
            .where(DocumentConflictDecision.conflict_id == rejected.id)
            .order_by(DocumentConflictDecision.created_at)
        )
    ).scalars().all()
    assert [decision.action for decision in decisions] == [
        "assign",
        "complete_analysis",
        "reject",
    ]
    assert decisions[-2].previous_status == ConflictStatus.ANALYSIS.value
    assert decisions[-2].resulting_status == ConflictStatus.DECISION.value
    assert decisions[-1].previous_status == ConflictStatus.DECISION.value
    assert decisions[-1].resulting_status == ConflictStatus.REJECTED.value


@pytest.mark.asyncio
async def test_invalid_reject_transition_does_not_record_history(db_session):
    tenant, project, _, _ = await create_project_graph(db_session)
    service = ConflictGovernanceService(db_session)
    scan = await service.scan_project(tenant_id=tenant.id, project_id=project.id)

    with pytest.raises(ValueError, match="Conflict must be in decision status"):
        await service.reject_conflict(
            tenant_id=tenant.id,
            conflict_id=scan.items[0].id,
            actor_id=project.owner_id,
            reason="Too early",
            evidence={},
        )

    reject_decisions = (
        await db_session.execute(
            select(DocumentConflictDecision).where(
                DocumentConflictDecision.conflict_id == scan.items[0].id,
                DocumentConflictDecision.action == "reject",
            )
        )
    ).scalars().all()
    assert reject_decisions == []


@pytest.mark.asyncio
async def test_project_owner_accepts_revision_and_creates_linked_draft_change_request(db_session):
    tenant, project, parent, child = await create_project_graph(db_session)
    service = ConflictGovernanceService(db_session)
    scan = await service.scan_project(tenant_id=tenant.id, project_id=project.id)
    ready = await service.complete_analysis(
        tenant_id=tenant.id,
        conflict_id=scan.items[0].id,
        actor_id=child.created_by,
        reason="Revision needed",
        evidence={"finding": "valid"},
    )

    accepted = await service.accept_revision(
        tenant_id=tenant.id,
        conflict_id=ready.id,
        actor_id=project.owner_id,
        suggested_revision="Link the BRD to the approved URS parent.",
        reason="Use existing URS as upstream source",
        evidence={"target_section": "parent link"},
    )

    assert accepted.status == ConflictStatus.REVISION_ACCEPTED.value
    assert accepted.linked_change_request_id is not None
    assert accepted.accepted_revision_json == {
        "suggested_revision": "Link the BRD to the approved URS parent.",
        "evidence": {"target_section": "parent link"},
    }
    change_request = await db_session.get(ChangeRequest, accepted.linked_change_request_id)
    assert change_request is not None
    assert change_request.status == ChangeStatus.DRAFT.value
    assert change_request.project_id == project.id
    assert change_request.source_document_id == child.id
    assert change_request.target_document_id == parent.id
    assert change_request.requested_by == project.owner_id
    assert "Link the BRD" in change_request.description
    assert str(accepted.id) in change_request.rationale

    decisions = (
        await db_session.execute(
            select(DocumentConflictDecision)
            .where(DocumentConflictDecision.conflict_id == accepted.id)
            .order_by(DocumentConflictDecision.created_at)
        )
    ).scalars().all()
    assert decisions[-1].action == "accept_revision"
    assert decisions[-1].previous_status == ConflictStatus.DECISION.value
    assert decisions[-1].resulting_status == ConflictStatus.REVISION_ACCEPTED.value
    assert decisions[-1].evidence_json["change_request_id"] == str(change_request.id)


@pytest.mark.asyncio
async def test_accept_revision_requires_decision_status_and_does_not_create_change_request(db_session):
    tenant, project, _, _ = await create_project_graph(db_session)
    service = ConflictGovernanceService(db_session)
    scan = await service.scan_project(tenant_id=tenant.id, project_id=project.id)

    with pytest.raises(ValueError, match="Conflict must be in decision status"):
        await service.accept_revision(
            tenant_id=tenant.id,
            conflict_id=scan.items[0].id,
            actor_id=project.owner_id,
            suggested_revision="Too early",
            reason="Invalid transition",
            evidence={},
        )

    change_requests = (await db_session.execute(select(ChangeRequest))).scalars().all()
    accept_decisions = (
        await db_session.execute(
            select(DocumentConflictDecision).where(
                DocumentConflictDecision.conflict_id == scan.items[0].id,
                DocumentConflictDecision.action == "accept_revision",
            )
        )
    ).scalars().all()
    assert change_requests == []
    assert accept_decisions == []
