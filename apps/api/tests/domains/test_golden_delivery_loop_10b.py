"""Golden Delivery Loop 10B Knowledge -> AI document -> approval -> export tests."""

import os
from types import SimpleNamespace
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-golden-delivery-loop-10b-secret"

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

import app.db.init_schema  # noqa: F401
import app.domains.collaboration.models  # noqa: F401
import app.domains.documents.models  # noqa: F401
import app.domains.identity.models  # noqa: F401
import app.domains.knowledge.models  # noqa: F401
import app.domains.projects.models  # noqa: F401
import app.domains.providers.models  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.collaboration.models import DocumentComment
from app.domains.documents.models import Document, DocumentStatus, DocumentType, DocumentVersion, QualityResult, QualityType
from app.domains.documents.schemas import DocumentStatusUpdate
from app.domains.documents.service import DocumentGenerationService, DocumentService
from app.domains.export.models import ExportStatus
from app.domains.export.service import ExportService
from app.domains.knowledge.models import KnowledgeEntry, ProvenanceRecord
from app.domains.providers.contracts import LLMResponse, ProviderError
from app.domains.providers.models import CapabilityType, Provider, ProviderRun, ProviderStatus, ProviderType, RunStatus
from app.domains.projects.models import SourceFile, SourceFileStatus
from app.models.identity import Tenant, User
from app.models.projects import Project, ProjectMember
from app.services.storage import StorageHandle


MARKER_PHRASE = "AMX-GOLDEN-10B-SOURCE-BACKED-MARKER"


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


class CapturingStorage:
    def __init__(self):
        self.uploads = []

    async def upload(self, tenant_id, project_id, filename, content, content_type):
        self.uploads.append(
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "filename": filename,
                "content": content,
                "content_type": content_type,
            }
        )
        return StorageHandle(
            path=f"{tenant_id}/{project_id}/{filename}",
            filename=filename,
            content_type=content_type,
            size=len(content),
            hash="c" * 64,
            storage_backend="test",
        )


class GroundedProvider:
    providers = [SimpleNamespace(name="candidate-real-llm", model="amx-candidate-model", is_primary=True)]

    async def generate(self, prompt, params):
        assert MARKER_PHRASE in prompt
        return LLMResponse(
            text=(
                "# 10B Delivery Evidence Document\n\n"
                f"Generated from source-backed knowledge marker: {MARKER_PHRASE}.\n\n"
                "## Review Evidence\nReady for approval, baseline, and package export."
            ),
            model="amx-candidate-model",
            usage={"prompt_tokens": 120, "completion_tokens": 48, "total_tokens": 168},
            finish_reason="stop",
            raw_response={"id": "synthetic-provider-run-10b"},
        )


class UnavailableProvider:
    providers = [SimpleNamespace(name="candidate-real-llm", model="amx-candidate-model", is_primary=True)]

    async def generate(self, prompt, params):
        raise ProviderError("provider unavailable", provider="candidate-real-llm")


