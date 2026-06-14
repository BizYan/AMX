"""Project Domain Schemas

Pydantic v2 schemas for request/response validation.
"""

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


# Project Schemas
class ProjectBase(BaseModel):
    """Base project schema."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    slug: str = Field(..., min_length=1, max_length=100)
    status: Literal["active", "archived"] | None = "active"


class ProjectCreate(ProjectBase):
    """Schema for creating a project."""

    pass


class ProjectUpdate(BaseModel):
    """Schema for updating a project."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    slug: str | None = Field(None, min_length=1, max_length=100)
    status: Literal["active", "archived"] | None = None



class ProjectResponse(ProjectBase):
    """Schema for project response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    owner_id: UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ProjectLaunchBlueprint(BaseModel):
    """Platform-maintained project launch blueprint."""

    key: str
    name: str
    description: str
    scenarios: list[str] = Field(default_factory=list)
    document_types: list[str] = Field(default_factory=list)
    workflow_template_ids: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class ProjectLaunchCreate(BaseModel):
    """Configuration for creating and initializing a project."""

    blueprint_key: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    slug: str = Field(..., min_length=1, max_length=100)
    member_ids: list[UUID] = Field(default_factory=list)
    document_types: list[str] | None = None
    workflow_template_ids: list[str] | None = None


class ProjectLaunchPlanResponse(BaseModel):
    """Persistent project launch status and execution evidence."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID
    blueprint_key: str
    status: str
    config_json: dict[str, Any]
    checks_json: list[dict[str, Any]]
    results_json: dict[str, Any]
    error_message: str | None
    attempt_count: int
    created_by: UUID
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProjectLaunchResponse(BaseModel):
    """Project and its launch plan."""

    project: ProjectResponse
    plan: ProjectLaunchPlanResponse


class ProjectMilestoneCreate(BaseModel):
    """Owner-managed project milestone input."""

    key: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    owner_id: UUID | None = None
    priority: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    planned_start_at: datetime | None = None
    due_at: datetime | None = None
    required_document_types: list[str] = Field(default_factory=list)
    required_workflow_template_ids: list[str] = Field(default_factory=list)


class ProjectMilestoneUpdate(BaseModel):
    """Editable milestone fields."""

    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=4000)
    owner_id: UUID | None = None
    priority: str | None = Field(None, pattern="^(low|medium|high|critical)$")
    planned_start_at: datetime | None = None
    due_at: datetime | None = None
    required_document_types: list[str] | None = None
    required_workflow_template_ids: list[str] | None = None


class ProjectMilestoneReorder(BaseModel):
    """Ordered milestone IDs."""

    milestone_ids: list[UUID] = Field(..., min_length=1)


class ProjectMilestoneResponse(BaseModel):
    """Milestone with latest gate evidence."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID
    plan_id: UUID
    owner_id: UUID | None
    key: str
    title: str
    description: str
    status: str
    priority: str
    order_index: int
    planned_start_at: datetime | None
    due_at: datetime | None
    completed_at: datetime | None
    required_document_types_json: list[str]
    required_workflow_template_ids_json: list[str]
    gate_results_json: list[dict[str, Any]]
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ProjectDeliveryPlanSummary(BaseModel):
    """Computed project delivery plan progress."""

    total_count: int
    completed_count: int
    blocked_count: int
    overdue_count: int
    progress_percent: int
    next_milestone_id: UUID | None = None
    blockers: list[str] = Field(default_factory=list)


class ProjectDeliveryPlanResponse(BaseModel):
    """Project delivery plan and ordered milestones."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID
    blueprint_key: str
    status: str
    summary_json: dict[str, Any]
    settings_json: dict[str, Any]
    created_by: UUID
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    milestones: list[ProjectMilestoneResponse]
    summary: ProjectDeliveryPlanSummary | None = None


class ProjectAcceptanceItem(BaseModel):
    """One customer acceptance criterion and its evidence."""

    key: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=255)
    status: str = Field(default="pending", pattern="^(pending|accepted|rejected)$")
    evidence: str = Field(default="", max_length=4000)


