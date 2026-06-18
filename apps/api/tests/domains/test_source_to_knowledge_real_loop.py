"""Real source-to-knowledge evidence loop integration tests."""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-source-to-knowledge-secret"

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]
settings.STORAGE_BACKEND = "local"

import app.db.init_schema  # noqa: F401
import app.domains.identity.models  # noqa: F401
import app.domains.knowledge.models  # noqa: F401
import app.domains.projects.models  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.knowledge import router as knowledge_router
from app.domains.knowledge.models import KnowledgeEntry, ProvenanceRecord
from app.domains.projects import router as projects_router
from app.domains.projects.models import SourceFile, SourceIngestionJob
from app.models.identity import Tenant, User
from app.models.projects import Project, ProjectMember
from app.services.storage import LocalStorageProvider


MARKER_PHRASE = "AMX-GOLDEN-SOURCE-KNOWLEDGE-10A distinctive retrieval marker"


@pytest.fixture
async def db_session():
    """Create a disposable async database for the real source loop."""
    deduplicate_indexes()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def api_client(db_session, tmp_path):
    tenant = Tenant(id=uuid4(), name="Golden Loop Tenant", slug=f"golden-{uuid4().hex[:8]}")
    owner = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email="golden-owner@example.com",
        full_name="Golden Owner",
        hashed_password="hashed",
    )
    outsider = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email="golden-outsider@example.com",
        full_name="Golden Outsider",
        hashed_password="hashed",
    )
    project = Project(
        id=uuid4(),
        tenant_id=tenant.id,
        owner_id=owner.id,
        name="Golden Delivery Loop 10A",
        slug=f"golden-loop-{uuid4().hex[:8]}",
        status="active",
    )
    db_session.add_all([tenant, owner, outsider, project, ProjectMember(project_id=project.id, user_id=owner.id)])
    await db_session.flush()

    storage = LocalStorageProvider(base_path=str(tmp_path / "source-storage"))
    current_user = {"value": owner}

    async def override_db():
        yield db_session

    async def override_project_user():
        return current_user["value"]

    async def override_knowledge_user():
        return current_user["value"]

    app = FastAPI()
    app.include_router(projects_router.router, prefix="/api/v1/projects")
    app.include_router(knowledge_router.router, prefix="/api/v1/knowledge")
    app.dependency_overrides[projects_router.get_db] = override_db
    app.dependency_overrides[knowledge_router.get_db] = override_db
    app.dependency_overrides[projects_router.get_current_user] = override_project_user
    app.dependency_overrides[knowledge_router.get_current_user] = override_knowledge_user
    app.dependency_overrides[projects_router.get_storage] = lambda: storage

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield SimpleNamespace(
            client=client,
            db=db_session,
            tenant=tenant,
            owner=owner,
            outsider=outsider,
            project=project,
            storage=storage,
            storage_root=Path(storage.base_path),
            current_user=current_user,
        )


@pytest.mark.asyncio
async def test_real_markdown_upload_ingests_searches_and_returns_provenance(api_client):
    markdown_bytes = (
        "# Golden Delivery Evidence\n\n"
        f"REQ-10A-001: {MARKER_PHRASE} must be searchable after ingestion.\n\n"
        "REQ-10A-002: Source lineage must point back to the uploaded markdown file.\n"
    ).encode("utf-8")

    upload_response = await api_client.client.post(
        f"/api/v1/projects/{api_client.project.id}/files",
        files={"file": ("golden-source-10a.md", markdown_bytes, "text/markdown")},
    )

    assert upload_response.status_code == 201
    source_file_id = UUID(upload_response.json()["id"])
    source_file = await api_client.db.get(SourceFile, source_file_id)
    assert source_file is not None
    assert source_file.original_filename == "golden-source-10a.md"
    assert source_file.storage_path
    assert source_file.hash
    assert (api_client.storage_root / source_file.storage_path).read_bytes() == markdown_bytes

    jobs_response = await api_client.client.get(f"/api/v1/projects/{api_client.project.id}/ingestion-jobs")
    assert jobs_response.status_code == 200
    queued_job = jobs_response.json()["items"][0]
    assert queued_job["source_file_id"] == str(source_file_id)
    assert queued_job["status"] == "pending"

    execute_response = await api_client.client.post(
        f"/api/v1/projects/{api_client.project.id}/ingestion-jobs/{queued_job['id']}/execute"
    )
    assert execute_response.status_code == 200
    completed_job = execute_response.json()
    assert completed_job["status"] == "completed"
    assert completed_job["stage"] == "knowledge_ready"
    assert completed_job["result_json"]["knowledge_entry_count"] >= 1

    await api_client.db.refresh(source_file)
    assert source_file.status == "ready"
    assert source_file.metadata_json["extractedKnowledgeCount"] >= 1

    search_response = await api_client.client.get(
        "/api/v1/knowledge/search",
        params={"q": MARKER_PHRASE, "type": "fulltext", "project_id": str(api_client.project.id)},
    )
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert search_body["total"] >= 1
    result_entry = search_body["results"][0]["entry"]
    assert MARKER_PHRASE in result_entry["content"]
    assert result_entry["source_file_id"] == str(source_file_id)

    provenance_response = await api_client.client.get(f"/api/v1/knowledge/provenance/{result_entry['id']}")
    assert provenance_response.status_code == 200
    provenance = provenance_response.json()
    assert provenance[0]["provider_id"] == "source_file_ingest"
    assert provenance[0]["raw_artifact_id"] == str(source_file_id)

    evidence = {
        "storage_backend": "local",
        "source_file_id": str(source_file_id),
        "ingestion_job_id": completed_job["id"],
        "knowledge_entry_id": result_entry["id"],
        "provenance_id": provenance[0]["id"],
    }
    assert all(evidence.values())


