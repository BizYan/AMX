"""P5 persistent traceability and impact-analysis workflow tests."""

import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-traceability-impact-p5.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-traceability-impact-p5-secret"

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

import app.db.init_schema  # noqa: F401 - registers sqlite compilers for UUID/JSONB
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
import app.models.identity  # noqa: F401 - registers tenant/user tables for FK targets
import app.models.projects  # noqa: F401 - registers project tables for FK targets
from app.domains.change.models import (
    DocumentImpactAnalysis,
    DocumentReference,
    DocumentSyncProposal,
)
from app.domains.change.service import TraceabilityService
from app.domains.documents.models import (
    Document,
    DocumentStatus,
    DocumentType,
    DocumentVersion,
)


@pytest.fixture
async def db_session():
    """Create a disposable async SQLite database with registered domain models."""
    deduplicate_indexes()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()


def _document(
    *,
    tenant_id,
    project_id,
    user_id,
    doc_type,
    title,
    content,
    version=1,
    status=DocumentStatus.PUBLISHED.value,
):
    return Document(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        doc_type=doc_type,
        title=title,
        content=content,
        status=status,
        version=version,
        created_by=user_id,
        metadata_json={},
    )


@pytest.mark.asyncio
async def test_create_document_reference_requires_published_documents(db_session):
    tenant_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    urs = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.URS.value,
        title="URS-001 Account security",
        content="Users need audited account controls.",
        version=2,
    )
    prd = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.PRD.value,
        title="PRD-001 Account security",
        content="Product behavior for account controls.",
    )
    draft_test = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.TEST_CASE.value,
        title="TC-001 Draft coverage",
        content="Draft test cases.",
        status=DocumentStatus.DRAFT.value,
    )
    db_session.add_all([urs, prd, draft_test])
    await db_session.flush()

    service = TraceabilityService(db_session)
    reference = await service.create_document_reference(
        tenant_id=tenant_id,
        project_id=project_id,
        source_document_id=urs.id,
        target_document_id=prd.id,
        reference_type="derives_from",
        created_by=user_id,
        source_section="1. Business need",
        target_section="2. Product behavior",
    )

    assert reference.source_document_version == 2
    assert reference.target_document_version == 1
    assert reference.status == "active"

    outgoing = await service.list_document_references(
        tenant_id=tenant_id,
        document_id=urs.id,
        direction="outgoing",
    )
    assert [item.id for item in outgoing] == [reference.id]

    with pytest.raises(ValueError, match="published"):
        await service.create_document_reference(
            tenant_id=tenant_id,
            project_id=project_id,
            source_document_id=prd.id,
            target_document_id=draft_test.id,
            reference_type="validated_by",
            created_by=user_id,
        )


@pytest.mark.asyncio
async def test_impact_analysis_generates_sync_proposal_and_apply_creates_new_version(db_session):
    tenant_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    urs = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.URS.value,
        title="URS-002 Password reset",
        content="Password reset must require audit logging.",
        version=3,
    )
    prd = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.PRD.value,
        title="PRD-002 Password reset",
        content="Existing PRD password reset flow.",
        version=4,
    )
    db_session.add_all([urs, prd])
    await db_session.flush()

    service = TraceabilityService(db_session)
    reference = await service.create_document_reference(
        tenant_id=tenant_id,
        project_id=project_id,
        source_document_id=urs.id,
        target_document_id=prd.id,
        reference_type="derives_from",
        created_by=user_id,
    )

    analysis = await service.create_document_impact_analysis(
        tenant_id=tenant_id,
        document_id=urs.id,
        created_by=user_id,
        trigger_type="content_changed",
        summary="URS password reset requirement changed",
    )

    proposals_result = await db_session.execute(
        select(DocumentSyncProposal).where(
            DocumentSyncProposal.impact_analysis_id == analysis.id
        )
    )
    proposals = list(proposals_result.scalars().all())
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.reference_id == reference.id
    assert proposal.target_document_id == prd.id
    assert proposal.status == "pending"
    assert proposal.impact_level == "high"
    assert "Password reset must require audit logging" in proposal.candidate_content

    applied = await service.apply_sync_proposal(
        proposal_id=proposal.id,
        tenant_id=tenant_id,
        decided_by=user_id,
        decision_note="Accepted PRD sync",
    )

    await db_session.refresh(prd)
    await db_session.refresh(reference)
    assert applied.status == "applied"
    assert applied.result_document_version == 5
    assert prd.version == 5
    assert "Password reset must require audit logging" in prd.content
    assert reference.target_document_version == 5

    version_count = await db_session.scalar(
        select(func.count(DocumentVersion.id)).where(DocumentVersion.document_id == prd.id)
    )
    assert version_count == 1