class ProjectAcceptanceUpdate(BaseModel):
    """Owner-managed customer acceptance record."""

    customer_name: str = Field(default="", max_length=255)
    contact_name: str = Field(default="", max_length=255)
    contact_email: str = Field(default="", max_length=255)
    decision: str = Field(
        default="pending",
        pattern="^(pending|accepted|accepted_with_followups|rejected)$",
    )
    notes: str = Field(default="", max_length=8000)
    items: list[ProjectAcceptanceItem] = Field(default_factory=list)


class ProjectAcceptanceGate(BaseModel):
    """Formal delivery closure gate."""

    status: str
    label: str
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CustomerAcceptanceFollowUp(BaseModel):
    """Safe status of a collaboration task created from an acceptance criterion."""

    key: str
    title: str
    status: str
    priority: str
    updated_at: datetime


class ProjectAcceptanceResponse(ProjectAcceptanceUpdate):
    """Customer acceptance record with formal delivery gate evidence."""

    project_id: UUID
    updated_by: UUID | None = None
    accepted_at: datetime | None = None
    closed_at: datetime | None = None
    package_ready: bool = False
    gate: ProjectAcceptanceGate
    follow_ups: list[CustomerAcceptanceFollowUp] = Field(default_factory=list)


class CustomerPortalLinkCreate(BaseModel):
    """Create a one-time visible customer delivery portal link."""

    label: str = Field(default="客户验收门户", min_length=1, max_length=255)
    customer_email: str = Field(..., min_length=3, max_length=255)
    expires_in_days: int = Field(default=14, ge=1, le=90)


class CustomerPortalLinkResponse(BaseModel):
    """Safe persisted representation of a customer portal link."""

    id: UUID
    label: str
    customer_email: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    last_accessed_at: datetime | None = None
    submitted_at: datetime | None = None
    last_downloaded_at: datetime | None = None
    download_count: int = 0
    receipt_id: UUID | None = None


class CustomerPortalLinkCreatedResponse(CustomerPortalLinkResponse):
    """Portal link creation response containing the raw token once."""

    token: str
    portal_path: str


class CustomerPortalAcceptanceSubmit(BaseModel):
    """Customer-submitted acceptance decision through the scoped portal."""

    contact_name: str = Field(..., min_length=1, max_length=255)
    contact_email: str = Field(..., min_length=3, max_length=255)
    decision: str = Field(
        ..., pattern="^(accepted|accepted_with_followups|rejected)$"
    )
    notes: str = Field(default="", max_length=8000)
    items: list[ProjectAcceptanceItem] = Field(default_factory=list)


