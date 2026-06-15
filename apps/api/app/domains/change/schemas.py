"""Change Domain Schemas

Pydantic v2 schemas for request/response validation.
"""

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# Generic type for paginated responses
T = TypeVar("T")


# =============================================================================
# Change Request Schemas
# =============================================================================


class ChangeRequestBase(BaseModel):
    """Base change request schema."""

    project_id: UUID
    source_document_id: UUID | None = None
    target_document_id: UUID | None = None
    change_type: str = Field(..., description="Change type (correction/enhancement/dependency)")
    priority: str = Field(default="medium", description="Priority (critical/high/medium/low)")
    description: str = Field(..., description="Description of the change")
    rationale: str | None = None
    impact_analysis: str | None = None
    risk_assessment: str | None = None


class ChangeRequestCreate(ChangeRequestBase):
    """Schema for creating a change request."""

    requested_by: UUID | None = None


class ChangeRequestUpdate(BaseModel):
    """Schema for updating a change request."""

    change_type: str | None = None
    priority: str | None = None
    description: str | None = None
    rationale: str | None = None
    impact_analysis: str | None = None
    risk_assessment: str | None = None


class ChangeRequestResponse(ChangeRequestBase):
    """Schema for change request response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    source_document_version: int | None
    target_document_version: int | None
    status: str
    requested_by: UUID
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    applied_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChangeRequestListResponse(BaseModel):
    """Schema for paginated change request list response."""

    items: list[ChangeRequestResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class ChangeRequestApproval(BaseModel):
    """Schema for approving a change request."""

    pass


class ChangeRequestRejection(BaseModel):
    """Schema for rejecting a change request."""

    reason: str = Field(..., description="Reason for rejection")


# =============================================================================
# Field Patch Schemas
# =============================================================================


class FieldPatchBase(BaseModel):
    """Base field patch schema."""

    document_id: UUID
    field_path: str = Field(..., description="Field path (e.g., 'sections.0.content')")
    old_value: str | None = None
    new_value: str | None = None
    patch_type: str = Field(default="replace", description="Patch type (replace/add/remove)")


class FieldPatchCreate(FieldPatchBase):
    """Schema for creating a field patch."""

    pass


class FieldPatchUpdate(BaseModel):
    """Schema for updating a field patch."""

    field_path: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    patch_type: str | None = None


class FieldPatchResponse(FieldPatchBase):
    """Schema for field patch response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    change_request_id: UUID
    document_version: int
    status: str
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FieldPatchApproval(BaseModel):
    """Schema for approving a field patch."""

    pass


class FieldPatchRejection(BaseModel):
    """Schema for rejecting a field patch."""

    reason: str = Field(..., description="Reason for rejection")


# =============================================================================
# Comment Schemas
# =============================================================================


class ChangeRequestCommentCreate(BaseModel):
    """Schema for creating a comment."""

    content: str = Field(..., description="Comment content")


