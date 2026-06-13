"""S3 Storage Provider

S3-compatible object storage provider using boto3.
Supports AWS S3, MinIO, and other S3-compatible services.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from uuid import UUID

import boto3
from botocore.exceptions import ClientError, BotoCoreError

from app.services.storage import StorageProvider, StorageError


logger = logging.getLogger(__name__)


class S3StorageProvider(StorageProvider):
    """S3-compatible object storage provider.

    Supports:
    - AWS S3
    - MinIO (self-hosted S3)
    - Other S3-compatible services (Oracle Cloud Infrastructure, etc.)
    """

    DEFAULT_REGION = "us-east-1"
    MAX_UPLOAD_SIZE = 5 * 1024 * 1024 * 1024  # 5GB
    MAX_PART_SIZE = 100 * 1024 * 1024  # 100MB for multipart

    def __init__(
        self,
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        region_name: str | None = None,
        bucket_name: str | None = None,
        **kwargs,
    ):
        """Initialize S3 storage provider.

        Args:
            endpoint_url: S3 endpoint URL (for MinIO or custom S3)
            aws_access_key_id: AWS access key ID
            aws_secret_access_key: AWS secret access key
            region_name: AWS region name
            bucket_name: S3 bucket name
            **kwargs: Additional boto3 configuration options
        """
        self.endpoint_url = endpoint_url
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.region_name = region_name or self.DEFAULT_REGION
        self.bucket_name = bucket_name
        self.kwargs = kwargs

        # Initialize boto3 client
        self._client = None
        self._resource = None

    @property
    def client(self):
        """Lazy initialization of S3 client."""
        if self._client is None:
            config_kwargs = {
                "endpoint_url": self.endpoint_url,
                "aws_access_key_id": self.aws_access_key_id,
                "aws_secret_access_key": self.aws_secret_access_key,
                "region_name": self.region_name,
            }
            config_kwargs.update(self.kwargs)

            self._client = boto3.client("s3", **config_kwargs)

        return self._client

    @property
    def resource(self):
        """Lazy initialization of S3 resource."""
        if self._resource is None:
            config_kwargs = {
                "endpoint_url": self.endpoint_url,
                "aws_access_key_id": self.aws_access_key_id,
                "aws_secret_access_key": self.aws_secret_access_key,
                "region_name": self.region_name,
            }
            config_kwargs.update(self.kwargs)

            self._resource = boto3.resource("s3", **config_kwargs)

        return self._resource

    def _normalize_key(self, key: str) -> str:
        """Normalize storage key to S3 key format.

        Args:
            key: Storage key

        Returns:
            Normalized S3 key
        """
        # Remove leading slashes and normalize
        key = key.lstrip("/")
        return key

    def _build_key(
        self,
        tenant_id: UUID,
        project_id: UUID | None,
        filename: str,
    ) -> str:
        """Build S3 key from components.

        Args:
            tenant_id: Tenant UUID
            project_id: Optional project UUID
            filename: File name

        Returns:
            S3 key
        """
        parts = [str(tenant_id)]
        if project_id:
            parts.append(str(project_id))
        parts.append(filename)
        return "/".join(parts)

    async def upload(
        self,
        content: bytes,
        filename: str,
        tenant_id: UUID,
        project_id: UUID | None = None,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Upload a file to S3.

        Args:
            content: File content as bytes
            filename: Original filename
            tenant_id: Tenant UUID
            project_id: Optional project UUID
            content_type: MIME type
            metadata: Additional metadata

        Returns:
            Storage key
        """
        try:
            key = self._build_key(tenant_id, project_id, filename)

            # Build extra args
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type

            if metadata:
                extra_args["Metadata"] = metadata

            # Calculate content hash
            content_hash = hashlib.sha256(content).hexdigest()
            extra_args["Metadata"]["content-hash"] = content_hash

            # Upload to S3
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=content,
                **extra_args,
            )

            logger.info(f"Uploaded file to S3: {key}")
            return key

        except (ClientError, BotoCoreError) as e:
            logger.error(f"S3 upload failed: {e}")
            raise StorageError(f"Failed to upload file: {e}")

    async def download(self, key: str) -> bytes:
        """Download a file from S3.

        Args:
            key: Storage key

        Returns:
            File content as bytes
        """
        try:
            key = self._normalize_key(key)

            response = self.client.get_object(
                Bucket=self.bucket_name,
                Key=key,
            )

            # Read content
            body = response["Body"]
            content = b""
            async for chunk in body.iter_chunks():
                content += chunk

            return content

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "404":
                raise StorageError(f"File not found: {key}")
            logger.error(f"S3 download failed: {e}")
            raise StorageError(f"Failed to download file: {e}")

    async def delete(self, key: str) -> None:
        """Delete a file from S3.

        Args:
            key: Storage key
        """
        try:
            key = self._normalize_key(key)

            self.client.delete_object(
                Bucket=self.bucket_name,
                Key=key,
            )

            logger.info(f"Deleted file from S3: {key}")

        except (ClientError, BotoCoreError) as e:
            logger.error(f"S3 delete failed: {e}")
            raise StorageError(f"Failed to delete file: {e}")

    async def exists(self, key: str) -> bool:
        """Check if a file exists in S3.

        Args:
            key: Storage key

        Returns:
            True if file exists
        """
        try:
            key = self._normalize_key(key)

            self.client.head_object(
                Bucket=self.bucket_name,
                Key=key,
            )
            return True

        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            logger.error(f"S3 exists check failed: {e}")
            return False

    async def get_url(
        self,
        key: str,
        expires_in: int = 3600,
    ) -> str:
        """Get a pre-signed URL for a file.

        Args:
            key: Storage key
            expires_in: URL expiration time in seconds

        Returns:
            Pre-signed URL
        """
        try:
            key = self._normalize_key(key)

            url = self.client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": key,
                },
                ExpiresIn=expires_in,
            )

            return url

        except (ClientError, BotoCoreError) as e:
            logger.error(f"S3 URL generation failed: {e}")
            raise StorageError(f"Failed to generate URL: {e}")

    async def list_files(
        self,
        prefix: str | None = None,
        tenant_id: UUID | None = None,
        project_id: UUID | None = None,
        max_keys: int = 1000,
    ) -> list[dict[str, Any]]:
        """List files in S3 with optional prefix filter.

        Args:
            prefix: Optional prefix filter
            tenant_id: Optional tenant filter
            project_id: Optional project filter
            max_keys: Maximum number of keys to return

        Returns:
            List of file info dicts with key, size, last_modified, etc.
        """
        try:
            # Build prefix
            parts = []
            if tenant_id:
                parts.append(str(tenant_id))
            if project_id:
                parts.append(str(project_id))
            if prefix:
                parts.append(prefix.lstrip("/"))

            s3_prefix = "/".join(parts) if parts else ""

            # List objects
            response = self.client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=s3_prefix,
                MaxKeys=max_keys,
            )

            files = []
            for obj in response.get("Contents", []):
                files.append({
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat() if obj.get("LastModified") else None,
                    "etag": obj.get("ETag", "").strip('"'),
                })

            return files

        except (ClientError, BotoCoreError) as e:
            logger.error(f"S3 list files failed: {e}")
            raise StorageError(f"Failed to list files: {e}")

    async def copy(
        self,
        source_key: str,
        dest_key: str,
        tenant_id: UUID,
        project_id: UUID | None = None,
    ) -> str:
        """Copy a file within S3.

        Args:
            source_key: Source key
            dest_key: Destination key
            tenant_id: Tenant UUID
            project_id: Optional project UUID

        Returns:
            Destination key
        """
        try:
            source_key = self._normalize_key(source_key)
            dest_key = self._normalize_key(dest_key)

            # Build full source path
            if not source_key.startswith(f"{self.bucket_name}/"):
                source_key = f"{self.bucket_name}/{source_key}"

            self.client.copy_object(
                Bucket=self.bucket_name,
                Key=dest_key,
                CopySource=source_key,
            )

            logger.info(f"Copied S3 file: {source_key} -> {dest_key}")
            return dest_key

        except (ClientError, BotoCoreError) as e:
            logger.error(f"S3 copy failed: {e}")
            raise StorageError(f"Failed to copy file: {e}")

    async def get_metadata(self, key: str) -> dict[str, Any]:
        """Get metadata for a file in S3.

        Args:
            key: Storage key

        Returns:
            Metadata dict
        """
        try:
            key = self._normalize_key(key)

            response = self.client.head_object(
                Bucket=self.bucket_name,
                Key=key,
            )

            return {
                "key": key,
                "size": response.get("ContentLength", 0),
                "content_type": response.get("ContentType", "application/octet-stream"),
                "last_modified": response.get("LastModified", "").isoformat() if response.get("LastModified") else None,
                "metadata": response.get("Metadata", {}),
                "etag": response.get("ETag", "").strip('"'),
            }

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "404":
                raise StorageError(f"File not found: {key}")
            logger.error(f"S3 metadata failed: {e}")
            raise StorageError(f"Failed to get metadata: {e}")

    def health_check(self) -> dict[str, Any]:
        """Check S3 connection health.

        Returns:
            Health status dict
        """
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
            return {
                "status": "healthy",
                "bucket": self.bucket_name,
                "endpoint": self.endpoint_url or "AWS S3",
            }
        except (ClientError, BotoCoreError) as e:
            return {
                "status": "unhealthy",
                "bucket": self.bucket_name,
                "error": str(e),
            }