class CustomerPortalArtifact(BaseModel):
    """Safe downloadable project-package artifact metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    content_type: str
    file_size: int
    file_hash: str | None = None
    created_at: datetime


class CustomerPortalReceipt(BaseModel):
    """Durable receipt for a customer acceptance submission."""

    id: UUID
    contact_name: str
    contact_email: str
    decision: str
    submitted_at: datetime
    item_count: int
    accepted_item_count: int


class CustomerPortalSummaryResponse(BaseModel):
    """Public, token-scoped delivery and acceptance summary."""

    project_name: str
    customer_name: str
    package_ready: bool
    decision: str
    accepted_at: datetime | None = None
    submitted_at: datetime | None = None
    criteria: list[ProjectAcceptanceItem] = Field(default_factory=list)
    artifacts: list[CustomerPortalArtifact] = Field(default_factory=list)
    receipt: CustomerPortalReceipt | None = None
    follow_ups: list[CustomerAcceptanceFollowUp] = Field(default_factory=list)
    gate: ProjectAcceptanceGate


class ProjectListResponse(PaginatedResponse[ProjectResponse]):
    """Schema for paginated project list response."""

    pass


class ProjectDeliveryDocumentItem(BaseModel):
    """Compact document item used by project delivery cockpit."""

    id: UUID
    title: str
    doc_type: str
    status: str
    version: int
    updated_at: datetime


class ProjectDeliveryChainItem(BaseModel):
    """Delivery-chain slot for one expected project document type."""

    doc_type: str
    label: str
    document_id: UUID | None = None
    title: str | None = None
    status: str
    version: int | None = None
    updated_at: datetime | None = None
    missing: bool
    completion_ratio: float = 0
    quality_level: str | None = None
    upstream_dependencies: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    action_href: str | None = None


class ProjectDeliverySessionItem(BaseModel):
    """Active conversational document authoring session."""

    id: UUID
    doc_type: str
    title: str
    status: str
    current_section_key: str | None = None
    confirmed_sections: int = 0
    section_count: int = 0
    updated_at: datetime


class ProjectDeliveryReadiness(BaseModel):
    """Aggregated review and export readiness."""

    ready: bool
    export_ready: bool
    review_ready: bool
    blockers: list[str] = Field(default_factory=list)


class ProjectDeliveryRisk(BaseModel):
    """Actionable project delivery risk."""

    code: str
    severity: str
    title: str
    description: str
    target_href: str


class ProjectDeliveryNextAction(BaseModel):
    """Recommended next project action."""

    code: str
    label: str
    description: str
    href: str
    priority: str


class ProjectDocumentWorkflowLane(BaseModel):
    """Operational lane for project document delivery."""

    key: str
    label: str
    count: int
    attention_count: int = 0
    document_ids: list[UUID] = Field(default_factory=list)
    href: str


class ProjectDocumentQualityGate(BaseModel):
    """Project-level quality gate for document delivery."""

    key: str
    label: str
    status: str
    score: int = Field(ge=0, le=100)
    message: str
    target_href: str


class ProjectDocumentTemplateCoverage(BaseModel):
    """Template and section coverage for one expected document type."""

    doc_type: str
    label: str
    template_available: bool
    active_template_count: int = 0
    section_count: int = 0
    skill_binding_count: int = 0
    action_href: str


class ProjectDocumentExportPackage(BaseModel):
    """Project document export-package readiness."""

    ready: bool
    required_document_count: int
    completed_document_count: int
    approved_or_published_count: int
    latest_job_id: UUID | None = None
    latest_job_status: str | None = None
    blockers: list[str] = Field(default_factory=list)
    action_href: str


class ProjectDocumentCollaborationSummary(BaseModel):
    """Collaboration status for project document work."""

    member_count: int
    unresolved_comment_count: int
    review_queue_count: int
    active_session_count: int
    open_change_count: int
    action_href: str


class ProjectDocumentPackageManifestItem(BaseModel):
    """One document slot in the project delivery package manifest."""

    doc_type: str
    label: str
    required: bool = True
    included: bool
    release_ready: bool
    document_id: UUID | None = None
    title: str | None = None
    status: str
    version: int | None = None
    export_order: int
    blockers: list[str] = Field(default_factory=list)
    action_href: str


class ProjectDocumentTraceabilityAction(BaseModel):
    """Actionable traceability repair or review item."""

    code: str
    status: str
    source_document_id: UUID | None = None
    source_title: str | None = None
    source_doc_type: str | None = None
    target_document_id: UUID | None = None
    target_title: str | None = None
    target_doc_type: str | None = None
    reference_type: str = "derives_from"
    reason: str
    action_href: str


class ProjectDocumentCollaborationAction(BaseModel):
    """Actionable collaboration item in the project document workbench."""

    code: str
    label: str
    description: str
    count: int = 0
    priority: str
    action_href: str


class ProjectDocumentControlAction(BaseModel):
    """One executable action for a core delivery document."""

    code: str
    label: str
    href: str
    priority: str = "medium"


class ProjectDocumentControlMatrixItem(BaseModel):
    """Per-document control status for final delivery management."""

    doc_type: str
    label: str
    stage: str
    stage_label: str
    document_id: UUID | None = None
    title: str | None = None
    status: str
    version: int | None = None
    completion_ratio: float = 0
    quality_level: str | None = None
    template_ready: bool
    source_ready: bool
    release_ready: bool
    package_included: bool
    upstream_missing: list[str] = Field(default_factory=list)
    traceability_gap_count: int = 0
    blockers: list[str] = Field(default_factory=list)
    primary_action: ProjectDocumentControlAction
    secondary_actions: list[ProjectDocumentControlAction] = Field(default_factory=list)


class ProjectDocumentSourceCoverage(BaseModel):
    """Source and knowledge readiness for project document delivery."""

    status: str
    label: str
    source_file_total: int
    ready_source_file_count: int
    pending_source_file_count: int
    failed_source_file_count: int
    knowledge_entry_count: int
    blockers: list[str] = Field(default_factory=list)
    action_href: str


class ProjectDeliveryTraceabilitySummary(BaseModel):
    """Traceability counts for project delivery readiness."""

    active_references: int
    open_impact_analyses: int
    pending_sync_proposals: int


class ProjectDeliveryWorkbenchResponse(BaseModel):
    """Aggregated project workbench response for delivery readiness."""

    project_id: UUID
    generated_at: datetime
    totals: dict[str, int]
    document_status_counts: dict[str, int]
    document_type_counts: dict[str, int]
    source_file_status_counts: dict[str, int]
    change_status_counts: dict[str, int]
    traceability: ProjectDeliveryTraceabilitySummary
    delivery_chain: list[ProjectDeliveryChainItem]
    review_queue: list[ProjectDeliveryDocumentItem]
    recent_documents: list[ProjectDeliveryDocumentItem]
    risks: list[ProjectDeliveryRisk]
    next_actions: list[ProjectDeliveryNextAction]
    active_sessions: list[ProjectDeliverySessionItem] = Field(default_factory=list)
    readiness: ProjectDeliveryReadiness | None = None
    workflow_lanes: list[ProjectDocumentWorkflowLane] = Field(default_factory=list)
    quality_gates: list[ProjectDocumentQualityGate] = Field(default_factory=list)
    template_coverage: list[ProjectDocumentTemplateCoverage] = Field(default_factory=list)
    export_package: ProjectDocumentExportPackage | None = None
    collaboration_summary: ProjectDocumentCollaborationSummary | None = None
    package_manifest: list[ProjectDocumentPackageManifestItem] = Field(default_factory=list)
    traceability_actions: list[ProjectDocumentTraceabilityAction] = Field(default_factory=list)
    collaboration_actions: list[ProjectDocumentCollaborationAction] = Field(default_factory=list)
    control_matrix: list[ProjectDocumentControlMatrixItem] = Field(default_factory=list)
    source_coverage: ProjectDocumentSourceCoverage | None = None


class SystemDeliveryProjectDigest(BaseModel):
    """One project row in the system-level delivery overview."""

    project_id: UUID
    name: str
    status: str
    updated_at: datetime
    readiness_score: int = Field(ge=0, le=100)
    readiness_label: str
    blocker_count: int = 0
    document_count: int = 0
    source_file_count: int = 0
    knowledge_entry_count: int = 0
    open_change_count: int = 0
    review_queue_count: int = 0
    export_ready: bool = False
    delivery_phase_key: str = "intake"
    delivery_phase_label: str = "资料导入"
    release_gate_status: str = "blocked"
    next_action_label: str
    next_action_href: str
    next_action_priority: str = "medium"


class SystemDeliveryModuleHealth(BaseModel):
    """Aggregated health for one core product module."""

    key: str
    label: str
    status: str
    score: int = Field(ge=0, le=100)
    summary: str
    action_href: str


class SystemDeliveryAction(BaseModel):
    """Cross-project critical action for the main workbench."""

    project_id: UUID
    project_name: str
    code: str
    label: str
    description: str
    href: str
    priority: str


class SystemDeliveryPhaseSummary(BaseModel):
    """Cross-project delivery phase summary."""

    key: str
    label: str
    status: str
    project_count: int = 0
    blocked_project_count: int = 0
    ready_project_count: int = 0
    score: int = Field(ge=0, le=100)
    summary: str
    action_href: str


class SystemDeliveryReleaseGate(BaseModel):
    """System-level release gate for project delivery readiness."""

    key: str
    label: str
    status: str
    passed_count: int = 0
    total_count: int = 0
    score: int = Field(ge=0, le=100)
    blockers: list[str] = Field(default_factory=list)
    action_href: str


class SystemDeliveryOperatingPlanItem(BaseModel):
    """Prioritized operating plan item across projects."""

    project_id: UUID
    project_name: str
    phase_key: str
    phase_label: str
    action_code: str
    action_label: str
    action_description: str
    action_href: str
    priority: str
    status: str


class SystemCompletionCapability(BaseModel):
    """Production closure status for one core product capability."""

    key: str
    label: str
    status: str
    score: int = Field(ge=0, le=100)
    summary: str
    evidence: dict[str, int | str | bool] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    action_label: str
    action_href: str


class SystemCompletionGap(BaseModel):
    """Actionable system-level gap derived from capability closure."""

    key: str
    capability_key: str
    severity: str
    title: str
    detail: str
    action_label: str
    action_href: str


class SystemDeliveryMilestoneDigest(BaseModel):
    """One cross-project milestone requiring portfolio attention."""

    milestone_id: UUID
    project_id: UUID
    project_name: str
    title: str
    status: str
    priority: str
    owner_id: UUID | None = None
    owner_name: str
    due_at: datetime | None = None
    is_overdue: bool = False
    gate_blocker_count: int = 0
    action_href: str


class SystemDeliveryOwnerLoad(BaseModel):
    """Active portfolio responsibility load for one owner."""

    owner_id: UUID | None = None
    owner_name: str
    active_count: int = 0
    blocked_count: int = 0
    overdue_count: int = 0
    project_count: int = 0
    action_href: str


class SystemDeliveryMilestonePortfolio(BaseModel):
    """Cross-project milestone operating view."""

    totals: dict[str, int]
    status_counts: dict[str, int]
    upcoming: list[SystemDeliveryMilestoneDigest] = Field(default_factory=list)
    blocked: list[SystemDeliveryMilestoneDigest] = Field(default_factory=list)
    owner_load: list[SystemDeliveryOwnerLoad] = Field(default_factory=list)


class SystemDeliveryPortfolioResponse(BaseModel):
    """Complete visible cross-project milestone portfolio."""

    generated_at: datetime
    project_count: int = 0
    portfolio: SystemDeliveryMilestonePortfolio


class SystemDeliveryOverviewResponse(BaseModel):
    """System-level command center for core delivery operations."""

    generated_at: datetime
    readiness_score: int = Field(ge=0, le=100)
    totals: dict[str, int]
    module_health: list[SystemDeliveryModuleHealth]
    projects: list[SystemDeliveryProjectDigest]
    critical_actions: list[SystemDeliveryAction]
    phase_summary: list[SystemDeliveryPhaseSummary] = Field(default_factory=list)
    release_gates: list[SystemDeliveryReleaseGate] = Field(default_factory=list)
    operating_plan: list[SystemDeliveryOperatingPlanItem] = Field(default_factory=list)
    completion_capabilities: list[SystemCompletionCapability] = Field(default_factory=list)
    completion_gaps: list[SystemCompletionGap] = Field(default_factory=list)
    completion_score: int = Field(default=0, ge=0, le=100)
    milestone_portfolio: SystemDeliveryMilestonePortfolio


# Project Member Schemas
class ProjectMemberBase(BaseModel):
    """Base project member schema."""

    user_id: UUID
    role_id: UUID | None = None


class ProjectMemberCreate(ProjectMemberBase):
    """Schema for creating a project member."""

    pass


class ProjectMemberUpdate(BaseModel):
    """Schema for updating a project member."""

    role_id: UUID | None = None


class ProjectMemberResponse(ProjectMemberBase):
    """Schema for project member response."""

    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectMemberListResponse(PaginatedResponse[ProjectMemberResponse]):
    """Schema for paginated project member list response."""

    pass


class ProjectInvitationResponse(BaseModel):
    """Owner-facing project invitation lifecycle state."""

    id: UUID
    project_id: UUID
    email: str
    status: Literal["active", "expired", "accepted", "revoked"]
    expires_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    delivery_status: Literal["pending", "sent", "failed"]
    delivery_channel: str | None = None
    delivery_attempt_count: int
    delivery_error: str | None = None
    last_delivery_attempt_at: datetime | None = None
    last_delivered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProjectInvitationListResponse(PaginatedResponse[ProjectInvitationResponse]):
    """Paginated project invitation lifecycle response."""

    pass


class ProjectInvitationCreatedResponse(BaseModel):
    """One-time raw invitation token returned to the project owner."""

    id: UUID
    token: str
    invite_path: str
    expires_at: datetime


class ProjectInvitationDeliveryUpdate(BaseModel):
    """Owner-recorded external invitation delivery evidence."""

    status: Literal["sent", "failed"]
    channel: Literal["manual", "email", "messaging"] = "manual"
    error: str | None = Field(None, max_length=1000)


class ProjectInvitationAcceptResponse(BaseModel):
    """Invitation acceptance result."""

    project_id: UUID
    project_name: str
    user_id: UUID
    status: Literal["accepted"]


class ProjectInvitationPreviewResponse(BaseModel):
    """Public, deliberately limited invitation preview."""

    status: Literal["active", "expired", "accepted", "revoked", "invalid"]
    project_name: str | None = None
    masked_email: str | None = None
    expires_at: datetime | None = None


class ProjectInvitationActivationRequest(BaseModel):
    """Account details supplied by a new invited user."""

    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=100)


class ProjectInvitationActivationResponse(ProjectInvitationAcceptResponse):
    """Invitation acceptance result with the new user's session."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"


