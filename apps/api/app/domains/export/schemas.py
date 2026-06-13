"""Export Domain Schemas

Pydantic v2 schemas for export request/response validation.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# Export Job Schemas
class ExportJobBase(BaseModel):
    """Base export job schema."""

    project_id: UUID = Field(..., description="Project UUID")
    document_id: UUID | None = Field(None, description="Document UUID")
    template_id: UUID | None = Field(None, description="Template UUID")
    export_type: str = Field(..., description="Export type (word, markdown, pptx)")


class ExportJobCreate(ExportJobBase):
    """Schema for creating an export job."""

    created_by: UUID | None = Field(None, description="User ID of creator")


class ExportJobResponse(ExportJobBase):
    """Schema for export job response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    status: str
    output_path: str | None
    file_hash: str | None
    error_message: str | None
    created_by: UUID
    created_at: datetime
    completed_at: datetime | None


# Export Artifact Schemas
class ExportArtifactResponse(BaseModel):
    """Schema for export artifact response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    job_id: UUID
    filename: str
    content_type: str
    file_size: int
    storage_path: str
    file_hash: str | None
    created_at: datetime


class ExportJobWithArtifactsResponse(ExportJobResponse):
    """Schema for export job list responses including generated artifacts."""

    artifacts: list[ExportArtifactResponse] = Field(default_factory=list)


# Export Request Schemas
class WordExportRequest(BaseModel):
    """Schema for Word export request."""

    document_id: UUID = Field(..., description="Document UUID to export")
    template_id: UUID | None = Field(None, description="Optional template UUID to use")
    title: str | None = Field(None, description="Optional export title override")
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional variables for placeholder substitution",
    )


class MarkdownExportRequest(BaseModel):
    """Schema for Markdown export request."""

    document_id: UUID = Field(..., description="Document UUID to export")
    title: str | None = Field(None, description="Optional export title override")
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional variables for placeholder substitution",
    )


class PPTXExportRequest(BaseModel):
    """Schema for PPTX export request."""

    document_id: UUID = Field(..., description="Document UUID to export")
    template_id: UUID | None = Field(None, description="Optional template UUID to use")
    title: str | None = Field(None, description="Optional export title override")
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional variables for placeholder substitution",
    )


class ProjectPackageExportRequest(BaseModel):
    """Schema for project-level delivery package exports."""

    project_id: UUID = Field(..., description="Project UUID to package")
    document_ids: list[UUID] | None = Field(
        None,
        description="Optional explicit document UUIDs to include",
    )
    title: str | None = Field(None, description="Optional export title override")
    include_drafts: bool = Field(
        False,
        description="Include draft/review documents when document_ids is omitted",
    )
    include_manifest: bool = Field(
        True,
        description="Prepend a package manifest with document metadata",
    )
    formats: list[str] = Field(
        default_factory=lambda: ["markdown"],
        description="Package artifact formats to generate: markdown, word, pptx",
    )
    include_audit: bool = Field(
        False,
        description="Include an audit checklist in generated package artifacts",
    )
    watermark: str | None = Field(
        None,
        description="Optional visible watermark or distribution label",
    )
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional variables for placeholder substitution",
    )


# Export Response Schemas
class ExportJobCreatedResponse(BaseModel):
    """Schema for export job creation response."""

    job_id: UUID = Field(..., description="Export job UUID")
    status: str = Field(..., description="Initial job status")
    message: str = Field(..., description="Status message")


class ExportStatusResponse(BaseModel):
    """Schema for export status check response."""

    job_id: UUID
    status: str
    progress_percent: int = Field(..., description="Progress percentage (0-100)")
    message: str | None = Field(None, description="Status message or error")
    completed_at: datetime | None = Field(None, description="Completion timestamp")


class ExportArtifactDownloadResponse(BaseModel):
    """Schema for artifact download response."""

    artifact_id: UUID
    filename: str
    content_type: str
    file_size: int
    download_url: str | None = Field(None, description="Pre-signed download URL if applicable")


class ExportReadinessDocumentBlocker(BaseModel):
    """Document-level blocker preventing production-grade package release."""

    document_id: UUID
    title: str
    doc_type: str
    status: str
    reason: str
    recommended_action: str


class ExportReadinessRequiredType(BaseModel):
    """Readiness state for a required consulting delivery document type."""

    doc_type: str
    label: str
    ready_count: int
    blocked_count: int
    status: str


class ExportReadinessResponse(BaseModel):
    """Project export readiness summary for the delivery room."""

    project_id: UUID
    total_documents: int
    exportable_documents: int
    blocked_documents: int
    readiness_score: int
    can_export_production: bool
    missing_required_types: list[str] = Field(default_factory=list)
    required_types: list[ExportReadinessRequiredType] = Field(default_factory=list)
    blockers: list[ExportReadinessDocumentBlocker] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class ExportReleaseEvidenceSummary(BaseModel):
    """Project release evidence summary derived from export jobs and artifacts."""

    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    artifact_count: int
    covered_formats: list[str] = Field(default_factory=list)
    missing_formats: list[str] = Field(default_factory=list)
    production_package_jobs: int
    latest_completed_at: datetime | None = None


class ExportReleaseGate(BaseModel):
    """Release gate for production delivery package evidence."""

    status: str
    label: str
    summary: str
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExportReleaseRiskItem(BaseModel):
    """Actionable export release risk."""

    code: str
    severity: str
    title: str
    detail: str
    count: int
    href: str


class ExportReleasePriorityAction(BaseModel):
    """Next action for export release closeout."""

    code: str
    title: str
    description: str
    href: str
    priority: str


class ExportReleaseEvidenceResponse(BaseModel):
    """Backend-authoritative release evidence cockpit for project exports."""

    project_id: UUID
    release_gate: ExportReleaseGate
    readiness: ExportReadinessResponse
    summary: ExportReleaseEvidenceSummary
    latest_job: ExportJobWithArtifactsResponse | None = None
    recent_artifacts: list[ExportArtifactResponse] = Field(default_factory=list)
    risk_items: list[ExportReleaseRiskItem] = Field(default_factory=list)
    priority_actions: list[ExportReleasePriorityAction] = Field(default_factory=list)


# Export Statistics
class ExportStatistics(BaseModel):
    """Schema for export statistics."""

    total_jobs: int
    by_status: dict[str, int]
    by_type: dict[str, int]
    average_processing_time_seconds: float | None
