"""Document Domain Schemas

Pydantic v2 schemas for request/response validation in the document platform.
"""

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.documents.models import DocumentStatus, DocumentType, QualityType


# Generic type for paginated responses
T = TypeVar("T")


class PaginationParams(BaseModel):
    """Pagination parameters for list endpoints."""

    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response schema."""

    items: list[T]
    total: int
    page: int
    page_size: int
    has_more: bool


# Document Schemas
class DocumentBase(BaseModel):
    """Base document schema."""

    project_id: UUID
    doc_type: str = Field(..., description="Document type (urs, brd, prd, etc.)")
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(default="", description="Document content")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata")


class DocumentCreate(DocumentBase):
    """Schema for creating a document."""

    parent_document_id: UUID | None = Field(None, description="Parent document ID for linking")
    created_by: UUID | None = Field(None, description="User ID of creator")


class DocumentUpdate(BaseModel):
    """Schema for updating a document."""

    title: str | None = Field(None, min_length=1, max_length=500)
    content: str | None = Field(None)
    status: str | None = Field(
        None,
        description="Document status (draft, review, approved, published, archived)",
    )
    metadata: dict[str, Any] | None = None


class DocumentStatusUpdate(BaseModel):
    """Schema for updating document status."""

    status: str = Field(
        ...,
        description=(
            "New status (draft, writing, pending_review, review, in_review, "
            "revision_required, approved, published, archived)"
        ),
    )
    approved_by: UUID | None = Field(None, description="User ID who approved (if applicable)")
    reason: str | None = Field(None, max_length=1000, description="Reason for the status change")
    action: str | None = Field(None, max_length=100, description="Workflow action that triggered the change")


class DocumentStatusTransitionResponse(BaseModel):
    """Schema for document status transition history."""

    transition_id: str | None = None
    from_status: str
    to_status: str
    action: str
    reason: str | None = None
    changed_by: UUID | str | None = None
    changed_at: datetime
    unresolved_comment_count: int = 0
    policy_revision: int = 1


class DocumentStatusCapability(BaseModel):
    """Authorization and workflow readiness for one target status."""

    status: str
    label: str
    permission_action: str
    allowed: bool
    authorization_reason: str
    blockers: list[str] = Field(default_factory=list)


class DocumentStatusCapabilitiesResponse(BaseModel):
    """All status transition capabilities visible to the current user."""

    current_status: str
    policy_revision: int = 1
    capabilities: list[DocumentStatusCapability]


class DocumentResponse(DocumentBase):
    """Schema for document response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    doc_type: str
    status: str
    version: int
    parent_document_id: UUID | None
    created_by: UUID
    approved_by: UUID | None
    quality_score: float | None
    metadata: dict[str, Any] | None = Field(None, validation_alias="metadata_json")
    metadata_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class DocumentListResponse(PaginatedResponse[DocumentResponse]):
    """Schema for paginated document list response."""

    pass


# Document Entity Schemas
class DocumentEntityBase(BaseModel):
    """Base document entity schema."""

    entity_type: str = Field(..., description="Entity type (heading, paragraph, table, list, item)")
    content: str = Field(..., description="Entity content")
    position: int = Field(default=0, description="Position in document")


class DocumentEntityCreate(DocumentEntityBase):
    """Schema for creating a document entity."""

    document_id: UUID
    parent_entity_id: UUID | None = Field(None, description="Parent entity ID for nested entities")
    metadata: dict[str, Any] | None = None


class DocumentEntityUpdate(BaseModel):
    """Schema for updating a document entity."""

    entity_type: str | None = None
    content: str | None = None
    position: int | None = None
    parent_entity_id: UUID | None = None
    metadata: dict[str, Any] | None = None


class DocumentEntityResponse(DocumentEntityBase):
    """Schema for document entity response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    document_id: UUID
    parent_entity_id: UUID | None
    metadata_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


# Document Version Schemas
class DocumentVersionCreate(BaseModel):
    """Schema for creating a document version."""

    content: str = Field(..., description="Version content snapshot")
    changes_summary: str | None = Field(None, description="Summary of changes in this version")


class DocumentVersionResponse(BaseModel):
    """Schema for document version response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    document_id: UUID
    version: int
    content: str
    changes_summary: str | None
    created_by: UUID
    created_at: datetime


class DocumentVersionListResponse(PaginatedResponse[DocumentVersionResponse]):
    """Schema for paginated document version list response."""

    pass


# Document Baseline Schemas
class DocumentBaselineCreate(BaseModel):
    """Schema for creating a document baseline."""

    version_id: UUID = Field(..., description="Version ID to baseline")
    baseline_name: str = Field(..., min_length=1, max_length=255)
    baseline_reason: str | None = Field(None, description="Reason for creating baseline")
    approved_by: UUID | None = Field(None, description="User ID who approved")