# Project Settings Schemas
class ProjectSettingsUpdate(BaseModel):
    """Schema for updating project settings."""

    settings: dict[str, Any] = Field(..., description="Settings key-value pairs")


class ProjectSettingsResponse(BaseModel):
    """Schema for project settings response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    settings_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


DOCUMENT_LIFECYCLE_STATUS_KEYS = {
    "draft",
    "writing",
    "pending_review",
    "review",
    "in_review",
    "revision_required",
    "approved",
    "published",
    "archived",
}


class DocumentLifecycleStatus(BaseModel):
    """One enabled status in a project's document lifecycle."""

    key: str = Field(..., min_length=1, max_length=50)
    label: str = Field(..., min_length=1, max_length=100)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if value not in DOCUMENT_LIFECYCLE_STATUS_KEYS:
            raise ValueError(f"Unknown document lifecycle status: {value}")
        return value


class DocumentLifecycleTransition(BaseModel):
    """One directed transition between enabled project document statuses."""

    from_status: str = Field(..., min_length=1, max_length=50)
    to_status: str = Field(..., min_length=1, max_length=50)


class DocumentLifecyclePublishGates(BaseModel):
    """Project-level publish readiness gates."""

    require_approved: bool = True
    require_resolved_comments: bool = True
    require_resolved_placeholders: bool = True