async def _seed_project_with_source_knowledge(db_session):
    tenant = Tenant(id=uuid4(), name="Golden 10B Tenant", slug=f"golden-10b-{uuid4().hex[:8]}")
    owner = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email="golden-10b-owner@example.test",
        full_name="Golden 10B Owner",
        hashed_password="hashed",
    )
    project = Project(
        id=uuid4(),
        tenant_id=tenant.id,
        owner_id=owner.id,
        name="Golden Delivery Loop 10B",
        slug=f"golden-delivery-loop-10b-{uuid4().hex[:8]}",
        status="active",
    )
    source_file = SourceFile(
        id=uuid4(),
        tenant_id=tenant.id,
        project_id=project.id,
        filename="golden-10b-source.md",
        original_filename="golden-10b-source.md",
        content_type="text/markdown",
        size="128",
        hash="a" * 64,
        storage_path=f"{tenant.id}/{project.id}/golden-10b-source.md",
        status=SourceFileStatus.READY.value,
        metadata_json={"extractedKnowledgeCount": 1},
    )
    knowledge = KnowledgeEntry(
        id=uuid4(),
        tenant_id=tenant.id,
        project_id=project.id,
        source_file_id=source_file.id,
        entry_type="requirement",
        content=f"REQ-10B-001: {MARKER_PHRASE} must appear in generated delivery evidence.",
        content_hash="b" * 64,
        metadata_json={
            "title": "10B source-backed delivery marker",
            "ingestion": {"source_file_id": str(source_file.id), "source_file_status": "ready"},
        },
    )
    provider = Provider(
        id=uuid4(),
        tenant_id=tenant.id,
        name="candidate-only real LLM",
        provider_type=ProviderType.LLM.value,
        status=ProviderStatus.ACTIVE.value,
        config_json={
            "credential_ref": "env:AMX_CANDIDATE_LLM_API_KEY",
            "candidate_spend_cap": {"amount_usd": 5, "max_calls": 50},
        },
        capabilities_json=[CapabilityType.TEXT_GENERATION.value],
    )
    db_session.add_all([
        tenant,
        owner,
        project,
        ProjectMember(project_id=project.id, user_id=owner.id),
        source_file,
        knowledge,
        provider,
    ])
    await db_session.flush()
    provenance = ProvenanceRecord(
        tenant_id=tenant.id,
        project_id=project.id,
        entry_id=knowledge.id,
        provider_id="source_file_ingest",
        provider_version_id=None,
        raw_artifact_id=str(source_file.id),
        confidence=1.0,
        normalization_notes=f"marker={MARKER_PHRASE}",
    )
    db_session.add(provenance)
    await db_session.flush()
    return SimpleNamespace(
        tenant=tenant,
        owner=owner,
        project=project,
        source_file=source_file,
        knowledge=knowledge,
        provider=provider,
    )