class DocumentBaselineResponse(BaseModel):
    """Schema for document baseline response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    document_id: UUID
    version_id: UUID
    baseline_name: str
    baseline_reason: str | None
    approved_by: UUID | None
    approved_at: datetime | None
    created_at: datetime


class DocumentBaselineListResponse(PaginatedResponse[DocumentBaselineResponse]):
    """Schema for paginated document baseline list response."""

    pass


# Quality Result Schemas
class QualityResultResponse(BaseModel):
    """Schema for quality result response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    document_id: UUID
    version_id: UUID | None
    quality_type: str
    score: float
    issues_json: dict[str, Any] | None
    checked_at: datetime
    created_at: datetime


class QualityCheckRequest(BaseModel):
    """Schema for requesting a quality check."""

    quality_type: str = Field(
        ...,
        description="Quality check type (consistency, completeness, mece, citation)",
    )
    version_id: UUID | None = Field(None, description="Specific version to check (defaults to latest)")


# Document Generation Schemas
class DocumentGenerateRequest(BaseModel):
    """Schema for requesting document generation."""

    doc_type: str = Field(
        ...,
        description="Document type to generate (urs, brd, prd, user_story, detailed_design, interface, data_dictionary, test_case)",
    )
    project_id: UUID = Field(..., description="Project ID to generate document for")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Context for generation including existing documents, requirements, etc.",
    )
    title: str | None = Field(None, description="Optional title override")
    template_id: UUID | None = Field(None, description="Optional template ID to use")


class DocumentGenerateResponse(BaseModel):
    """Schema for document generation response."""

    document_id: UUID = Field(..., description="Generated document ID")
    doc_type: str
    title: str
    content: str
    status: str
    version: int
    generated_at: datetime


class DocumentGenerationSessionCreate(BaseModel):
    """Start an interactive document generation session."""

    doc_type: str = Field(..., description="Document type to generate interactively")
    project_id: UUID = Field(..., description="Project ID")
    title: str | None = Field(None, description="Optional title override")
    template_id: UUID | None = Field(None, description="Optional template ID")
    context: dict[str, Any] = Field(default_factory=dict)


class DocumentGenerationMessageRequest(BaseModel):
    """Continue an interactive generation session with one user turn."""

    message: str = Field(default="", description="User message")
    action: str = Field(default="answer", description="answer, confirm, skip, revise")


class DocumentGenerationSectionResponse(BaseModel):
    """Interactive generation section response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    session_id: UUID
    section_key: str
    title: str
    position: int
    status: str
    prompt: str
    content_requirement: str
    content: str
    pending_questions_json: list[str]
    confirmed_facts_json: list[str]
    quality_json: dict[str, Any]
    required_inputs: list[str]
    quality_rules: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class DocumentGenerationStepResponse(BaseModel):
    """Interactive generation step response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    session_id: UUID
    step_index: int
    role: str
    action_type: str
    section_key: str | None
    message: str
    patch_json: dict[str, Any]
    quality_json: dict[str, Any]
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class DocumentGenerationSessionResponse(BaseModel):
    """Interactive generation session response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID
    document_id: UUID | None
    template_id: UUID | None
    doc_type: str
    title: str
    status: str
    generation_mode: str
    current_section_key: str | None
    context_json: dict[str, Any]
    stash_json: dict[str, Any]
    quality_summary_json: dict[str, Any]
    created_by: UUID
    finalized_at: datetime | None
    created_at: datetime
    updated_at: datetime
    sections: list[DocumentGenerationSectionResponse] = Field(default_factory=list)
    steps: list[DocumentGenerationStepResponse] = Field(default_factory=list)


class DocumentGenerationTurnResponse(BaseModel):
    """Response after one interactive generation turn."""

    session: DocumentGenerationSessionResponse
    current_section: DocumentGenerationSectionResponse
    assistant_message: str
    section_summaries: list[dict[str, Any]]
    write_log: list[dict[str, Any]] = Field(default_factory=list)
    skill_trace: list[dict[str, Any]] = Field(default_factory=list)
    quality_gate: dict[str, Any] = Field(default_factory=dict)
    pending_confirmations: list[dict[str, Any]] = Field(default_factory=list)


# Document Statistics
class DocumentStatistics(BaseModel):
    """Schema for document statistics."""

    total_documents: int
    by_type: dict[str, int]
    by_status: dict[str, int]
    average_quality_score: float | None


# Document Content Extraction
class DocumentContentExtraction(BaseModel):
    """Schema for extracted document content."""

    doc_type: str
    schema_version: str
    extracted_data: dict[str, Any]
    validation_errors: list[str] | None = None
