"""Raw Artifact Store Domain Model

Stores external Provider (Graphify/GitNexus) raw output for audit, replay, and comparison.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as UUIDType
from sqlalchemy.orm import relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UuidMixin


class RawArtifact(Base, UuidMixin, TimestampMixin, SoftDeleteMixin):
    """Raw artifact storage for external Provider output.

    Stores raw JSON output from external providers for:
    - Audit trail: Track all provider outputs
    - Replay capability: Re-run artifacts through normalization
    - Diff comparison: Compare outputs across provider versions
    - Contract test verification: Verify provider behavior

    Attributes:
        tenant_id: Tenant UUID for multi-tenancy isolation
        project_id: Optional project association
        provider_id: Provider that generated this artifact
        provider_version_id: Provider version that generated this artifact
        provider_run_id: Associated provider run
        artifact_type: Type of artifact (graph/wiki/code_analysis/summary)
        content: Raw JSON output from provider
        content_hash: SHA256 hash of content for deduplication
        file_size: Size in bytes if content is large
        schema_version: Version of the artifact schema
        upstream_pin: Commit SHA or tag of upstream dependency
        normalized_graph_id: Reference to normalized output
        created_by: User who triggered the provider run
    """

    __tablename__ = "raw_artifacts"

    tenant_id = Column(
        UUIDType(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=True,
        index=True,
    )
    project_id = Column(
        UUIDType(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=True,
    )

    provider_id = Column(
        UUIDType(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_version_id = Column(
        UUIDType(as_uuid=True),
        ForeignKey("provider_versions.id"),
        nullable=False,
        index=True,
    )
    provider_run_id = Column(
        UUIDType(as_uuid=True),
        ForeignKey("provider_runs.id"),
        nullable=False,
        index=True,
    )

    artifact_type = Column(String(50), nullable=False, index=True)
    content = Column(JSONB, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    file_size = Column(Integer, nullable=True)

    schema_version = Column(String(20), nullable=False, default="1.0")
    upstream_pin = Column(String(255), nullable=True)

    normalized_graph_id = Column(UUIDType(as_uuid=True), nullable=True, index=True)

    created_by = Column(
        UUIDType(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_raw_artifacts_tenant_provider", "tenant_id", "provider_id"),
        Index("ix_raw_artifacts_tenant_type_created", "tenant_id", "artifact_type", "created_at"),
        Index("ix_raw_artifacts_content_hash", "content_hash", unique=True),
    )