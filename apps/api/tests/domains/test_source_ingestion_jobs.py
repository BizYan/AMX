"""Persistent source-ingestion job lifecycle and knowledge governance tests."""

import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-source-ingestion-jobs-secret"

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401
import app.domains.identity.models  # noqa: F401
import app.domains.knowledge.models  # noqa: F401
import app.domains.projects.models  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.knowledge.models import KnowledgeEntry, KnowledgeLink
from app.domains.projects.ingestion_service import SourceIngestionError, SourceIngestionService
from app.domains.projects.models import SourceFile, SourceIngestionJob
from app.models.identity import Tenant, User
from app.models.projects import Project, ProjectMember
from app.services.storage import StorageHandle, StorageProvider


class MemoryStorage(StorageProvider):
    def __init__(self, files: dict[str, bytes] | None = None):
        self.files = files or {}

    async def upload(self, tenant_id: str, project_id: str, filename: str, content: bytes, content_type: str):
        path = f"{tenant_id}/{project_id}/{filename}"
        self.files[path] = content
        return StorageHandle(path=path, filename=filename, content_type=content_type, size=len(content), hash="a" * 64, storage_backend="memory")

    async def download(self, handle: StorageHandle) -> bytes:
        if handle.path not in self.files:
            raise FileNotFoundError(handle.path)
        return self.files[handle.path]

    async def delete(self, handle: StorageHandle) -> None:
        self.files.pop(handle.path, None)

    async def get_url(self, handle: StorageHandle, expires_in: int = 3600) -> str:
        return f"memory://{handle.path}"


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
    tenant = Tenant(id=uuid4(), name="Ingestion Tenant", slug=f"ingestion-{uuid4().hex[:8]}")
    owner = User(id=uuid4(), tenant_id=tenant.id, email="owner@example.com", full_name="Owner", hashed_password="hashed")
    project = Project(id=uuid4(), tenant_id=tenant.id, owner_id=owner.id, name="Ingestion Project", slug=f"ingestion-{uuid4().hex[:8]}")
    source = SourceFile(
        id=uuid4(),
        tenant_id=tenant.id,
        project_id=project.id,
        filename="source.txt",
        original_filename="source.txt",
        content_type="text/plain",
        size="64",
        hash="a" * 64,
        storage_path=f"{tenant.id}/{project.id}/source.txt",
        status="pending",
        metadata_json={},
    )
    db_session.add_all([tenant, owner, project, ProjectMember(project_id=project.id, user_id=owner.id), source])
    await db_session.flush()
    return tenant, owner, project, source


@pytest.mark.asyncio
async def test_enqueue_deduplicates_active_job_and_records_requester(db_session):
    tenant, owner, project, source = await _seed(db_session)
    service = SourceIngestionService(db_session)

    first = await service.enqueue(source, owner.id)
    second = await service.enqueue(source, owner.id)

    assert first.id == second.id
    assert first.status == "pending"
    assert first.stage == "queued"
    assert first.requested_by_id == owner.id
    assert first.project_id == project.id
    assert first.tenant_id == tenant.id
    assert len(list((await db_session.scalars(select(SourceIngestionJob))).all())) == 1


@pytest.mark.asyncio
async def test_execute_job_completes_and_records_knowledge_result(db_session):
    _, owner, _, source = await _seed(db_session)
    storage = MemoryStorage({source.storage_path: b"URS-001: Users can upload governed source evidence."})
    service = SourceIngestionService(db_session)
    job = await service.enqueue(source, owner.id)

    completed = await service.execute(job.id, storage=storage)

    assert completed.status == "completed"
    assert completed.stage == "knowledge_ready"
    assert completed.attempt_count == 1
    assert completed.completed_at is not None
    assert completed.result_json["knowledge_entry_count"] == 1
    assert source.status == "ready"


@pytest.mark.asyncio
async def test_failed_job_can_be_retried_without_creating_duplicate_active_job(db_session):
    _, owner, _, source = await _seed(db_session)
    service = SourceIngestionService(db_session)
    job = await service.enqueue(source, owner.id)

    failed = await service.execute(job.id, storage=MemoryStorage())
    retried = await service.retry(failed.id, owner.id)
    duplicate = await service.enqueue(source, owner.id)

    assert failed.status == "pending"
    assert retried.id == failed.id
    assert retried.stage == "queued_for_retry"
    assert retried.error_message is None
    assert duplicate.id == retried.id


@pytest.mark.asyncio
async def test_retry_rejects_running_or_completed_job(db_session):
    _, owner, _, source = await _seed(db_session)
    service = SourceIngestionService(db_session)
    job = await service.enqueue(source, owner.id)
    job.status = "running"
    await db_session.flush()

    with pytest.raises(SourceIngestionError, match="cannot be retried"):
        await service.retry(job.id, owner.id)


@pytest.mark.asyncio
async def test_reingest_retires_old_source_knowledge_and_enqueues_new_job(db_session):
    tenant, owner, project, source = await _seed(db_session)
    old_one = KnowledgeEntry(id=uuid4(), tenant_id=tenant.id, project_id=project.id, source_file_id=source.id, entry_type="text", content="old one", content_hash="1" * 64)
    old_two = KnowledgeEntry(id=uuid4(), tenant_id=tenant.id, project_id=project.id, source_file_id=source.id, entry_type="text", content="old two", content_hash="2" * 64)
    link = KnowledgeLink(id=uuid4(), tenant_id=tenant.id, source_entry_id=old_one.id, target_entry_id=old_two.id, link_type="cites")
    db_session.add_all([old_one, old_two, link])
    source.status = "ready"
    await db_session.flush()

    job = await SourceIngestionService(db_session).reingest(source.id, tenant.id, project.id, owner.id)

    assert job.status == "pending"
    assert source.status == "pending"
    assert source.metadata_json["extractedKnowledgeCount"] == 0
    assert old_one.deleted_at is not None
    assert old_two.deleted_at is not None
    assert link.deleted_at is not None


@pytest.mark.asyncio
async def test_source_deletion_retires_derived_knowledge(db_session):
    tenant, owner, project, source = await _seed(db_session)
    entry = KnowledgeEntry(id=uuid4(), tenant_id=tenant.id, project_id=project.id, source_file_id=source.id, entry_type="text", content="derived", content_hash="3" * 64)
    db_session.add(entry)
    await db_session.flush()
    job = await SourceIngestionService(db_session).enqueue(source, owner.id)

    retired = await SourceIngestionService(db_session).retire_source_knowledge(source.id, tenant.id)

    assert retired == 1
    assert entry.deleted_at is not None
    assert job.status == "cancelled"
    assert job.stage == "source_retired"