@pytest.mark.asyncio
async def test_source_to_knowledge_blocks_cross_project_access_and_recovers_from_failed_ingestion(api_client):
    markdown_bytes = f"REQ-10A-003: {MARKER_PHRASE} recovery path content.".encode("utf-8")
    upload_response = await api_client.client.post(
        f"/api/v1/projects/{api_client.project.id}/files",
        files={"file": ("recovery-source-10a.md", markdown_bytes, "text/markdown")},
    )
    source_file_id = UUID(upload_response.json()["id"])
    source_file = await api_client.db.get(SourceFile, source_file_id)

    api_client.current_user["value"] = api_client.outsider
    denied_response = await api_client.client.get(f"/api/v1/projects/{api_client.project.id}/ingestion-jobs")
    assert denied_response.status_code == 403
    api_client.current_user["value"] = api_client.owner

    jobs = (
        await api_client.db.scalars(select(SourceIngestionJob).where(SourceIngestionJob.source_file_id == source_file.id))
    ).all()
    assert len(jobs) == 1

    duplicate_response = await api_client.client.post(
        f"/api/v1/projects/{api_client.project.id}/files/{source_file.id}/reingest"
    )
    assert duplicate_response.status_code == 409

    stored_path = api_client.storage_root / source_file.storage_path
    stored_bytes = stored_path.read_bytes()
    stored_path.unlink()

    failed_response = await api_client.client.post(
        f"/api/v1/projects/{api_client.project.id}/ingestion-jobs/{jobs[0].id}/execute"
    )
    assert failed_response.status_code == 200
    failed_job = failed_response.json()
    assert failed_job["status"] == "failed"
    assert failed_job["error_message"]
    await api_client.db.refresh(source_file)
    assert source_file.status == "failed"
    assert source_file.metadata_json["errorMessage"]

    retry_response = await api_client.client.post(
        f"/api/v1/projects/{api_client.project.id}/ingestion-jobs/{jobs[0].id}/retry"
    )
    assert retry_response.status_code == 200
    assert retry_response.json()["status"] == "pending"

    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_bytes(stored_bytes)
    completed_response = await api_client.client.post(
        f"/api/v1/projects/{api_client.project.id}/ingestion-jobs/{jobs[0].id}/execute"
    )
    assert completed_response.status_code == 200
    assert completed_response.json()["status"] == "completed"

    old_entries = list(
        (
            await api_client.db.scalars(
                select(KnowledgeEntry).where(KnowledgeEntry.source_file_id == source_file.id)
            )
        ).all()
    )
    assert old_entries

    reingest_response = await api_client.client.post(
        f"/api/v1/projects/{api_client.project.id}/files/{source_file.id}/reingest"
    )
    assert reingest_response.status_code == 200
    reingest_job_id = reingest_response.json()["id"]
    for entry in old_entries:
        await api_client.db.refresh(entry)
        assert entry.deleted_at is not None

    replacement_response = await api_client.client.post(
        f"/api/v1/projects/{api_client.project.id}/ingestion-jobs/{reingest_job_id}/execute"
    )
    assert replacement_response.status_code == 200
    assert replacement_response.json()["status"] == "completed"

    active_entries = list(
        (
            await api_client.db.scalars(
                select(KnowledgeEntry).where(
                    KnowledgeEntry.source_file_id == source_file.id,
                    KnowledgeEntry.deleted_at.is_(None),
                )
            )
        ).all()
    )
    assert active_entries
    assert {entry.id for entry in active_entries}.isdisjoint({entry.id for entry in old_entries})
    assert await api_client.db.scalar(
        select(ProvenanceRecord).where(ProvenanceRecord.entry_id == active_entries[0].id)
    )