@pytest.mark.asyncio
async def test_reject_sync_proposal_closes_without_changing_document(db_session):
    tenant_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    urs = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.URS.value,
        title="URS-003 Session timeout",
        content="Sessions expire after 15 minutes.",
    )
    prd = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.PRD.value,
        title="PRD-003 Session timeout",
        content="Existing session timeout behavior.",
        version=2,
    )
    db_session.add_all([urs, prd])
    await db_session.flush()

    service = TraceabilityService(db_session)
    await service.create_document_reference(
        tenant_id=tenant_id,
        project_id=project_id,
        source_document_id=urs.id,
        target_document_id=prd.id,
        reference_type="derives_from",
        created_by=user_id,
    )
    analysis = await service.create_document_impact_analysis(
        tenant_id=tenant_id,
        document_id=urs.id,
        created_by=user_id,
        trigger_type="content_changed",
    )
    proposal = (
        await db_session.execute(
            select(DocumentSyncProposal).where(
                DocumentSyncProposal.impact_analysis_id == analysis.id
            )
        )
    ).scalar_one()

    rejected = await service.reject_sync_proposal(
        proposal_id=proposal.id,
        tenant_id=tenant_id,
        decided_by=user_id,
        decision_note="PRD already covers this in another section",
    )

    await db_session.refresh(prd)
    assert rejected.status == "rejected"
    assert rejected.decision_note == "PRD already covers this in another section"
    assert prd.version == 2
    assert prd.content == "Existing session timeout behavior."


@pytest.mark.asyncio
async def test_traceability_coverage_identifies_gaps_and_suggestions(db_session):
    tenant_id = uuid4()
    project_id = uuid4()
    other_project_id = uuid4()
    user_id = uuid4()
    urs = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.URS.value,
        title="URS-004 Customer onboarding",
        content="Users need guided onboarding.",
    )
    brd = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.BRD.value,
        title="BRD-004 Customer onboarding",
        content="Business onboarding process.",
    )
    prd = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.PRD.value,
        title="PRD-004 Customer onboarding",
        content="Product onboarding requirements.",
    )
    design = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.DETAILED_DESIGN.value,
        title="DD-004 Customer onboarding",
        content="Detailed onboarding design.",
    )
    test_case = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.TEST_CASE.value,
        title="TC-004 Customer onboarding",
        content="Onboarding acceptance tests.",
    )
    draft_data_dictionary = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.DATA_DICTIONARY.value,
        title="DATA-004 Customer onboarding",
        content="Draft onboarding data fields.",
        status=DocumentStatus.DRAFT.value,
    )
    cross_project_prd = _document(
        tenant_id=tenant_id,
        project_id=other_project_id,
        user_id=user_id,
        doc_type=DocumentType.PRD.value,
        title="PRD-999 Other project",
        content="Must not be suggested for this project.",
    )
    db_session.add_all([
        urs,
        brd,
        prd,
        design,
        test_case,
        draft_data_dictionary,
        cross_project_prd,
    ])
    await db_session.flush()

    service = TraceabilityService(db_session)
    await service.create_document_reference(
        tenant_id=tenant_id,
        project_id=project_id,
        source_document_id=urs.id,
        target_document_id=brd.id,
        reference_type="derives_from",
        created_by=user_id,
    )
    analysis = DocumentImpactAnalysis(
        tenant_id=tenant_id,
        project_id=project_id,
        trigger_document_id=urs.id,
        trigger_document_version=urs.version,
        trigger_type="content_changed",
        impact_level="high",
        status="open",
        summary="Open onboarding impact analysis",
        analysis_json={},
        created_by=user_id,
    )
    db_session.add(analysis)
    await db_session.flush()
    db_session.add(
        DocumentSyncProposal(
            tenant_id=tenant_id,
            impact_analysis_id=analysis.id,
            project_id=project_id,
            reference_id=None,
            source_document_id=urs.id,
            target_document_id=brd.id,
            target_document_version=brd.version,
            impact_level="high",
            reason="Pending sync review",
            suggested_action="sync_content",
            status="pending",
            metadata_json={},
        )
    )
    await db_session.flush()

    coverage = await service.get_traceability_coverage(
        tenant_id=tenant_id,
        project_id=project_id,
    )

    assert coverage.summary.total_documents == 6
    assert coverage.summary.published_documents == 5
    assert coverage.summary.referenced_documents == 2
    assert coverage.summary.orphan_documents == 3
    assert coverage.summary.coverage_rate == 40.0
    assert coverage.summary.open_impact_analyses == 1
    assert coverage.summary.pending_sync_proposals == 1

    gap_codes_by_doc = {
        (gap.document_id, gap.code)
        for gap in coverage.gaps
    }
    assert (prd.id, "missing_upstream") in gap_codes_by_doc
    assert (brd.id, "missing_downstream") in gap_codes_by_doc
    assert (draft_data_dictionary.id, "unpublished") in gap_codes_by_doc
    assert (design.id, "orphan_document") in gap_codes_by_doc

    suggestion_pairs = {
        (suggestion.source_document_id, suggestion.target_document_id)
        for suggestion in coverage.suggestions
    }
    assert (brd.id, prd.id) in suggestion_pairs
    assert (prd.id, design.id) in suggestion_pairs
    assert (design.id, test_case.id) in suggestion_pairs
    assert (design.id, draft_data_dictionary.id) not in suggestion_pairs
    assert all(
        suggestion.target_document_id != cross_project_prd.id
        for suggestion in coverage.suggestions
    )


