"""Document Domain Models

Database models for document management, versioning, baselines, and quality tracking.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
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


class DocumentType(str, Enum):
    """Document type enumeration."""

    URS = "urs"  # User Requirements Specification
    BRD = "brd"  # Business Requirements Document
    PRD = "prd"  # Product Requirements Document
    USER_STORY = "user_story"  # User Story
    DETAILED_DESIGN = "detailed_design"  # Detailed Design Document
    INTERFACE = "interface"  # Interface Document
    DATA_DICTIONARY = "data_dictionary"  # Data Dictionary
    TEST_CASE = "test_case"  # Test Case


class DocumentStatus(str, Enum):
    """Document status enumeration."""

    DRAFT = "draft"
    WRITING = "writing"
    PENDING_REVIEW = "pending_review"
    REVIEW = "review"
    IN_REVIEW = "in_review"
    REVISION_REQUIRED = "revision_required"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class EntityType(str, Enum):
    """Document entity type enumeration."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    LIST = "list"
    ITEM = "item"


class QualityType(str, Enum):
    """Quality check type enumeration."""

    CONSISTENCY = "consistency"
    COMPLETENESS = "completeness"
    MECE = "mece"
    CITATION = "citation"


class GenerationSessionStatus(str, Enum):
    """Interactive document generation session status."""

    ACTIVE = "active"
    FINALIZED = "finalized"
    CANCELLED = "cancelled"


class GenerationSectionStatus(str, Enum):
    """Per-section generation status."""

    PENDING = "pending"
    DRAFTED = "drafted"
    CONFIRMED = "confirmed"
    SKIPPED = "skipped"


