"""Storage Services

Abstract storage provider interface and concrete implementations.
"""

import hashlib
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

try:
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - exercised when S3 extras are not installed
    boto3 = None
    BotoConfig = None
    ClientError = Exception

from app.core.settings import settings


@dataclass
class StorageHandle:
    """Handle representing a stored file.

    Contains metadata about the stored file needed for retrieval and management.
    """

    path: str
    filename: str
    content_type: str
    size: int
    hash: str  # SHA256 hex string
    storage_backend: str


class StorageProvider(ABC):
    """Abstract storage provider interface.

    Defines the contract for upload, download, delete, and URL generation.
    Implementations can use local filesystem, S3, or other backends.
    """

    @abstractmethod
    async def upload(
        self,
        tenant_id: str,
        project_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> StorageHandle:
        """Upload a file and return a storage handle.

        Args:
            tenant_id: Tenant UUID string
            project_id: Project UUID string
            filename: Original filename
            content: File content as bytes
            content_type: MIME type of the file

        Returns:
            StorageHandle with file metadata

        Raises:
            ValueError: If content type is not supported or file is too large
        """
        pass

    @abstractmethod
    async def download(self, handle: StorageHandle) -> bytes:
        """Download a file by its storage handle.

        Args:
            handle: StorageHandle from a previous upload

        Returns:
            File content as bytes

        Raises:
            FileNotFoundError: If file does not exist
        """
        pass

    @abstractmethod
    async def delete(self, handle: StorageHandle) -> None:
        """Delete a file by its storage handle.

        Args:
            handle: StorageHandle from a previous upload

        Raises:
            FileNotFoundError: If file does not exist
        """
        pass

    @abstractmethod
    async def get_url(self, handle: StorageHandle, expires_in: int = 3600) -> str:
        """Get a URL for accessing the file.

        For local storage, returns a file:// URL.
        For S3, returns a pre-signed URL.

        Args:
            handle: StorageHandle from a previous upload
            expires_in: URL expiration time in seconds (for pre-signed URLs)

        Returns:
            URL string for accessing the file
        """
        pass

    async def exists(self, handle: StorageHandle) -> bool:
        """Check if a file exists.

        Args:
            handle: StorageHandle to check

        Returns:
            True if file exists, False otherwise
        """
        try:
            await self.download(handle)
            return True
        except FileNotFoundError:
            return False


class LocalStorageProvider(StorageProvider):
    """Local filesystem storage provider.

    Stores files in {STORAGE_LOCAL_PATH}/{tenant_id}/{project_id}/{uuid}/{filename}
    """

    def __init__(self, base_path: str | None = None):
        """Initialize local storage provider.

        Args:
            base_path: Base directory for file storage. Defaults to settings.STORAGE_LOCAL_PATH
        """
        self.base_path = Path(base_path or settings.STORAGE_LOCAL_PATH)
        self._ensure_base_path()

    def _ensure_base_path(self) -> None:
        """Ensure base path exists."""
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _compute_hash(self, content: bytes) -> str:
        """Compute SHA256 hash of content.

        Args:
            content: File content

        Returns:
            Hex string of SHA256 hash
        """
        return hashlib.sha256(content).hexdigest()

    def _generate_storage_path(
        self,
        tenant_id: str,
        project_id: str,
        filename: str,
    ) -> tuple[str, str]:
        """Generate unique storage path for a file.

        Args:
            tenant_id: Tenant UUID string
            project_id: Project UUID string
            filename: Original filename

        Returns:
            Tuple of (storage_path, full_file_path)

        Raises:
            ValueError: If filename contains path traversal characters
        """
        # Sanitize filename to prevent path traversal attacks
        # Remove any .. or path separators
        sanitized = filename.replace("..", "").replace("/", "_").replace("\\", "_").replace(":", "_").replace("\0", "")
        if sanitized != filename:
            raise ValueError(f"Invalid filename: contains path traversal or invalid characters")

        unique_id = str(uuid.uuid4())
        storage_path = f"{tenant_id}/{project_id}/{unique_id}/{sanitized}"
        full_path = self.base_path / tenant_id / project_id / unique_id / sanitized
        return storage_path, str(full_path)

    async def upload(
        self,
        tenant_id: str,
        project_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> StorageHandle:
        """Upload a file to local storage.

        Args:
            tenant_id: Tenant UUID string
            project_id: Project UUID string
            filename: Original filename
            content: File content as bytes
            content_type: MIME type of the file

        Returns:
            StorageHandle with file metadata

        Raises:
            ValueError: If content type is not supported or file is too large
        """
        # Validate content type
        supported_types = {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "text/plain",
            "text/markdown",
            "text/csv",
        }
        if content_type not in supported_types:
            raise ValueError(f"Unsupported content type: {content_type}")

        # Validate file size (default 100MB)
        max_size = 100 * 1024 * 1024
        if len(content) > max_size:
            raise ValueError(f"File too large: {len(content)} bytes (max: {max_size})")

        # Compute hash
        file_hash = self._compute_hash(content)

        # Generate storage path
        storage_path, full_path = self._generate_storage_path(tenant_id, project_id, filename)

        # Ensure directory exists
        Path(full_path).parent.mkdir(parents=True, exist_ok=True)

        # Write file
        with open(full_path, "wb") as f:
            f.write(content)

        return StorageHandle(
            path=storage_path,
            filename=filename,
            content_type=content_type,
            size=len(content),
            hash=file_hash,
            storage_backend="local",
        )

    async def download(self, handle: StorageHandle) -> bytes:
        """Download a file from local storage.

        Args:
            handle: StorageHandle from a previous upload

        Returns:
            File content as bytes

        Raises:
            FileNotFoundError: If file does not exist
        """
        full_path = self.base_path / handle.path
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {handle.path}")
        return full_path.read_bytes()

    async def delete(self, handle: StorageHandle) -> None:
        """Delete a file from local storage.

        Args:
            handle: StorageHandle from a previous upload

        Raises:
            FileNotFoundError: If file does not exist
        """
        full_path = self.base_path / handle.path
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {handle.path}")
        full_path.unlink()

    async def get_url(self, handle: StorageHandle, expires_in: int = 3600) -> str:
        """Get a file:// URL for local storage.

        Args:
            handle: StorageHandle from a previous upload
            expires_in: Ignored for local storage

        Returns:
            File URL string
        """
        full_path = self.base_path / handle.path
        # Convert to absolute path with file:// scheme
        return f"file://{full_path.absolute()}"


class S3StorageProvider(StorageProvider):
    """S3-compatible storage provider using boto3.

    Supports AWS S3, MinIO, OBS (Huawei Cloud), and other S3-compatible services.
    """

    def __init__(
        self,
        bucket: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        endpoint: str | None = None,
        region: str = "us-east-1",
    ):
        """Initialize S3 storage provider.

        Args:
            bucket: S3 bucket name
            access_key: AWS access key ID
            secret_key: AWS secret access key
            endpoint: S3 endpoint URL (for OBS/custom S3-compatible services)
            region: AWS region
        """
        self.bucket = bucket or settings.S3_BUCKET
        self.access_key = access_key or settings.AWS_ACCESS_KEY_ID
        self.secret_key = secret_key or settings.AWS_SECRET_ACCESS_KEY
        self.endpoint = endpoint or settings.S3_ENDPOINT_URL
        self.region = region or settings.AWS_REGION

        if boto3 is None or BotoConfig is None:
            raise RuntimeError("S3 storage backend requires boto3 and botocore to be installed")

        # Build boto3 client with retry configuration
        config = BotoConfig(
            retries={'max_attempts': 3, 'mode': 'standard'},
            connect_timeout=5,
            read_timeout=30,
        )

        session_kwargs = {
            'aws_access_key_id': self.access_key,
            'aws_secret_access_key': self.secret_key,
            'region_name': self.region,
        }

        if self.endpoint:
            # For MinIO, OBS, and other S3-compatible services
            self.s3 = boto3.client(
                's3',
                endpoint_url=self.endpoint,
                config=config,
                **session_kwargs
            )
        else:
            # For AWS S3
            self.s3 = boto3.client('s3', config=config, **session_kwargs)

    def _generate_key(self, tenant_id: str, project_id: str, filename: str) -> str:
        """Generate a unique S3 key for the file.

        Args:
            tenant_id: Tenant UUID
            project_id: Project UUID
            filename: Original filename

        Returns:
            S3 object key string
        """
        ext = Path(filename).suffix
        unique_id = uuid.uuid4().hex[:12]
        timestamp = uuid.uuid4().node
        safe_filename = "".join(c for c in filename if c.isalnum() or c in ('.', '-', '_')).strip()[:50]
        return f"tenants/{tenant_id}/projects/{project_id}/{safe_filename}_{timestamp}_{unique_id}{ext}"

    async def upload(
        self,
        tenant_id: str,
        project_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> StorageHandle:
        """Upload a file to S3.

        Args:
            tenant_id: Tenant UUID
            project_id: Project UUID
            filename: Original filename
            content: File content as bytes
            content_type: MIME type

        Returns:
            StorageHandle with file metadata

        Raises:
            RuntimeError: If upload fails
        """
        key = self._generate_key(tenant_id, project_id, filename)
        content_hash = hashlib.sha256(content).hexdigest()

        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                Metadata={
                    'tenant_id': tenant_id,
                    'project_id': project_id,
                    'original_filename': filename,
                }
            )
        except ClientError as e:
            raise RuntimeError(f"S3 upload failed: {e}") from e

        return StorageHandle(
            path=key,
            filename=filename,
            content_type=content_type,
            size=len(content),
            hash=content_hash,
            storage_backend='s3',
        )

    async def download(self, handle: StorageHandle) -> bytes:
        """Download a file from S3.

        Args:
            handle: StorageHandle from a previous upload

        Returns:
            File content as bytes

        Raises:
            RuntimeError: If download fails
        """
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=handle.path)
            return response['Body'].read()
        except ClientError as e:
            raise RuntimeError(f"S3 download failed: {e}") from e

    async def delete(self, handle: StorageHandle) -> None:
        """Delete a file from S3.

        Args:
            handle: StorageHandle from a previous upload

        Raises:
            RuntimeError: If delete fails
        """
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=handle.path)
        except ClientError as e:
            raise RuntimeError(f"S3 delete failed: {e}") from e

    async def get_url(self, handle: StorageHandle, expires_in: int = 3600) -> str:
        """Get a pre-signed URL for S3.

        Args:
            handle: StorageHandle from a previous upload
            expires_in: URL expiration time in seconds (default 1 hour)

        Returns:
            Pre-signed URL string

        Raises:
            RuntimeError: If URL generation fails
        """
        try:
            url = self.s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket, 'Key': handle.path},
                ExpiresIn=expires_in,
            )
            return url
        except ClientError as e:
            raise RuntimeError(f"S3 pre-signed URL generation failed: {e}") from e


def get_storage_provider() -> StorageProvider:
    """Factory function to get the configured storage provider.

    Returns:
        StorageProvider: Configured storage provider instance
    """
    backend = settings.STORAGE_BACKEND

    if backend == "local":
        return LocalStorageProvider()
    elif backend == "s3":
        return S3StorageProvider(
            bucket=settings.S3_BUCKET,
            access_key=settings.AWS_ACCESS_KEY_ID,
            secret_key=settings.AWS_SECRET_ACCESS_KEY,
            endpoint=settings.S3_ENDPOINT_URL,
            region=settings.AWS_REGION,
        )
    else:
        raise ValueError(f"Unknown storage backend: {backend}")
