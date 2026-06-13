"""Raw Artifact Store Schemas

Pydantic v2 schemas for raw artifact request/response validation.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RawArtifactCreate(BaseModel):
    """Schema for creating a raw artifact."""
    provider_id: UUID = Field(..., description="Provider UUID")
    provider_version_id: UUID = Field(..., description="Provider version UUID")
    provider_run_id: UUID = Field(..., description="Provider run UUID")
    artifact_type: str = Field(..., min_length=1, max_length=50, description="Artifact type")
    content: dict[str, Any] = Field(..., description="Raw JSON content")
    schema_version: str = Field(default="1.0", max_length=20, description="Schema version")
    upstream_pin: str | None = Field(None, max_length=255, description="Upstream commit SHA or tag")
    project_id: UUID | None = Field(None, description="Optional project ID")
    created_by: UUID | None = Field(None, description="User who triggered the run")


class RawArtifactUpdate(BaseModel):
    """Schema for updating a raw artifact."""
    normalized_graph_id: UUID | None = Field(None, description="Reference to normalized output")
    upstream_pin: str | None = Field(None, max_length=255, description="Upstream commit SHA or tag")


class RawArtifactResponse(BaseModel):
    """Schema for raw artifact response."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID | None

    provider_id: UUID
    provider_version_id: UUID
    provider_run_id: UUID

    artifact_type: str
    content: dict[str, Any]
    content_hash: str
    file_size: int | None

    schema_version: str
    upstream_pin: str | None

    normalized_graph_id: UUID | None

    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class RawArtifactListItem(BaseModel):
    """Schema for raw artifact list item (lightweight)."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID | None

    provider_id: UUID
    provider_version_id: UUID
    provider_run_id: UUID

    artifact_type: str
    content_hash: str
    file_size: int | None

    schema_version: str
    upstream_pin: str | None

    normalized_graph_id: UUID | None

    created_at: datetime


class RawArtifactSearch(BaseModel):
    """Schema for raw artifact search/filter parameters."""
    provider_id: UUID | None = Field(None, description="Filter by provider")
    provider_version_id: UUID | None = Field(None, description="Filter by provider version")
    artifact_type: str | None = Field(None, max_length=50, description="Filter by artifact type")
    project_id: UUID | None = Field(None, description="Filter by project")
    start_date: datetime | None = Field(None, description="Filter by start date")
    end_date: datetime | None = Field(None, description="Filter by end date")
    limit: int = Field(default=100, ge=1, le=1000, description="Max results to return")
    offset: int = Field(default=0, ge=0, description="Offset for pagination")


class RawArtifactVersionSummary(BaseModel):
    """Schema for version comparison summary."""
    provider_id: UUID
    provider_name: str
    total_artifacts: int
    latest_version: str
    versions: list[dict[str, Any]]


class RawArtifactReplayRequest(BaseModel):
    """Schema for replay request."""
    normalize_only: bool = Field(default=True, description="Only normalize without storing")


class RawArtifactReplayResponse(BaseModel):
    """Schema for replay response."""
    success: bool
    artifact_id: UUID | None
    normalized_graph_id: UUID | None
    message: str
    replayed_at: datetime