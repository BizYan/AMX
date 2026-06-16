import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-secret"

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401 - registers sqlite compilers for UUID/JSONB
import app.models.identity  # noqa: F401 - registers tenant/user tables for FK targets
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.knowledge.models import KnowledgeEntry, KnowledgeLink, ProvenanceRecord
from app.domains.projects.models import SourceFile, SourceFileStatus
from app.domains.projects.schemas import SourceFileCreate
from app.domains.projects.service import SourceFileService
from app.models.identity import Tenant, User
from app.models.projects import Project, ProjectMember
from app.services.storage import StorageHandle, StorageProvider


class MemoryStorage(StorageProvider):
    def __init__(self):
        self.files: dict[str, bytes] = {}

    async def upload(self, tenant_id: str, project_id: str, filename: str, content: bytes, content_type: str):
        path = f"{tenant_id}/{project_id}/{filename}"
        self.files[path] = content
        return StorageHandle(
            path=path,
            filename=filename,
            content_type=content_type,
            size=len(content),
            hash="a" * 64,
            storage_backend="memory",
        )

    async def download(self, handle: StorageHandle) -> bytes:
        try:
            return self.files[handle.path]
        except KeyError:
            raise FileNotFoundError(handle.path)

    async def delete(self, handle: StorageHandle) -> None:
        self.files.pop(handle.path, None)

    async def get_url(self, handle: StorageHandle, expires_in: int = 3600) -> str:
        return f"memory://{handle.path}"


def minimal_text_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    chunks = [b"%PDF-1.4\n"]
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{index} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref_offset = sum(len(chunk) for chunk in chunks)
    chunks.append(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        chunks.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    chunks.append(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return b"".join(chunks)


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


@pytest.fixture
async def project_context(db_session):
    tenant_id = uuid4()
    db_session.add(Tenant(id=tenant_id, name="Test tenant", slug=f"tenant-{tenant_id.hex[:8]}"))
    user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email="owner@example.com",
        full_name="Owner",
        hashed_password="hashed",
    )
    project = Project(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_id=user.id,
        name="Core project",
        slug="core-project",
        description="Core flow",
    )
    db_session.add(user)
    db_session.add(project)
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id))
    await db_session.flush()
    return tenant_id, user, project


@pytest.mark.asyncio
async def test_direct_source_upload_ingests_text_into_knowledge_and_updates_summary(db_session, project_context):
    tenant_id, _, project = project_context
    storage = MemoryStorage()
    content = (
        "URS-001: 系统必须支持顾问上传客户访谈纪要并生成需求文档。\n\n"
        "BRD-002: 资料摄取完成后应形成可追溯知识条目。"
    ).encode("utf-8")
    handle = await storage.upload(
        tenant_id=str(tenant_id),
        project_id=str(project.id),
        filename="访谈纪要.txt",
        content=content,
        content_type="text/plain",
    )

    source_service = SourceFileService(db_session)
    source_file = await source_service.create_source_file(
        project_id=project.id,
        tenant_id=tenant_id,
        data=SourceFileCreate(
            filename=handle.filename,
            original_filename="访谈纪要.txt",
            content_type="text/plain",
            size=handle.size,
            hash=handle.hash,
            storage_path=handle.path,
            metadata={},
        ),
    )

    entries = await source_service.ingest_source_file(
        source_file_id=source_file.id,
        tenant_id=tenant_id,
        project_id=project.id,
        storage=storage,
    )

    assert len(entries) == 2
    refreshed = await source_service.get_source_file(source_file.id, tenant_id)
    assert refreshed.status == SourceFileStatus.READY.value
    assert refreshed.metadata_json["ingestionStage"] == "已完成解析和知识抽取"
    assert refreshed.metadata_json["extractedKnowledgeCount"] == 2
    assert refreshed.metadata_json["knowledgeLinkCount"] == 1
    assert "访谈纪要.txt" in refreshed.metadata_json["ingestionSummary"]

    stored_entries = list(
        (await db_session.execute(select(KnowledgeEntry).where(KnowledgeEntry.source_file_id == source_file.id))).scalars()
    )
    assert len(stored_entries) == 2
    assert {entry.metadata_json["ingestion"]["identifier"] for entry in stored_entries} == {"URS-001", "BRD-002"}
    assert all(entry.metadata_json["ingestion"]["source_file_status"] == "ready" for entry in stored_entries)

    provenance = list(
        (
            await db_session.execute(
                select(ProvenanceRecord).where(ProvenanceRecord.entry_id.in_([entry.id for entry in stored_entries]))
            )
        ).scalars()
    )
    assert len(provenance) == 2

    links = list(
        (
            await db_session.execute(
                select(KnowledgeLink).where(
                    KnowledgeLink.source_entry_id.in_([entry.id for entry in stored_entries]),
                    KnowledgeLink.target_entry_id.in_([entry.id for entry in stored_entries]),
                )
            )
        ).scalars()
    )
    assert len(links) == 1
    assert links[0].link_type == "depends_on"
    assert links[0].metadata_json["ingestion"]["source_file_id"] == str(source_file.id)