@pytest.mark.asyncio
async def test_knowledge_to_generated_review_approval_export_evidence_loop(db_session, monkeypatch):
    fixture = await _seed_project_with_source_knowledge(db_session)
    storage = CapturingStorage()
    monkeypatch.setattr("app.domains.export.service.get_storage_provider", lambda: storage)

    generation = DocumentGenerationService(db_session, llm_gateway=GroundedProvider())
    document = await generation.generate_document(
        doc_type=DocumentType.BRD.value,
        project_id=fixture.project.id,
        tenant_id=fixture.tenant.id,
        created_by=fixture.owner.id,
        context={
            "title": "10B Source Grounded BRD",
            "project_name": fixture.project.name,
            "additional_context": fixture.knowledge.content,
            "source_grounding": [
                {
                    "knowledge_entry_id": str(fixture.knowledge.id),
                    "source_file_id": str(fixture.source_file.id),
                    "marker": MARKER_PHRASE,
                }
            ],
            "provider_id": str(fixture.provider.id),
        },
    )

    evidence = document.metadata_json["generation_evidence"]
    assert document.metadata_json["generation_status"] == "generated"
    assert evidence["provider"] == "candidate-real-llm"
    assert evidence["model"] == "amx-candidate-model"
    assert evidence["usage"]["total_tokens"] == 168
    assert evidence["provider_run_id"]
    assert evidence["raw_artifact_ref"] == "synthetic-provider-run-10b"
    serialized_evidence = str(document.metadata_json)
    assert "api_key" not in serialized_evidence.lower()
    assert "secret" not in serialized_evidence.lower()
    assert "password" not in serialized_evidence.lower()
    assert document.metadata_json["source_grounding"]["knowledge_entry_ids"] == [str(fixture.knowledge.id)]
    assert document.metadata_json["source_grounding"]["source_file_ids"] == [str(fixture.source_file.id)]
    assert MARKER_PHRASE in document.content
    assert "placeholder" not in document.content.lower()
    assert "generation failed" not in document.content.lower()

    provider_run = await db_session.scalar(
        select(ProviderRun).where(
            ProviderRun.provider_id == fixture.provider.id,
            ProviderRun.capability_type == CapabilityType.TEXT_GENERATION.value,
        )
    )
    assert provider_run is not None
    assert provider_run.status == RunStatus.SUCCESS.value
    assert provider_run.input_tokens == 120
    assert provider_run.output_tokens == 48
    assert "api_key" not in str(provider_run.error_message).lower()

    reviewed = await DocumentService(db_session).transition_status(
        document_id=document.id,
        tenant_id=fixture.tenant.id,
        status_update=DocumentStatusUpdate(status=DocumentStatus.REVIEW.value, reason="Ready for review"),
        changed_by=fixture.owner.id,
    )
    approved = await DocumentService(db_session).transition_status(
        document_id=document.id,
        tenant_id=fixture.tenant.id,
        status_update=DocumentStatusUpdate(status=DocumentStatus.APPROVED.value, reason="Ready for approval check"),
        changed_by=fixture.owner.id,
    )
    assert reviewed.status == DocumentStatus.APPROVED.value
    assert approved.status == DocumentStatus.APPROVED.value

    comment = DocumentComment(
        tenant_id=fixture.tenant.id,
        document_id=document.id,
        user_id=fixture.owner.id,
        content="Confirm source grounding before approval.",
        anchor="generation.source_grounding",
    )
    db_session.add(comment)
    await db_session.flush()
    unresolved = await DocumentService(db_session).count_unresolved_comments(document.id, fixture.tenant.id)
    assert unresolved == 1

    with pytest.raises(ValueError, match="unresolved comments"):
        await DocumentService(db_session).transition_status(
            document_id=document.id,
            tenant_id=fixture.tenant.id,
            status_update=DocumentStatusUpdate(status=DocumentStatus.PUBLISHED.value, reason="Attempt with open review"),
            changed_by=fixture.owner.id,
        )

    comment.resolved = True
    await db_session.flush()
    assert comment.resolved is True

    version = await DocumentService(db_session).create_version(
        document_id=document.id,
        tenant_id=fixture.tenant.id,
        content=document.content + "\n\nBaseline-ready source grounding confirmed.",
        changes_summary="Resolve review and preserve 10B source grounding",
        created_by=fixture.owner.id,
    )
    baseline = await DocumentService(db_session).create_baseline(
        document_id=document.id,
        version_id=version.id,
        tenant_id=fixture.tenant.id,
        baseline_name="10B approved baseline",
        reason="Generated from source-backed knowledge and reviewed",
        approved_by=fixture.owner.id,
    )
    assert isinstance(version, DocumentVersion)
    assert baseline.approved_by == fixture.owner.id

    published = await DocumentService(db_session).transition_status(
        document_id=document.id,
        tenant_id=fixture.tenant.id,
        status_update=DocumentStatusUpdate(status=DocumentStatus.PUBLISHED.value, reason="Package export approved"),
        changed_by=fixture.owner.id,
    )
    assert published.status == DocumentStatus.PUBLISHED.value

    readiness = await ExportService(db_session).get_project_export_readiness(fixture.project.id, fixture.tenant.id)
    assert readiness.exportable_documents == 1

    job = await ExportService(db_session).export_project_package(
        project_id=fixture.project.id,
        tenant_id=fixture.tenant.id,
        document_ids=[document.id],
        title="10B Evidence Package",
        formats=["markdown"],
        include_audit=True,
        created_by=fixture.owner.id,
    )

    assert job.status == ExportStatus.COMPLETED.value
    exported_markdown = storage.uploads[0]["content"].decode("utf-8")
    assert MARKER_PHRASE in exported_markdown
    assert "10B Delivery Evidence Document" in exported_markdown
    assert document.content in exported_markdown
    assert "fixture" not in exported_markdown.lower()
    assert "placeholder" not in document.content.lower()