class DocumentLifecyclePolicyBase(BaseModel):
    """Validated project-level document lifecycle policy."""

    statuses: list[DocumentLifecycleStatus] = Field(..., min_length=2)
    transitions: list[DocumentLifecycleTransition] = Field(..., min_length=1)
    require_reason_for: list[str] = Field(default_factory=list)
    publish_gates: DocumentLifecyclePublishGates = Field(default_factory=DocumentLifecyclePublishGates)

    @model_validator(mode="after")
    def validate_policy(self):
        status_keys = [status.key for status in self.statuses]
        if len(status_keys) != len(set(status_keys)):
            raise ValueError("Duplicate lifecycle status")
        if "draft" not in status_keys:
            raise ValueError("The draft status must remain enabled")

        status_set = set(status_keys)
        transition_keys: set[tuple[str, str]] = set()
        inbound: set[str] = set()
        outbound: set[str] = set()
        for transition in self.transitions:
            edge = (transition.from_status, transition.to_status)
            if edge in transition_keys:
                raise ValueError(
                    f"Duplicate transition from '{transition.from_status}' to '{transition.to_status}'"
                )
            transition_keys.add(edge)
            if transition.from_status == transition.to_status:
                raise ValueError("A status cannot transition to itself")
            for status_key in edge:
                if status_key not in DOCUMENT_LIFECYCLE_STATUS_KEYS:
                    raise ValueError(f"Transition references unknown status '{status_key}'")
                if status_key not in status_set:
                    raise ValueError(f"Transition references disabled status '{status_key}'")
            inbound.add(transition.to_status)
            outbound.add(transition.from_status)

        disconnected = [status for status in status_keys if status != "draft" and status not in inbound]
        if disconnected:
            raise ValueError(
                "Every enabled non-draft status requires an inbound transition: "
                + ", ".join(disconnected)
            )

        dead_ends = [status for status in status_keys if status != "archived" and status not in outbound]
        if dead_ends:
            raise ValueError(
                "Every enabled non-archived status requires an outbound transition: "
                + ", ".join(dead_ends)
            )

        unknown_reason_statuses = sorted(set(self.require_reason_for) - status_set)
        if unknown_reason_statuses:
            raise ValueError(
                "Reason requirements reference disabled or unknown statuses: "
                + ", ".join(unknown_reason_statuses)
            )

        if self.publish_gates.require_approved and "published" in status_set:
            if "approved" not in status_set:
                raise ValueError("Approved status is required when publish approval gate is enabled")
            invalid_publish_sources = sorted(
                transition.from_status
                for transition in self.transitions
                if transition.to_status == "published" and transition.from_status != "approved"
            )
            if invalid_publish_sources:
                raise ValueError(
                    "Publish approval gate only permits transitions from approved"
                )
        return self