@pytest.mark.asyncio
async def test_source_ingestion_marks_failed_when_storage_content_is_missing(db_session, project_context):
    tenant_id, _, project = project_context
    source_service = SourceFileService(db_session)
    source_file = await source_service.create_source_file(
        project_id=project.id,
        tenant_id=tenant_id,
        data=SourceFileCreate(
            filename="missing.txt",
            original_filename="missing.txt",
            content_type="text/plain",
            size=12,
            hash="b" * 64,
            storage_path="missing/path.txt",
            metadata={},
        ),
    )

    entries = await source_service.ingest_source_file(
        source_file_id=source_file.id,
        tenant_id=tenant_id,
        project_id=project.id,
        storage=MemoryStorage(),
    )

    assert entries == []
    refreshed = await source_service.get_source_file(source_file.id, tenant_id)
    assert refreshed.status == SourceFileStatus.FAILED.value
    assert refreshed.metadata_json["requiredAction"] == "重新上传资料或确认存储文件可访问"
    assert "missing.txt" in refreshed.metadata_json["errorMessage"]

@pytest.mark.asyncio
async def test_source_ingestion_marks_failed_for_unparseable_docx_without_placeholder_entries(
    db_session,
    project_context,
):
    tenant_id, _, project = project_context
    storage = MemoryStorage()
    handle = await storage.upload(
        tenant_id=str(tenant_id),
        project_id=str(project.id),
        filename="broken.docx",
        content=b"not a valid office archive",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    source_service = SourceFileService(db_session)
    source_file = await source_service.create_source_file(
        project_id=project.id,
        tenant_id=tenant_id,
        data=SourceFileCreate(
            filename=handle.filename,
            original_filename="broken.docx",
            content_type=handle.content_type,
            size=handle.size,
            hash=handle.hash,
            storage_path=handle.path,
            metadata={},
        ),
    )

    entries = await source_service.ingest_source_file(
        source_file_id=source_file.id,
        tenant_id=tenant_id,
        project_id=project.id,
        storage=storage,
    )

    assert entries == []
    refreshed = await source_service.get_source_file(source_file.id, tenant_id)
    assert refreshed.status == SourceFileStatus.FAILED.value
    assert refreshed.metadata_json["extractedKnowledgeCount"] == 0
    assert "broken.docx" in refreshed.metadata_json["errorMessage"]

    stored_entries = list(
        (await db_session.execute(select(KnowledgeEntry).where(KnowledgeEntry.source_file_id == source_file.id))).scalars()
    )
    assert stored_entries == []


@pytest.mark.asyncio
async def test_source_ingestion_extracts_pdf_text_into_knowledge(db_session, project_context):
    tenant_id, _, project = project_context
    storage = MemoryStorage()
    handle = await storage.upload(
        tenant_id=str(tenant_id),
        project_id=str(project.id),
        filename="source.pdf",
        content=minimal_text_pdf("URS-101: PDF source material supports knowledge ingestion."),
        content_type="application/pdf",
    )

    source_service = SourceFileService(db_session)
    source_file = await source_service.create_source_file(
        project_id=project.id,
        tenant_id=tenant_id,
        data=SourceFileCreate(
            filename=handle.filename,
            original_filename="source.pdf",
            content_type=handle.content_type,
            size=handle.size,
            hash=handle.hash,
            storage_path=handle.path,
            metadata={},
        ),
    )

    entries = await source_service.ingest_source_file(
        source_file_id=source_file.id,
        tenant_id=tenant_id,
        project_id=project.id,
        storage=storage,
    )

    assert len(entries) == 1
    assert "PDF source material supports knowledge ingestion" in entries[0].content
    refreshed = await source_service.get_source_file(source_file.id, tenant_id)
    assert refreshed.status == SourceFileStatus.READY.value
