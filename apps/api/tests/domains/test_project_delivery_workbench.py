"""Tests for project delivery workbench aggregation."""

import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-project-delivery-workbench.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-project-delivery-workbench-secret"

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

import app.domains.agent.models  # noqa: F401 - registers skill tables for template bindings
import app.db.init_schema  # noqa: F401 - registers sqlite compilers for UUID/JSONB
import app.domains.collaboration.models  # noqa: F401 - registers collaboration tables
import app.domains.export.models  # noqa: F401 - registers export tables
import app.domains.templates.models  # noqa: F401 - registers template tables
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.change.models import ChangeRequest, DocumentImpactAnalysis, DocumentReference, DocumentSyncProposal
from app.domains.documents.models import Document, DocumentStatus, DocumentType
from app.domains.knowledge.models import KnowledgeEntry
from app.domains.projects.models import SourceFile
from app.domains.projects.service import ProjectService
from app.models.identity import Tenant, User
from app.models.projects import Project, ProjectMember


@pytest.fixture
async def db_session():
    """Create an isolated async SQLite database for delivery workbench tests."""
    deduplicate_indexes()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()


def _document(*, tenant_id, project_id, user_id, doc_type, title, status, version=1):
    return Document(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        doc_type=doc_type,
        title=title,
        content=f"# {title}\n\nDelivery workbench fixture.",
        status=status,
        version=version,
        created_by=user_id,
        metadata_json={},
    )


@pytest.mark.asyncio
async def test_delivery_workbench_summarizes_project_readiness_and_risks(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()

    tenant = Tenant(id=tenant_id, name="Workbench Tenant", slug="workbench-tenant")
    user = User(
        id=user_id,
        tenant_id=tenant_id,
        email="owner@example.com",
        hashed_password="test",
        full_name="Project Owner",
    )
    project = Project(
        id=project_id,
        tenant_id=tenant_id,
        owner_id=user_id,
        name="Project Delivery Workbench",
        slug="project-delivery-workbench",
    )
    membership = ProjectMember(project_id=project_id, user_id=user_id)

    urs = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.URS.value,
        title="URS Account Controls",
        status=DocumentStatus.PUBLISHED.value,
        version=2,
    )
    brd = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.BRD.value,
        title="BRD Account Controls",
        status=DocumentStatus.REVIEW.value,
    )
    prd = _document(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        doc_type=DocumentType.PRD.value,
        title="PRD Account Controls",
        status=DocumentStatus.DRAFT.value,
    )

    ready_file = SourceFile(
        tenant_id=tenant_id,
        project_id=project_id,
        filename="source-ready.pdf",
        original_filename="source-ready.pdf",
        content_type="application/pdf",
        size="1024",
        hash="a" * 64,
        storage_path="tenant/project/source-ready.pdf",
        status="ready",
        metadata_json={},
    )
    failed_file = SourceFile(
        tenant_id=tenant_id,
        project_id=project_id,
        filename="source-failed.pdf",
        original_filename="source-failed.pdf",
        content_type="application/pdf",
        size="2048",
        hash="b" * 64,
        storage_path="tenant/project/source-failed.pdf",
        status="failed",
        metadata_json={},
    )

    knowledge_entries = [
        KnowledgeEntry(
            tenant_id=tenant_id,
            project_id=project_id,
            source_file_id=ready_file.id,
            entry_type="text",
            content=f"Knowledge entry {index}",
            content_hash=str(index) * 64,
            metadata_json={"title": f"Entry {index}"},
            created_by_id=user_id,
        )
        for index in (1, 2)
    ]

    change_request = ChangeRequest(
        tenant_id=tenant_id,
        project_id=project_id,
        source_document_id=urs.id,
        source_document_version=urs.version,
        target_document_id=brd.id,
        target_document_version=brd.version,
        change_type="enhancement",
        priority="high",
        status="open",
        description="Account control requirement changed.",
        requested_by=user_id,
    )
    reference = DocumentReference(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        source_document_id=urs.id,
        source_document_version=urs.version,
        target_document_id=brd.id,
        target_document_version=brd.version,
        reference_type="derives_from",
        status="active",
        created_by=user_id,
        metadata_json={},
    )
    impact_analysis = DocumentImpactAnalysis(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        trigger_document_id=urs.id,
        trigger_document_version=urs.version,
        trigger_type="content_changed",
        impact_level="high",
        status="open",
        summary="URS changed and downstream BRD needs sync.",
        analysis_json={"impacted_reference_count": 1},
        created_by=user_id,
    )
    sync_proposal = DocumentSyncProposal(
        tenant_id=tenant_id,
        impact_analysis_id=impact_analysis.id,
        project_id=project_id,
        reference_id=reference.id,
        source_document_id=urs.id,
        target_document_id=brd.id,
        target_document_version=brd.version,
        target_section="2. Controls",
        impact_level="high",
        reason="BRD should confirm account-control updates.",
        suggested_action="review_and_sync",
        status="pending",
        metadata_json={},
    )

    db_session.add_all([
        tenant,
        user,
        project,
        membership,
        urs,
        brd,
        prd,
        ready_file,
        failed_file,
        *knowledge_entries,
        change_request,
        reference,
        impact_analysis,
        sync_proposal,
    ])
    await db_session.flush()

    workbench = await ProjectService(db_session).get_delivery_workbench(
        project_id=project_id,
        tenant_id=tenant_id,
    )

    assert workbench["totals"]["documents"] == 3
    assert workbench["totals"]["source_files"] == 2
    assert workbench["totals"]["knowledge_entries"] == 2
    assert workbench["totals"]["members"] == 1
    assert workbench["document_status_counts"] == {"draft": 1, "published": 1, "review": 1}
    assert workbench["source_file_status_counts"] == {"failed": 1, "ready": 1}
    assert workbench["change_status_counts"] == {"open": 1}
    assert workbench["traceability"]["active_references"] == 1
    assert workbench["traceability"]["open_impact_analyses"] == 1
    assert workbench["traceability"]["pending_sync_proposals"] == 1

    chain_by_type = {item["doc_type"]: item for item in workbench["delivery_chain"]}
    assert chain_by_type["urs"]["status"] == "published"
    assert chain_by_type["brd"]["status"] == "review"
    assert chain_by_type["prd"]["status"] == "draft"
    assert chain_by_type["test_case"]["missing"] is True

    assert [item["id"] for item in workbench["review_queue"]] == [str(brd.id)]
    assert any(risk["code"] == "pending_sync_proposals" for risk in workbench["risks"])
    assert any(risk["code"] == "failed_source_files" for risk in workbench["risks"])
    assert {action["code"] for action in workbench["next_actions"]} >= {
        "review_documents",
        "review_traceability_sync",
        "resolve_source_file_failures",
    }
