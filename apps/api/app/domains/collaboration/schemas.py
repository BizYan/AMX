"""Collaboration Domain Schemas

Pydantic v2 schemas for request/response validation in collaboration features.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# Lock Schemas
from app.domains.collaboration.models import LockType, SnapshotType  # noqa: PLC0415


class CollaborationWorkItemCreate(BaseModel):
    project_id: UUID
    document_id: UUID | None = None
    comment_id: UUID | None = None
    assigned_to: UUID | None = None
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=10000)
    work_type: str = Field(default="manual", max_length=40)
    priority: str = Field(default="medium", max_length=20)
    due_at: datetime | None = None


class CollaborationWorkItemUpdate(BaseModel):
    assigned_to: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    priority: str | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, max_length=30)
    due_at: datetime | None = None


class CollaborationWorkItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    document_id: UUID | None = None
    comment_id: UUID | None = None
    assigned_to: UUID | None = None
    assigned_to_name: str | None = None
    created_by: UUID
    project_name: str = ""
    work_type: str
    status: str
    priority: str
    title: str
    description: str
    due_at: datetime | None = None
    completed_at: datetime | None = None
    source_key: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class CollaborationWorkItemBoardResponse(BaseModel):
    items: list[CollaborationWorkItemResponse]
    total: int
    page: int
    page_size: int
    has_more: bool
    mine_count: int
    unassigned_count: int
    overdue_count: int
    status_counts: dict[str, int]


class CollaborationLockAcquire(BaseModel):
    """Schema for acquiring a lock."""

    resource_type: str = Field(..., min_length=1, max_length=50, description="Type of resource (document, section, entity)")
    resource_id: UUID = Field(..., description="UUID of the resource to lock")
    lock_type: str = Field(default=LockType.EXCLUSIVE.value, description="Lock type: exclusive or shared")
    ttl_seconds: int = Field(default=300, ge=10, le=3600, description="Time-to-live in seconds (10s to 1h)")


class CollaborationLockRelease(BaseModel):
    """Schema for releasing a lock."""

    lock_id: UUID = Field(..., description="UUID of the lock to release")


class CollaborationLockResponse(BaseModel):
    """Schema for lock response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    resource_type: str
    resource_id: UUID
    locked_by: UUID
    locked_at: datetime
    expires_at: datetime
    lock_type: str


# Snapshot Schemas
class DocumentSnapshotCreate(BaseModel):
    """Schema for creating a document snapshot."""

    snapshot_type: str = Field(default=SnapshotType.AUTO.value, description="Snapshot type: auto or manual")
    title: str | None = Field(default=None, min_length=1, max_length=500, description="Unsaved draft title")
    content: str | None = Field(default=None, description="Unsaved draft content")


class DocumentSnapshotResponse(BaseModel):
    """Schema for snapshot response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_id: UUID
    user_id: UUID
    snapshot_data: dict[str, Any]
    snapshot_type: str
    version: int
    created_at: datetime


# Comment Schemas
class DocumentCommentCreate(BaseModel):
    """Schema for creating a document comment."""

    entity_id: UUID | None = Field(None, description="UUID of the entity to comment on (null for general comments)")
    content: str = Field(..., min_length=1, max_length=10000, description="Comment content")
    anchor: str | None = Field(None, max_length=1000, description="Human-readable section or paragraph location")
    parent_comment_id: UUID | None = Field(None, description="UUID of parent comment for replies")


class DocumentCommentUpdate(BaseModel):
    """Schema for updating a document comment."""

    content: str = Field(..., min_length=1, max_length=10000, description="Updated comment content")


class DocumentCommentResponse(BaseModel):
    """Schema for comment response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_id: UUID
    entity_id: UUID | None
    user_id: UUID
    content: str
    anchor: str | None
    resolved: bool
    parent_comment_id: UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


# Thread Schemas
class CommentThreadCreate(BaseModel):
    """Schema for creating a comment thread."""

    thread_type: str = Field(default="general", description="Thread type: general or entity")


class CommentThreadResponse(BaseModel):
    """Schema for thread response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_id: UUID
    thread_type: str
    created_at: datetime
    updated_at: datetime


class CollaborationMemberResponse(BaseModel):
    """Team member summary for the collaboration review hub."""

    id: UUID
    name: str
    email: str
    role: str
    status: str
    pending_count: int
    current_focus: str


class CollaborationReviewItemResponse(BaseModel):
    """Document review queue item derived from document, comments, and audit state."""

    id: UUID
    document_id: UUID
    project_id: UUID
    title: str
    document_type: str
    owner: str
    role: str
    status: str
    priority: str
    pending_comments: int
    snapshot_count: int = 0
    baseline_count: int = 0
    updated_at: datetime
    summary: str
    acceptance_decision: str
    action_href: str


class CollaborationCommentTodoResponse(BaseModel):
    """Unresolved comment work item grouped by document."""

    id: str
    document_id: UUID
    document_title: str
    assignee: str
    count: int
    due: str
    action_href: str


class CollaborationActivityResponse(BaseModel):
    """Recent collaboration or audit activity shown in the review hub."""

    id: str
    actor: str
    action: str
    target: str
    created_at: datetime


class CollaborationAcceptanceDecisionResponse(BaseModel):
    """Aggregated acceptance decision count."""

    id: str
    label: str
    status: str
    count: int


class CollaborationReviewHubResponse(BaseModel):
    """Full collaboration review hub response."""

    members: list[CollaborationMemberResponse]
    review_queue: list[CollaborationReviewItemResponse]
    comment_todos: list[CollaborationCommentTodoResponse]
    recent_activities: list[CollaborationActivityResponse]
    acceptance_decisions: list[CollaborationAcceptanceDecisionResponse]


class CollaborationAcceptanceSummaryResponse(BaseModel):
    """Aggregated acceptance and review readiness summary."""

    total_reviews: int
    passed_reviews: int
    blocked_reviews: int
    follow_up_reviews: int
    pending_comments: int
    open_work_items: int
    overdue_work_items: int
    unassigned_work_items: int
    active_members: int


class CollaborationAcceptanceGateResponse(BaseModel):
    """Release gate for collaboration acceptance readiness."""

    status: str
    label: str
    summary: str
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CollaborationAcceptanceRiskResponse(BaseModel):
    """Actionable collaboration acceptance risk."""

    code: str
    severity: str
    title: str
    detail: str
    count: int
    href: str


class CollaborationAcceptanceActionResponse(BaseModel):
    """Priority action for closing collaboration acceptance."""

    code: str
    title: str
    description: str
    href: str
    priority: str


class CollaborationAcceptanceCommandCenterResponse(BaseModel):
    """Acceptance command center payload for release review."""

    release_gate: CollaborationAcceptanceGateResponse
    summary: CollaborationAcceptanceSummaryResponse
    risk_items: list[CollaborationAcceptanceRiskResponse]
    priority_actions: list[CollaborationAcceptanceActionResponse]
    review_queue: list[CollaborationReviewItemResponse]
    comment_todos: list[CollaborationCommentTodoResponse]
    acceptance_decisions: list[CollaborationAcceptanceDecisionResponse]


# Error Response
class LockConflictError(BaseModel):
    """Schema for lock conflict error."""

    error: str = "lock_conflict"
    message: str
    existing_lock: CollaborationLockResponse | None = None


class LockNotFoundError(BaseModel):
    """Schema for lock not found error."""

    error: str = "lock_not_found"
    message: str


class LockExpiredError(BaseModel):
    """Schema for lock expired error."""

    error: str = "lock_expired"
    message: str
