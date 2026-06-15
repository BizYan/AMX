"""Creator attribution contract tests for production creation paths."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-creator-attribution-contracts.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-creator-attribution-contracts-secret"

import pytest

from app.domains.documents.service import DocumentService
from app.domains.export.service import ExportService
from app.domains.templates.schemas import TemplateCreate, TemplateVersionCreate
from app.domains.templates.service import TemplateService


@pytest.mark.asyncio
async def test_create_document_requires_created_by():
    service = DocumentService(AsyncMock())

    with pytest.raises(ValueError, match="created_by is required"):
        await service.create_document(
            tenant_id=uuid4(),
            project_id=uuid4(),
            doc_type="prd",
            title="PRD",
            created_by=None,
        )


@pytest.mark.asyncio
async def test_create_template_requires_created_by():
    service = TemplateService(AsyncMock())

    with pytest.raises(ValueError, match="created_by is required"):
        await service.create_template(
            tenant_id=uuid4(),
            template_data=TemplateCreate(name="PRD Template", doc_type="prd"),
            created_by=None,
        )


@pytest.mark.asyncio
async def test_create_template_version_requires_created_by():
    service = TemplateService(AsyncMock())
    service.get_template = AsyncMock(return_value=SimpleNamespace(doc_type="prd", version_count=0))

    with pytest.raises(ValueError, match="created_by is required"):
        await service.create_template_version(
            tenant_id=uuid4(),
            template_id=uuid4(),
            version_data=TemplateVersionCreate(version=1),
            created_by=None,
        )


@pytest.mark.asyncio
async def test_upload_template_version_requires_created_by():
    db = AsyncMock()
    max_version = MagicMock()
    max_version.scalar.return_value = 0
    db.execute.return_value = max_version

    service = TemplateService(db)
    service.get_template = AsyncMock(return_value=SimpleNamespace(doc_type="prd", version_count=0))
    service.parse_template = AsyncMock(return_value=SimpleNamespace(placeholders=[], page_types=[]))

    with pytest.raises(ValueError, match="created_by is required"):
        await service.upload_template_version(
            tenant_id=uuid4(),
            template_id=uuid4(),
            file_content=b"template",
            created_by=None,
        )


@pytest.mark.asyncio
async def test_create_export_job_requires_created_by():
    service = ExportService(AsyncMock())

    with pytest.raises(ValueError, match="created_by is required"):
        await service.create_export_job(
            tenant_id=uuid4(),
            project_id=uuid4(),
            document_id=uuid4(),
            template_id=None,
            export_type="word",
            created_by=None,
        )