class ChangeRequestCommentResponse(BaseModel):
    """Schema for comment response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    change_request_id: UUID
    user_id: UUID
    content: str
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Traceability Schemas
# =============================================================================


class TraceabilityMatrixRequest(BaseModel):
    """Schema for requesting traceability matrix."""

    project_id: UUID
    doc_type: str | None = Field(None, description="Filter by document type")


class TraceabilityMatrixItem(BaseModel):
    """Single item in traceability matrix."""

    requirement_id: str
    requirement_title: str
    document_type: str
    document_id: UUID
    document_version: int
    status: str
    linked_requirements: list[str]


class TraceabilityMatrixResponse(BaseModel):
    """Schema for traceability matrix response."""

    items: list[TraceabilityMatrixItem]
    total: int


class ImpactAnalysisRequest(BaseModel):
    """Schema for requesting impact analysis."""

    document_id: UUID


class ImpactAnalysisItem(BaseModel):
    """Single item in impact analysis."""

    document_id: UUID
    document_type: str
    title: str
    version: int
    status: str
    link_type: str = Field(..., description="Type of link (upstream/downstream)")


class ImpactAnalysisResponse(BaseModel):
    """Schema for impact analysis response."""

    document_id: UUID
    upstream_documents: list[ImpactAnalysisItem]
    downstream_documents: list[ImpactAnalysisItem]


class TraceabilityCoverageSummary(BaseModel):
    """Project-level formal traceability coverage summary."""

    total_documents: int
    published_documents: int
    referenced_documents: int
    orphan_documents: int
    coverage_rate: float
    open_impact_analyses: int
    pending_sync_proposals: int


class TraceabilityGapItem(BaseModel):
    """A traceability coverage gap with a user-actionable recommendation."""

    code: str
    severity: str
    document_id: UUID
    document_title: str
    document_type: str
    reason: str
    suggested_action: str
    related_document_id: UUID | None = None
    related_document_title: str | None = None
    related_document_type: str | None = None


class TraceabilityReferenceSuggestion(BaseModel):
    """Recommended same-project reference that can be created by the user."""

    id: str
    source_document_id: UUID
    source_document_title: str
    source_document_type: str
    target_document_id: UUID
    target_document_title: str
    target_document_type: str
    reference_type: str
    reason: str
    suggested_action: str


class TraceabilityCoverageResponse(BaseModel):
    """Project-level coverage cockpit payload."""

    summary: TraceabilityCoverageSummary
    gaps: list[TraceabilityGapItem]
    suggestions: list[TraceabilityReferenceSuggestion]


class ChangeAuditCommandCenterSummary(BaseModel):
    """Tenant or project level change-audit readiness summary."""

    total_changes: int
    draft_changes: int
    open_changes: int
    approved_unapplied_changes: int
    critical_or_high_open_changes: int
    pending_field_patches: int
    open_impact_analyses: int
    critical_or_high_open_impacts: int
    pending_sync_proposals: int


class ChangeAuditReleaseGate(BaseModel):
    """Release gate derived from change, traceability, and patch risks."""

    status: str
    label: str
    summary: str
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ChangeAuditRiskItem(BaseModel):
    """Actionable risk surfaced in the change-audit command center."""

    code: str
    severity: str
    title: str
    detail: str
    count: int
    href: str


class ChangeAuditPriorityAction(BaseModel):
    """Next action shown to operators before release."""

    code: str
    title: str
    description: str
    href: str
    priority: str


class ChangeAuditCommandCenterResponse(BaseModel):
    """Aggregated change-audit command center payload."""

    scope: str
    project_id: UUID | None = None
    release_gate: ChangeAuditReleaseGate
    summary: ChangeAuditCommandCenterSummary
    change_status_counts: dict[str, int]
    priority_counts: dict[str, int]
    impact_level_counts: dict[str, int]
    risk_items: list[ChangeAuditRiskItem]
    priority_actions: list[ChangeAuditPriorityAction]


class TraceabilitySuggestionAcceptanceRequest(BaseModel):
    """Accept one or more generated traceability reference suggestions."""

    suggestion_ids: list[str] | None = None


class TraceabilitySuggestionAcceptanceItem(BaseModel):
    """Result for one accepted or skipped reference suggestion."""

    suggestion_id: str
    source_document_id: UUID
    target_document_id: UUID
    reference_type: str
    status: str
    reference_id: UUID | None = None
    reason: str | None = None


class TraceabilitySuggestionAcceptanceResponse(BaseModel):
    """Batch result for accepting traceability suggestions."""

    created: int
    skipped: int
    items: list[TraceabilitySuggestionAcceptanceItem]


# =============================================================================
# Extended Traceability Schemas
# =============================================================================


class DocumentTraceabilityItem(BaseModel):
    """Single document in traceability lineage."""

    id: UUID
    title: str
    doc_type: str
    version: int
    status: str


class DocumentTraceabilityResponse(BaseModel):
    """Full traceability lineage for a document."""

    document: DocumentTraceabilityItem
    ancestors: list[DocumentTraceabilityItem] = Field(default_factory=list)
    descendants: list[DocumentTraceabilityItem] = Field(default_factory=list)
    linked_documents: list[DocumentTraceabilityItem] = Field(default_factory=list)


class ConflictItem(BaseModel):
    """Represents a conflict between document versions."""

    document_id: UUID
    document_title: str
    version_1: int
    version_2: int
    conflict_type: str = Field(..., description="Type of conflict (content/inconsistent_link/missing_parent)")
    description: str
    affected_entities: list[str] = Field(default_factory=list)
    rule_key: str | None = None
    severity: str = "medium"
    related_document_id: UUID | None = None
    related_document_version: int | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class ConflictAnalysisResponse(BaseModel):
    """Response for conflict analysis."""

    document_id: UUID
    conflicts: list[ConflictItem]


class DocumentConflictResponse(BaseModel):
    """Persisted conflict response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID
    rule_key: str
    fingerprint: str
    severity: str
    status: str
    primary_document_id: UUID
    primary_document_version: int
    related_document_id: UUID | None
    related_document_version: int | None
    summary: str
    evidence_json: dict[str, Any]
    first_detected_at: datetime
    last_detected_at: datetime
    last_scan_id: UUID
    absent_since: datetime | None
    closed_at: datetime | None
    assignee_user_id: UUID | None = None
    assignment_source: str | None = None
    assigned_at: datetime | None = None
    due_at: datetime | None = None
    linked_change_request_id: UUID | None = None
    accepted_revision_json: dict[str, Any] | None = None
    revision_accepted_at: datetime | None = None
    closure_scan_id: UUID | None = None
    closure_verified_at: datetime | None = None
    closure_evidence_json: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class DocumentConflictDecisionResponse(BaseModel):
    """Append-only conflict governance decision response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID
    conflict_id: UUID
    actor_id: UUID
    action: str
    previous_status: str | None
    resulting_status: str
    reason: str | None
    evidence_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ConflictAssignmentRequest(BaseModel):
    """Assign or reassign a persisted conflict."""

    assignee_user_id: UUID
    reason: str = Field(..., min_length=1)


class ConflictAnalysisCompletionRequest(BaseModel):
    """Move a conflict from analysis to decision."""

    reason: str = Field(..., min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)


class ConflictRejectionRequest(BaseModel):
    """Reject an inapplicable or false conflict finding."""

    reason: str = Field(..., min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)


class ConflictRevisionAcceptanceRequest(BaseModel):
    """Accept a suggested revision and create a linked change-request draft."""

    suggested_revision: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)


class ConflictClosureRequest(BaseModel):
    """Close a conflict after the linked change is applied and a rescan verifies absence."""

    reason: str = Field(..., min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)


class DocumentConflictListResponse(BaseModel):
    """Project conflict list response."""

    items: list[DocumentConflictResponse]
    total: int


class ConflictScanResponse(BaseModel):
    """Project conflict scan result."""

    scan_id: UUID
    project_id: UUID
    detected: int
    created: int
    refreshed: int
    reopened: int
    marked_absent: int
    items: list[DocumentConflictResponse]


class FullTraceabilityMatrixResponse(BaseModel):
    """Full traceability matrix with hierarchical structure."""

    urs: list[TraceabilityMatrixItem] = Field(default_factory=list)
    brd: list[TraceabilityMatrixItem] = Field(default_factory=list)
    prd: list[TraceabilityMatrixItem] = Field(default_factory=list)
    stories: list[TraceabilityMatrixItem] = Field(default_factory=list)
    tests: list[TraceabilityMatrixItem] = Field(default_factory=list)
    total: int


class ChangeRequestWithImpactResponse(BaseModel):
    """Change request with impact analysis."""

    change_request: ChangeRequestResponse
    impact_analysis: ImpactAnalysisResponse


# =============================================================================
# Persistent Traceability / Impact Workflow Schemas
# =============================================================================


class DocumentReferenceCreate(BaseModel):
    """Create a formal version-pinned reference from a source document."""

    target_document_id: UUID
    reference_type: str = Field(default="derives_from")
    source_section: str | None = None
    target_section: str | None = None
    metadata: dict[str, Any] | None = None


class DocumentReferenceResponse(BaseModel):
    """Formal document reference response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID
    source_document_id: UUID
    source_document_version: int
    target_document_id: UUID
    target_document_version: int
    reference_type: str
    source_section: str | None
    target_section: str | None
    status: str
    created_by: UUID
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DocumentReferenceListResponse(BaseModel):
    """List response for formal document references."""

    items: list[DocumentReferenceResponse]
    total: int