@pytest.mark.asyncio
async def test_accept_traceability_suggestions_creates_version_pinned_references(db_session):
    tenant_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    urs = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.URS.value,
        title="URS-005 Release controls",
        content="Release must be auditable.",
        version=2,
    )
    brd = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.BRD.value,
        title="BRD-005 Release controls",
        content="Business release process.",
        version=3,
    )
    prd = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.PRD.value,
        title="PRD-005 Release controls",
        content="Product release requirements.",
        version=4,
    )
    design = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.DETAILED_DESIGN.value,
        title="DD-005 Release controls",
        content="Detailed release design.",
        version=5,
    )
    test_case = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.TEST_CASE.value,
        title="TC-005 Release controls",
        content="Release control tests.",
        version=6,
    )
    db_session.add_all([urs, brd, prd, design, test_case])
    await db_session.flush()

    service = TraceabilityService(db_session)
    result = await service.accept_reference_suggestions(
        tenant_id=tenant_id,
        project_id=project_id,
        created_by=user_id,
    )

    assert result.created == 4
    assert result.skipped == 0
    assert {item.status for item in result.items} == {"created"}

    references = list(
        (
            await db_session.execute(
                select(DocumentReference).where(
                    DocumentReference.tenant_id == tenant_id,
                    DocumentReference.project_id == project_id,
                    DocumentReference.status == "active",
                )
            )
        ).scalars()
    )
    assert len(references) == 4
    versions_by_pair = {
        (reference.source_document_id, reference.target_document_id): (
            reference.source_document_version,
            reference.target_document_version,
        )
        for reference in references
    }
    assert versions_by_pair[(urs.id, brd.id)] == (2, 3)
    assert versions_by_pair[(brd.id, prd.id)] == (3, 4)
    assert versions_by_pair[(prd.id, design.id)] == (4, 5)
    assert versions_by_pair[(design.id, test_case.id)] == (5, 6)

    second = await service.accept_reference_suggestions(
        tenant_id=tenant_id,
        project_id=project_id,
        created_by=user_id,
    )
    assert second.created == 0
    assert second.skipped == 0


@pytest.mark.asyncio
async def test_accept_traceability_suggestions_does_not_emit_placeholder_ids_for_invalid_requested_id(db_session):
    service = TraceabilityService(db_session)

    result = await service.accept_reference_suggestions(
        tenant_id=uuid4(),
        project_id=uuid4(),
        created_by=uuid4(),
        suggestion_ids=["not-a-valid-suggestion-id"],
    )

    assert result.created == 0
    assert result.skipped == 1
    item = result.items[0]
    assert item.status == "skipped"
    assert item.reason == "invalid_suggestion_id"
    assert item.source_document_id is None
    assert item.target_document_id is None
    assert item.reference_type == "unknown"
    assert "00000000-0000-0000-0000-000000000000" not in item.model_dump_json()