@pytest.mark.asyncio
async def test_10b_export_readiness_blocks_open_comments_and_failed_quality_checks(db_session):
    fixture = await _seed_project_with_source_knowledge(db_session)
    document = Document(
        tenant_id=fixture.tenant.id,
        project_id=fixture.project.id,
        title="10B Quality Gate BRD",
        doc_type=DocumentType.BRD.value,
        content=f"# Quality Gate\n\n{MARKER_PHRASE} generated package content.",
        status=DocumentStatus.PUBLISHED.value,
        created_by=fixture.owner.id,
        metadata_json={"generation_status": "generated"},
    )
    db_session.add(document)
    await db_session.flush()

    comment = DocumentComment(
        tenant_id=fixture.tenant.id,
        document_id=document.id,
        user_id=fixture.owner.id,
        content="Resolve this before delivery.",
    )
    failed_quality = QualityResult(
        tenant_id=fixture.tenant.id,
        document_id=document.id,
        quality_type=QualityType.COMPLETENESS.value,
        score=45,
        issues_json={"status": "failed", "blockers": ["source citation missing"]},
    )
    db_session.add_all([comment, failed_quality])
    await db_session.flush()

    readiness = await ExportService(db_session).get_project_export_readiness(fixture.project.id, fixture.tenant.id)
    reasons = [item.reason for item in readiness.blockers]
    assert any("unresolved comments" in reason for reason in reasons)
    assert any("quality check failed" in reason for reason in reasons)
    assert readiness.exportable_documents == 0

    with pytest.raises(ValueError, match="unresolved comments"):
        await ExportService(db_session).export_project_package(
            project_id=fixture.project.id,
            tenant_id=fixture.tenant.id,
            document_ids=[document.id],
            created_by=fixture.owner.id,
        )

    comment.resolved = True
    await db_session.flush()
    with pytest.raises(ValueError, match="quality checks"):
        await ExportService(db_session).export_project_package(
            project_id=fixture.project.id,
            tenant_id=fixture.tenant.id,
            document_ids=[document.id],
            created_by=fixture.owner.id,
        )


@pytest.mark.asyncio
async def test_10b_blocks_unavailable_or_non_generated_documents_from_delivery(db_session, monkeypatch):
    fixture = await _seed_project_with_source_knowledge(db_session)
    storage = CapturingStorage()
    monkeypatch.setattr("app.domains.export.service.get_storage_provider", lambda: storage)

    failed_document = await DocumentGenerationService(db_session, llm_gateway=UnavailableProvider()).generate_document(
        doc_type=DocumentType.BRD.value,
        project_id=fixture.project.id,
        tenant_id=fixture.tenant.id,
        created_by=fixture.owner.id,
        context={
            "title": "Unavailable Provider BRD",
            "project_name": fixture.project.name,
            "additional_context": fixture.knowledge.content,
            "provider_id": str(fixture.provider.id),
        },
    )
    assert failed_document.metadata_json["generation_status"] == "failed"

    with pytest.raises(ValueError, match="Cannot transition failed document"):
        await DocumentService(db_session).transition_status(
            document_id=failed_document.id,
            tenant_id=fixture.tenant.id,
            status_update=DocumentStatusUpdate(status=DocumentStatus.REVIEW.value, reason="Should be blocked"),
            changed_by=fixture.owner.id,
        )

    failed_document.status = DocumentStatus.PUBLISHED.value
    await db_session.flush()
    with pytest.raises(ValueError, match="non-generated AI documents"):
        await ExportService(db_session).export_project_package(
            project_id=fixture.project.id,
            tenant_id=fixture.tenant.id,
            document_ids=[failed_document.id],
            created_by=fixture.owner.id,
        )
    assert storage.uploads == []

    failed_document.metadata_json = {
        "generation_status": "generated",
        "delivery": {
            "delivery_readiness": {
                "ready": False,
                "blockers": ["source grounding below threshold"],
            }
        },
    }
    failed_document.status = DocumentStatus.PUBLISHED.value
    await db_session.flush()
    with pytest.raises(ValueError, match="export readiness"):
        await ExportService(db_session).export_project_package(
            project_id=fixture.project.id,
            tenant_id=fixture.tenant.id,
            document_ids=[failed_document.id],
            created_by=fixture.owner.id,
        )