class DocumentImpactAnalysisCreate(BaseModel):
    """Request to create impact analysis for a document change trigger."""

    trigger_type: str = Field(default="content_changed")
    summary: str | None = None
    change_request_id: UUID | None = None


class DocumentSyncProposalResponse(BaseModel):
    """Human-reviewed downstream sync proposal."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    impact_analysis_id: UUID
    project_id: UUID
    reference_id: UUID | None
    source_document_id: UUID
    target_document_id: UUID
    target_document_version: int
    result_document_version: int | None
    target_section: str | None
    impact_level: str
    reason: str
    suggested_action: str
    candidate_content: str | None
    status: str
    decided_by: UUID | None
    decided_at: datetime | None
    decision_note: str | None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DocumentImpactAnalysisResponse(BaseModel):
    """Persisted impact analysis with sync proposals."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID
    trigger_document_id: UUID
    trigger_document_version: int
    change_request_id: UUID | None
    trigger_type: str
    impact_level: str
    status: str
    summary: str | None
    analysis_json: dict[str, Any]
    created_by: UUID
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    proposals: list[DocumentSyncProposalResponse] = Field(default_factory=list)


class SyncProposalDecision(BaseModel):
    """Apply or reject a sync proposal."""

    decision_note: str | None = None
    candidate_content: str | None = None


# =============================================================================
# Pagination
# =============================================================================


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