class Document(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Document model for storing documents with versioning support.

    Documents are the primary unit of content in the system, supporting
    multiple document types, versioning, and structured content entities.
    """

    __tablename__ = "documents"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doc_type = Column(String(50), nullable=False, default=DocumentType.URS.value, index=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False, default="")
    status = Column(
        String(20),
        nullable=False,
        default=DocumentStatus.DRAFT.value,
        index=True,
    )
    version = Column(Integer, nullable=False, default=1)
    parent_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    approved_by = Column(UUID(as_uuid=True), nullable=True)
    quality_score = Column(Float, nullable=True)
    metadata_json = Column(JSONB, nullable=True)

    # Relations
    project = relationship("Project", back_populates="documents", lazy="selectin")
    parent_document = relationship(
        "Document",
        remote_side="Document.id",
        back_populates="child_documents",
        lazy="selectin",
    )
    child_documents = relationship(
        "Document",
        back_populates="parent_document",
        lazy="selectin",
    )
    entities = relationship(
        "DocumentEntity",
        back_populates="document",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="DocumentEntity.position",
    )
    versions = relationship(
        "DocumentVersion",
        back_populates="document",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version.desc()",
    )
    baselines = relationship(
        "DocumentBaseline",
        back_populates="document",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    quality_results = relationship(
        "QualityResult",
        back_populates="document",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_documents_tenant_id", "tenant_id"),
        Index("ix_documents_project_id", "project_id"),
        Index("ix_documents_doc_type", "doc_type"),
        Index("ix_documents_status", "status"),
        Index("ix_documents_created_by", "created_by"),
    )


class DocumentGenerationSession(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Stateful section-by-section document generation session."""

    __tablename__ = "document_generation_sessions"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    template_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    doc_type = Column(String(50), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    status = Column(String(20), nullable=False, default=GenerationSessionStatus.ACTIVE.value, index=True)
    generation_mode = Column(String(30), nullable=False, default="interactive")
    current_section_key = Column(String(120), nullable=True)
    context_json = Column(JSONB, nullable=False, default=dict)
    stash_json = Column(JSONB, nullable=False, default=dict)
    quality_summary_json = Column(JSONB, nullable=False, default=dict)
    created_by = Column(UUID(as_uuid=True), nullable=False, index=True)
    finalized_at = Column(DateTime(timezone=True), nullable=True)

    sections = relationship(
        "DocumentGenerationSection",
        back_populates="session",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="DocumentGenerationSection.position",
    )
    steps = relationship(
        "DocumentGenerationStep",
        back_populates="session",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="DocumentGenerationStep.step_index",
    )
    document = relationship("Document", lazy="selectin")

    __table_args__ = (
        Index("ix_document_generation_sessions_tenant_id", "tenant_id"),
        Index("ix_document_generation_sessions_project_id", "project_id"),
        Index("ix_document_generation_sessions_doc_type", "doc_type"),
        Index("ix_document_generation_sessions_status", "status"),
    )


class DocumentGenerationSection(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Draft and confirmation state for one generated document section."""

    __tablename__ = "document_generation_sections"

    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("document_generation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_key = Column(String(120), nullable=False)
    title = Column(String(255), nullable=False)
    position = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default=GenerationSectionStatus.PENDING.value)
    prompt = Column(Text, nullable=False, default="")
    content_requirement = Column(Text, nullable=False, default="")
    content = Column(Text, nullable=False, default="")
    pending_questions_json = Column(JSONB, nullable=False, default=list)
    confirmed_facts_json = Column(JSONB, nullable=False, default=list)
    quality_json = Column(JSONB, nullable=False, default=dict)
    required_inputs = Column(JSONB, nullable=False, default=list)
    quality_rules = Column(JSONB, nullable=False, default=list)

    session = relationship("DocumentGenerationSession", back_populates="sections")

    __table_args__ = (
        Index("ix_document_generation_sections_tenant_id", "tenant_id"),
        Index("ix_document_generation_sections_session_id", "session_id"),
        Index("ix_document_generation_sections_key", "session_id", "section_key"),
        Index("ix_document_generation_sections_order", "session_id", "position"),
    )


class DocumentGenerationStep(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Audit log for user and assistant turns in a generation session."""

    __tablename__ = "document_generation_steps"

    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("document_generation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_index = Column(Integer, nullable=False, default=0)
    role = Column(String(20), nullable=False)
    action_type = Column(String(30), nullable=False)
    section_key = Column(String(120), nullable=True)
    message = Column(Text, nullable=False, default="")
    patch_json = Column(JSONB, nullable=False, default=dict)
    quality_json = Column(JSONB, nullable=False, default=dict)
    created_by = Column(UUID(as_uuid=True), nullable=True, index=True)

    session = relationship("DocumentGenerationSession", back_populates="steps")

    __table_args__ = (
        Index("ix_document_generation_steps_tenant_id", "tenant_id"),
        Index("ix_document_generation_steps_session_id", "session_id"),
        Index("ix_document_generation_steps_order", "session_id", "step_index"),
    )


# Add relationship to Project model
from app.models.projects import Project  # noqa: PLC0415

Project.documents = relationship(
    "Document",
    back_populates="project",
    lazy="selectin",
    cascade="all, delete-orphan",
)


class DocumentEntity(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Document entity model for structured content.

    Represents individual content elements within a document,
    such as headings, paragraphs, tables, and list items.
    """

    __tablename__ = "document_entities"

    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_type = Column(String(20), nullable=False, default=EntityType.PARAGRAPH.value)
    content = Column(Text, nullable=False)
    position = Column(Integer, nullable=False, default=0)
    parent_entity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("document_entities.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    metadata_json = Column(JSONB, nullable=True)

    # Relations
    document = relationship("Document", back_populates="entities")
    parent_entity = relationship(
        "DocumentEntity",
        remote_side="DocumentEntity.id",
        back_populates="child_entities",
        lazy="selectin",
    )
    child_entities = relationship(
        "DocumentEntity",
        back_populates="parent_entity",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="DocumentEntity.position",
    )

    __table_args__ = (
        Index("ix_document_entities_tenant_id", "tenant_id"),
        Index("ix_document_entities_document_id", "document_id"),
        Index("ix_document_entities_parent_entity_id", "parent_entity_id"),
    )


class DocumentVersion(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Document version model for version history tracking.

    Stores historical snapshots of document content for rollback
    and audit purposes.
    """

    __tablename__ = "document_versions"

    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    changes_summary = Column(Text, nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        nullable=False,
    )

    # Relations
    document = relationship("Document", back_populates="versions")

    __table_args__ = (
        Index("ix_document_versions_tenant_id", "tenant_id"),
        Index("ix_document_versions_document_id", "document_id"),
        Index("ix_document_versions_version", "document_id", "version"),
    )


class DocumentBaseline(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Document baseline model for approved version snapshots.

    Baselines represent approved document versions that can be
    used for comparison and rollback.
    """

    __tablename__ = "document_baselines"

    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    baseline_name = Column(String(255), nullable=False)
    baseline_reason = Column(Text, nullable=True)
    approved_by = Column(UUID(as_uuid=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    # Relations
    document = relationship("Document", back_populates="baselines")
    version = relationship("DocumentVersion", lazy="selectin")

    __table_args__ = (
        Index("ix_document_baselines_tenant_id", "tenant_id"),
        Index("ix_document_baselines_document_id", "document_id"),
    )


class QualityResult(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Quality result model for document quality assessment.

    Stores results of quality checks including consistency,
    completeness, MECE compliance, and citation coverage.
    """

    __tablename__ = "quality_results"

    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    quality_type = Column(
        String(20),
        nullable=False,
        default=QualityType.CONSISTENCY.value,
    )
    score = Column(Float, nullable=False)
    issues_json = Column(JSONB, nullable=True)
    checked_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relations
    document = relationship("Document", back_populates="quality_results")

    __table_args__ = (
        Index("ix_quality_results_tenant_id", "tenant_id"),
        Index("ix_quality_results_document_id", "document_id"),
        Index("ix_quality_results_quality_type", "quality_type"),
    )
