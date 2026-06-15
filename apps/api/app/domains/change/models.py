"""Change Domain Models

Database models for change requests, field patches, and traceability tracking.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UuidMixin,
)

if TYPE_CHECKING:
    pass


class ChangeType(str, Enum):
    """Change type enumeration."""

    CORRECTION = "correction"  # Bug fixes, errors
    ENHANCEMENT = "enhancement"  # New features, improvements
    DEPENDENCY = "dependency"  # Changes due to upstream/downstream


class ChangePriority(str, Enum):
    """Change priority enumeration."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ChangeStatus(str, Enum):
    """Change request status enumeration."""

    DRAFT = "draft"
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    CANCELLED = "cancelled"


class ConflictSeverity(str, Enum):
    """Persisted document conflict severity."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConflictStatus(str, Enum):
    """Persisted document conflict lifecycle status."""

    UNASSIGNED = "unassigned"
    ANALYSIS = "analysis"
    DECISION = "decision"
    REVISION_ACCEPTED = "revision_accepted"
    REJECTED = "rejected"
    RISK_ACCEPTED = "risk_accepted"
    CLOSED = "closed"


class PatchType(str, Enum):
    """Field patch type enumeration."""

    REPLACE = "replace"
    ADD = "add"
    REMOVE = "remove"


class PatchStatus(str, Enum):
    """Field patch status enumeration."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ChangeRequest(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Change request model for tracking document changes.

    Links source documents to target documents with change descriptions,
    impact analysis, and approval workflow.
    """

    __tablename__ = "change_requests"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_document_version = Column(Integer, nullable=True)
    target_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_document_version = Column(Integer, nullable=True)
    change_type = Column(
        String(20),
        nullable=False,
        default=ChangeType.CORRECTION.value,
    )
    priority = Column(
        String(20),
        nullable=False,
        default=ChangePriority.MEDIUM.value,
    )
    status = Column(
        String(20),
        nullable=False,
        default=ChangeStatus.DRAFT.value,
    )
    description = Column(Text, nullable=False)
    rationale = Column(Text, nullable=True)
    impact_analysis = Column(Text, nullable=True)
    risk_assessment = Column(Text, nullable=True)
    requested_by = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    reviewed_by = Column(UUID(as_uuid=True), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)

    # Relations
    project = relationship("Project", back_populates="change_requests", lazy="selectin")
    source_document = relationship(
        "Document",
        remote_side="Document.id",
        foreign_keys=[source_document_id],
        back_populates="source_change_requests",
        lazy="selectin",
    )
    target_document = relationship(
        "Document",
        remote_side="Document.id",
        foreign_keys=[target_document_id],
        back_populates="target_change_requests",
        lazy="selectin",
    )
    field_patches = relationship(
        "FieldPatch",
        back_populates="change_request",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="FieldPatch.created_at",
    )
    comments = relationship(
        "ChangeRequestComment",
        back_populates="change_request",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="ChangeRequestComment.created_at",
    )

    __table_args__ = (
        Index("ix_change_requests_tenant_id", "tenant_id"),
        Index("ix_change_requests_project_id", "project_id"),
        Index("ix_change_requests_source_document_id", "source_document_id"),
        Index("ix_change_requests_target_document_id", "target_document_id"),
        Index("ix_change_requests_status", "status"),
        Index("ix_change_requests_change_type", "change_type"),
        Index("ix_change_requests_requested_by", "requested_by"),
    )


class FieldPatch(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Field patch model for granular document changes.

    Tracks individual field-level changes within a change request,
    supporting nested paths like "sections.0.content".
    """

    __tablename__ = "field_patches"

    change_request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("change_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=False,
        index=True,
    )
    document_version = Column(Integer, nullable=False)
    field_path = Column(String(500), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    patch_type = Column(
        String(20),
        nullable=False,
        default=PatchType.REPLACE.value,
    )
    status = Column(
        String(20),
        nullable=False,
        default=PatchStatus.PENDING.value,
    )
    reviewed_by = Column(UUID(as_uuid=True), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    # Relations
    change_request = relationship("ChangeRequest", back_populates="field_patches")
    document = relationship("Document", lazy="selectin")

    __table_args__ = (
        Index("ix_field_patches_tenant_id", "tenant_id"),
        Index("ix_field_patches_change_request_id", "change_request_id"),
        Index("ix_field_patches_document_id", "document_id"),
        Index("ix_field_patches_status", "status"),
    )


class ChangeRequestComment(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Comment model for change request discussions."""

    __tablename__ = "change_request_comments"

    change_request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("change_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    content = Column(Text, nullable=False)

    # Relations
    change_request = relationship("ChangeRequest", back_populates="comments")

    __table_args__ = (
        Index("ix_change_request_comments_tenant_id", "tenant_id"),
        Index("ix_change_request_comments_change_request_id", "change_request_id"),
        Index("ix_change_request_comments_user_id", "user_id"),
    )


class DocumentReference(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Version-pinned formal reference between published documents."""

    __tablename__ = "document_references"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_document_version = Column(Integer, nullable=False)
    target_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_document_version = Column(Integer, nullable=False)
    reference_type = Column(String(50), nullable=False, default="derives_from")
    source_section = Column(String(255), nullable=True)
    target_section = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="active")
    created_by = Column(UUID(as_uuid=True), nullable=False, index=True)
    metadata_json = Column(JSONB, nullable=False, default=dict)

    source_document = relationship(
        "Document",
        foreign_keys=[source_document_id],
        lazy="selectin",
    )
    target_document = relationship(
        "Document",
        foreign_keys=[target_document_id],
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_document_references_tenant_id", "tenant_id"),
        Index("ix_document_references_project_id", "project_id"),
        Index("ix_document_references_source_document_id", "source_document_id"),
        Index("ix_document_references_target_document_id", "target_document_id"),
        Index("ix_document_references_status", "status"),
    )


class DocumentImpactAnalysis(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Persistent impact analysis created from a document change trigger."""

    __tablename__ = "document_impact_analyses"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trigger_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trigger_document_version = Column(Integer, nullable=False)
    change_request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("change_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trigger_type = Column(String(50), nullable=False, default="content_changed")
    impact_level = Column(String(20), nullable=False, default="low")
    status = Column(String(20), nullable=False, default="open")
    summary = Column(Text, nullable=True)
    analysis_json = Column(JSONB, nullable=False, default=dict)
    created_by = Column(UUID(as_uuid=True), nullable=False, index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    trigger_document = relationship("Document", foreign_keys=[trigger_document_id], lazy="selectin")
    change_request = relationship("ChangeRequest", lazy="selectin")
    proposals = relationship(
        "DocumentSyncProposal",
        back_populates="impact_analysis",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="DocumentSyncProposal.created_at",
    )

    __table_args__ = (
        Index("ix_document_impact_analyses_tenant_id", "tenant_id"),
        Index("ix_document_impact_analyses_project_id", "project_id"),
        Index("ix_document_impact_analyses_trigger_document_id", "trigger_document_id"),
        Index("ix_document_impact_analyses_status", "status"),
    )


class DocumentSyncProposal(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Human-reviewed proposal to sync an impacted downstream document."""

    __tablename__ = "document_sync_proposals"

    impact_analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("document_impact_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reference_id = Column(
        UUID(as_uuid=True),
        ForeignKey("document_references.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_document_version = Column(Integer, nullable=False)
    result_document_version = Column(Integer, nullable=True)
    target_section = Column(String(255), nullable=True)
    impact_level = Column(String(20), nullable=False, default="medium")
    reason = Column(Text, nullable=False)
    suggested_action = Column(String(50), nullable=False, default="sync_content")
    candidate_content = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    decided_by = Column(UUID(as_uuid=True), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decision_note = Column(Text, nullable=True)
    metadata_json = Column(JSONB, nullable=False, default=dict)

    impact_analysis = relationship("DocumentImpactAnalysis", back_populates="proposals")
    reference = relationship("DocumentReference", lazy="selectin")
    source_document = relationship("Document", foreign_keys=[source_document_id], lazy="selectin")
    target_document = relationship("Document", foreign_keys=[target_document_id], lazy="selectin")

    __table_args__ = (
        Index("ix_document_sync_proposals_tenant_id", "tenant_id"),
        Index("ix_document_sync_proposals_impact_analysis_id", "impact_analysis_id"),
        Index("ix_document_sync_proposals_project_id", "project_id"),
        Index("ix_document_sync_proposals_source_document_id", "source_document_id"),
        Index("ix_document_sync_proposals_target_document_id", "target_document_id"),
        Index("ix_document_sync_proposals_status", "status"),
    )


class DocumentConflict(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Canonical persisted finding from an auditable document conflict rule."""

    __tablename__ = "document_conflicts"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_key = Column(String(80), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    severity = Column(String(20), nullable=False, default=ConflictSeverity.MEDIUM.value)
    status = Column(String(20), nullable=False, default=ConflictStatus.ANALYSIS.value)
    primary_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    primary_document_version = Column(Integer, nullable=False)
    related_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    related_document_version = Column(Integer, nullable=True)
    summary = Column(Text, nullable=False)
    evidence_json = Column(JSONB, nullable=False, default=dict)
    first_detected_at = Column(DateTime(timezone=True), nullable=False)
    last_detected_at = Column(DateTime(timezone=True), nullable=False)
    last_scan_id = Column(UUID(as_uuid=True), nullable=False)
    absent_since = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    assignee_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assignment_source = Column(String(40), nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=True)
    linked_change_request_id = Column(UUID(as_uuid=True), nullable=True)
    accepted_revision_json = Column(JSONB, nullable=True)
    revision_accepted_at = Column(DateTime(timezone=True), nullable=True)
    closure_scan_id = Column(UUID(as_uuid=True), nullable=True)
    closure_verified_at = Column(DateTime(timezone=True), nullable=True)
    closure_evidence_json = Column(JSONB, nullable=True)

    primary_document = relationship(
        "Document",
        foreign_keys=[primary_document_id],
        lazy="selectin",
    )
    related_document = relationship(
        "Document",
        foreign_keys=[related_document_id],
        lazy="selectin",
    )
    assignee = relationship("User", foreign_keys=[assignee_user_id], lazy="selectin")
    decisions = relationship(
        "DocumentConflictDecision",
        back_populates="conflict",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="DocumentConflictDecision.created_at",
    )

    __table_args__ = (
        Index("ix_document_conflicts_tenant_id", "tenant_id"),
        Index("ix_document_conflicts_project_id", "project_id"),
        Index("ix_document_conflicts_status", "status"),
        Index("ix_document_conflicts_severity", "severity"),
        Index("ix_document_conflicts_last_scan_id", "last_scan_id"),
        Index("ix_document_conflicts_primary_document_id", "primary_document_id"),
        Index("ix_document_conflicts_related_document_id", "related_document_id"),
        Index("ix_document_conflicts_assignee_user_id", "assignee_user_id"),
        Index("ix_document_conflicts_linked_change_request_id", "linked_change_request_id"),
        Index("ix_document_conflicts_closure_scan_id", "closure_scan_id"),
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "fingerprint",
            name="uq_document_conflicts_tenant_project_fingerprint",
        ),
    )


class DocumentConflictDecision(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Append-only governance history for a persisted document conflict."""

    __tablename__ = "document_conflict_decisions"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    conflict_id = Column(
        UUID(as_uuid=True),
        ForeignKey("document_conflicts.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    action = Column(String(60), nullable=False)
    previous_status = Column(String(20), nullable=True)
    resulting_status = Column(String(20), nullable=False)
    reason = Column(Text, nullable=True)
    evidence_json = Column(JSONB, nullable=False, default=dict)

    conflict = relationship("DocumentConflict", back_populates="decisions", lazy="selectin")
    actor = relationship("User", foreign_keys=[actor_id], lazy="selectin")

    __table_args__ = (
        Index("ix_document_conflict_decisions_tenant_id", "tenant_id"),
        Index("ix_document_conflict_decisions_project_id", "project_id"),
        Index("ix_document_conflict_decisions_conflict_id", "conflict_id"),
        Index("ix_document_conflict_decisions_actor_id", "actor_id"),
        Index("ix_document_conflict_decisions_action", "action"),
    )


# Add relationships to existing models
from app.models.projects import Project  # noqa: PLC0415
from app.domains.documents.models import Document  # noqa: PLC0415

Project.change_requests = relationship(
    "ChangeRequest",
    back_populates="project",
    lazy="selectin",
    cascade="all, delete-orphan",
)

Document.source_change_requests = relationship(
    "ChangeRequest",
    foreign_keys=[ChangeRequest.source_document_id],
    back_populates="source_document",
    lazy="selectin",
)

Document.target_change_requests = relationship(
    "ChangeRequest",
    foreign_keys=[ChangeRequest.target_document_id],
    back_populates="target_document",
    lazy="selectin",
)
