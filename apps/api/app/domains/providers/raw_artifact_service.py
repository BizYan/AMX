"""Raw Artifact Store Service

Business logic for raw artifact storage, retrieval, and management.
"""

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.providers.raw_artifact import RawArtifact
from app.domains.providers.raw_artifact_schemas import (
    RawArtifactCreate,
    RawArtifactSearch,
)


class RawArtifactService:
    """Service for managing raw artifacts.

    Handles storage, retrieval, and deduplication of external provider output.
    """

    def __init__(self, db: AsyncSession):
        """Initialize service with database session.

        Args:
            db: Async SQLAlchemy session
        """
        self.db = db

    @staticmethod
    def compute_content_hash(content: dict) -> str:
        """Compute SHA256 hash of content.

        Args:
            content: JSON content dict

        Returns:
            Hex-encoded SHA256 hash
        """
        content_bytes = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(content_bytes).hexdigest()

    async def store(
        self,
        tenant_id: UUID | None,
        project_id: UUID | None,
        provider_id: UUID,
        version_id: UUID,
        run_id: UUID,
        artifact_type: str,
        content: dict,
        schema_version: str = "1.0",
        upstream_pin: str | None = None,
        created_by: UUID | None = None,
    ) -> RawArtifact:
        """Store raw artifact from provider.

        Args:
            tenant_id: Tenant UUID for multi-tenancy
            project_id: Optional project UUID
            provider_id: Provider UUID
            version_id: Provider version UUID
            run_id: Provider run UUID
            artifact_type: Type of artifact (graph/wiki/code_analysis/summary)
            content: Raw JSON output from provider
            schema_version: Version of the artifact schema
            upstream_pin: Commit SHA or tag of upstream dependency
            created_by: User who triggered the run

        Returns:
            Created RawArtifact
        """
        content_hash = self.compute_content_hash(content)
        file_size = len(json.dumps(content, separators=(",", ":")).encode("utf-8"))

        artifact = RawArtifact(
            tenant_id=tenant_id,
            project_id=project_id,
            provider_id=provider_id,
            provider_version_id=version_id,
            provider_run_id=run_id,
            artifact_type=artifact_type,
            content=content,
            content_hash=content_hash,
            file_size=file_size,
            schema_version=schema_version,
            upstream_pin=upstream_pin,
            created_by=created_by,
        )

        self.db.add(artifact)
        await self.db.flush()
        await self.db.refresh(artifact)

        return artifact

    async def get(self, artifact_id: UUID, tenant_id: UUID) -> RawArtifact | None:
        """Get single artifact with tenant check.

        Args:
            artifact_id: Artifact UUID
            tenant_id: Tenant UUID for access control

        Returns:
            RawArtifact if found and accessible, None otherwise
        """
        result = await self.db.execute(
            select(RawArtifact).where(
                RawArtifact.id == artifact_id,
                RawArtifact.tenant_id == tenant_id,
                RawArtifact.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        provider_id: UUID | None = None,
        provider_version_id: UUID | None = None,
        artifact_type: str | None = None,
        project_id: UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[RawArtifact], int]:
        """List artifacts with filters.

        Args:
            tenant_id: Tenant UUID for access control
            provider_id: Optional filter by provider
            provider_version_id: Optional filter by provider version
            artifact_type: Optional filter by artifact type
            project_id: Optional filter by project
            skip: Pagination offset
            limit: Page size

        Returns:
            Tuple of (artifacts list, total count)
        """
        query = select(RawArtifact).where(
            RawArtifact.tenant_id == tenant_id,
            RawArtifact.deleted_at.is_(None),
        )

        if provider_id:
            query = query.where(RawArtifact.provider_id == provider_id)

        if provider_version_id:
            query = query.where(RawArtifact.provider_version_id == provider_version_id)

        if artifact_type:
            query = query.where(RawArtifact.artifact_type == artifact_type)

        if project_id:
            query = query.where(RawArtifact.project_id == project_id)

        count_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar() or 0

        query = query.order_by(RawArtifact.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        artifacts = list(result.scalars().all())

        return artifacts, total

    async def get_by_hash(
        self,
        content_hash: str,
        tenant_id: UUID,
    ) -> RawArtifact | None:
        """Check for duplicate artifact by content hash.

        Args:
            content_hash: SHA256 hash of content
            tenant_id: Tenant UUID for access control

        Returns:
            Existing RawArtifact if found, None otherwise
        """
        result = await self.db.execute(
            select(RawArtifact).where(
                RawArtifact.content_hash == content_hash,
                RawArtifact.tenant_id == tenant_id,
                RawArtifact.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_versions(
        self,
        provider_id: UUID,
        tenant_id: UUID,
    ) -> list[dict]:
        """Get all versions of provider artifacts for comparison.

        Args:
            provider_id: Provider UUID
            tenant_id: Tenant UUID for access control

        Returns:
            List of version summaries with artifact counts
        """
        result = await self.db.execute(
            select(
                RawArtifact.provider_version_id,
                func.count(RawArtifact.id).label("artifact_count"),
                func.max(RawArtifact.created_at).label("latest_at"),
            )
            .where(
                RawArtifact.provider_id == provider_id,
                RawArtifact.tenant_id == tenant_id,
                RawArtifact.deleted_at.is_(None),
            )
            .group_by(RawArtifact.provider_version_id)
            .order_by(func.max(RawArtifact.created_at).desc())
        )

        versions = []
        for row in result.tuple():
            versions.append({
                "version_id": row[0],
                "artifact_count": row[1],
                "latest_at": row[2],
            })

        return versions

    async def update_normalized_reference(
        self,
        artifact_id: UUID,
        tenant_id: UUID,
        normalized_graph_id: UUID,
    ) -> RawArtifact | None:
        """Update the normalized graph reference for an artifact.

        Args:
            artifact_id: Artifact UUID
            tenant_id: Tenant UUID for access control
            normalized_graph_id: Normalized graph UUID

        Returns:
            Updated RawArtifact if found, None otherwise
        """
        artifact = await self.get(artifact_id, tenant_id)
        if not artifact:
            return None

        artifact.normalized_graph_id = normalized_graph_id
        await self.db.flush()
        await self.db.refresh(artifact)
        return artifact

    async def delete(self, artifact_id: UUID, tenant_id: UUID) -> bool:
        """Soft delete an artifact.

        Args:
            artifact_id: Artifact UUID
            tenant_id: Tenant UUID for access control

        Returns:
            True if deleted, False if not found
        """
        artifact = await self.get(artifact_id, tenant_id)
        if not artifact:
            return False

        artifact.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True