class DocumentLifecyclePolicyUpdate(DocumentLifecyclePolicyBase):
    """Owner-managed project document lifecycle policy update."""


class DocumentLifecyclePolicyResponse(DocumentLifecyclePolicyBase):
    """Effective project document lifecycle policy."""

    revision: int = Field(default=1, ge=1)


# Source File Schemas
class SourceFileBase(BaseModel):
    """Base source file schema."""

    filename: str = Field(..., min_length=1, max_length=255)
    original_filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., min_length=1, max_length=100)
    size: int = Field(..., ge=0, description="File size in bytes")


class SourceFileCreate(SourceFileBase):
    """Schema for creating a source file record."""

    hash: str = Field(..., min_length=64, max_length=64, description="SHA256 hash hex")
    storage_path: str = Field(..., min_length=1, description="Storage path")
    metadata: dict[str, Any] | None = None


class SourceFileUpdate(BaseModel):
    """Schema for updating a source file."""

    status: str | None = Field(
        None,
        pattern="^(pending|processing|ready|failed)$",
    )
    metadata: dict[str, Any] | None = None


class SourceFileResponse(BaseModel):
    """Schema for source file response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID
    filename: str
    original_filename: str
    content_type: str
    size: int
    hash: str
    storage_path: str
    status: str
    metadata_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class SourceFileListResponse(PaginatedResponse[SourceFileResponse]):
    """Schema for paginated source file list response."""

    pass


class SourceIngestionJobResponse(BaseModel):
    """Persistent source-ingestion execution response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID
    source_file_id: UUID
    requested_by_id: UUID | None
    status: str
    stage: str
    attempt_count: int
    max_attempts: int
    error_message: str | None
    result_json: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SourceIngestionJobListResponse(BaseModel):
    """Source-ingestion job list response."""

    items: list[SourceIngestionJobResponse]
    total: int


# Upload Schemas
class UploadUrlResponse(BaseModel):
    """Schema for pre-signed upload URL response."""

    file_id: UUID = Field(..., description="Source file ID for confirmation")
    upload_url: str = Field(..., description="Pre-signed URL for uploading")
    storage_path: str = Field(..., description="Path where file will be stored")
    expires_at: datetime = Field(..., description="URL expiration time")


class UploadConfirmRequest(BaseModel):
    """Schema for confirming upload completion."""

    upload_token: str = Field(..., description="Token from upload initiation")
    hash: str = Field(..., min_length=64, max_length=64, description="SHA256 hash of uploaded file")


# Supported content types for source files
SUPPORTED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
}

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB default


@field_validator("content_type")
@classmethod
def validate_content_type(cls, v: str) -> str:
    """Validate that content type is supported."""
    if v not in SUPPORTED_CONTENT_TYPES:
        raise ValueError(f"Unsupported content type: {v}. Supported: {list(SUPPORTED_CONTENT_TYPES.keys())}")
    return v
