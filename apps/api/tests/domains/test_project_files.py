"""Tests for direct project file upload endpoint."""

import os
from datetime import datetime

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-secret"

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

from app.domains.projects.router import download_source_file, upload_project_file
from app.domains.projects.models import SourceFileStatus
from app.services.storage import StorageHandle, StorageProvider


class TestUploadProjectFile:
    """Tests for upload_project_file router endpoint."""

    @pytest.fixture
    def project_id(self):
        return uuid4()

    @pytest.fixture
    def current_user(self):
        user = MagicMock()
        user.id = uuid4()
        user.tenant_id = uuid4()
        return user

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def mock_storage(self):
        storage = AsyncMock(spec=StorageProvider)
        return storage

    @pytest.mark.asyncio
    async def test_upload_unauthorized_user(self, project_id, current_user, mock_db, mock_storage):
        """Test upload fails when user is not a project member."""
        file = MagicMock(spec=UploadFile)

        with patch(
            "app.domains.projects.router.check_project_membership",
            side_effect=HTTPException(status_code=403, detail="Not a project member"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await upload_project_file(
                    project_id=project_id,
                    file=file,
                    db=mock_db,
                    current_user=current_user,
                    storage=mock_storage,
                )
            assert exc_info.value.status_code == 403
            assert exc_info.value.detail == "Access denied"

    @pytest.mark.asyncio
    async def test_upload_unsupported_content_type(self, project_id, current_user, mock_db, mock_storage):
        """Test upload fails when file content type is unsupported."""
        file = AsyncMock(spec=UploadFile)
        file.filename = "unsupported.exe"
        file.content_type = "application/x-msdownload"
        file.read.return_value = b"some executable bytes"

        with patch("app.domains.projects.router.check_project_membership", return_value=True):
            with pytest.raises(HTTPException) as exc_info:
                await upload_project_file(
                    project_id=project_id,
                    file=file,
                    db=mock_db,
                    current_user=current_user,
                    storage=mock_storage,
                )
            assert exc_info.value.status_code == 400
            assert "Unsupported content type" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_upload_file_too_large(self, project_id, current_user, mock_db, mock_storage):
        """Test upload fails when file size exceeds limit."""
        file = AsyncMock(spec=UploadFile)
        file.filename = "large.pdf"
        file.content_type = "application/pdf"
        file.read.return_value = b"oversized"

        with patch("app.domains.projects.router.check_project_membership", return_value=True), patch(
            "app.domains.projects.router.MAX_FILE_SIZE", 4
        ):
            with pytest.raises(HTTPException) as exc_info:
                await upload_project_file(
                    project_id=project_id,
                    file=file,
                    db=mock_db,
                    current_user=current_user,
                    storage=mock_storage,
                )
            assert exc_info.value.status_code == 400
            assert "File too large" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_upload_success_stores_file_and_queues_ingestion(self, project_id, current_user, mock_db, mock_storage):
        """Test successful upload stores content and queues the source ingestion pipeline."""
        file = AsyncMock(spec=UploadFile)
        file.filename = "playwright-test.txt"
        file.content_type = "text/plain"
        file_bytes = b"Mock upload file content from Playwright spec."
        file.read.return_value = file_bytes

        handle = StorageHandle(
            path=f"{current_user.tenant_id}/{project_id}/unique_id_playwright-test.txt",
            filename="unique_id_playwright-test.txt",
            content_type="text/plain",
            size=len(file_bytes),
            hash="a" * 64,
            storage_backend="local",
        )
        mock_storage.upload.return_value = handle

        mock_source_file = MagicMock()
        mock_source_file.id = uuid4()
        mock_source_file.tenant_id = current_user.tenant_id
        mock_source_file.project_id = project_id
        mock_source_file.filename = "unique_id_playwright-test.txt"
        mock_source_file.original_filename = "playwright-test.txt"
        mock_source_file.content_type = "text/plain"
        mock_source_file.size = len(file_bytes)
        mock_source_file.hash = "a" * 64
        mock_source_file.storage_path = handle.path
        mock_source_file.status = SourceFileStatus.PENDING.value
        mock_source_file.metadata_json = {}
        mock_source_file.created_at = datetime.now()
        mock_source_file.updated_at = datetime.now()

        with patch("app.domains.projects.router.check_project_membership", return_value=True), patch(
            "app.domains.projects.router.SourceFileService"
        ) as mock_service_class, patch(
            "app.domains.projects.router.SourceIngestionService"
        ) as mock_ingestion_class:

            mock_service = AsyncMock()
            mock_service.create_source_file.return_value = mock_source_file

            async def mark_ingested(**_kwargs):
                mock_source_file.status = SourceFileStatus.READY.value
                mock_source_file.metadata_json = {
                    "ingestionStage": "已完成解析和知识抽取",
                    "extractedKnowledgeCount": 1,
                }
                return []

            mock_service.ingest_source_file.side_effect = mark_ingested
            mock_service_class.return_value = mock_service
            mock_ingestion = AsyncMock()
            mock_ingestion_class.return_value = mock_ingestion

            result = await upload_project_file(
                project_id=project_id,
                file=file,
                db=mock_db,
                current_user=current_user,
                storage=mock_storage,
            )

            mock_storage.upload.assert_awaited_once_with(
                tenant_id=str(current_user.tenant_id),
                project_id=str(project_id),
                filename="playwright-test.txt",
                content=file_bytes,
                content_type="text/plain",
            )

            mock_service.create_source_file.assert_awaited_once()
            mock_ingestion.enqueue.assert_awaited_once_with(mock_source_file, current_user.id)
            assert result.status == SourceFileStatus.PENDING.value

    @pytest.mark.asyncio
    async def test_download_uses_original_filename_header(self, project_id, current_user, mock_db, mock_storage):
        """Test download response keeps a browser-friendly original filename."""
        file_id = uuid4()
        file_bytes = b"downloaded file"
        mock_storage.download.return_value = file_bytes

        mock_source_file = MagicMock()
        mock_source_file.id = file_id
        mock_source_file.project_id = project_id
        mock_source_file.filename = "unique_internal_name.txt"
        mock_source_file.original_filename = "需求 文档.txt"
        mock_source_file.content_type = "text/plain"
        mock_source_file.size = len(file_bytes)
        mock_source_file.hash = "b" * 64
        mock_source_file.storage_path = f"{current_user.tenant_id}/{project_id}/unique_internal_name.txt"

        with patch("app.domains.projects.router.check_project_membership", return_value=True), patch(
            "app.domains.projects.router.SourceFileService"
        ) as mock_service_class:
            mock_service = AsyncMock()
            mock_service.get_source_file.return_value = mock_source_file
            mock_service_class.return_value = mock_service

            response = await download_source_file(
                project_id=project_id,
                file_id=file_id,
                db=mock_db,
                current_user=current_user,
                storage=mock_storage,
            )

            assert response.media_type == "text/plain"
            disposition = response.headers["content-disposition"]
            assert 'filename="download.txt"' in disposition
            assert "filename*=UTF-8''%E9%9C%80%E6%B1%82%20%E6%96%87%E6%A1%A3.txt" in disposition
            mock_storage.download.assert_awaited_once()
