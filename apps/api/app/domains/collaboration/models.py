"""Collaboration Domain Models

Database models for pessimistic locking, document snapshots, and comments.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, Boolean, UniqueConstraint
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


class LockType(str, Enum):
    """Lock type enumeration."""

    EXCLUSIVE = "exclusive"  # Only one user can hold this lock
    SHARED = "shared"  # Multiple users can hold shared locks simultaneously


class SnapshotType(str, Enum):
    """Snapshot type enumeration."""

    AUTO = "auto"  # Automatically created (e.g., before major changes)
    MANUAL = "manual"  # Manually created by user


class ThreadType(str, Enum):
    """Comment thread type enumeration."""

    GENERAL = "general"  # General document comments
    ENTITY = "entity"  # Comments attached to specific document entities


class WorkItemType(str, Enum):
    REVIEW = "review"
    COMMENT_RESOLUTION = "comment_resolution"
    FOLLOW_UP = "follow_up"
    MANUAL = "manual"


class WorkItemStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class WorkItemPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CollaborationWorkItem(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Persistent responsibility item for reviews, comments, and follow-ups."""

    __tablename__ = "collaboration_work_items"

    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    comment_id = Column(UUID(as_uuid=True), ForeignKey("document_comments.id", ondelete="CASCADE"), nullable=True, index=True)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    work_type = Column(String(40), nullable=False, default=WorkItemType.MANUAL.value, index=True)
    status = Column(String(30), nullable=False, default=WorkItemStatus.OPEN.value, index=True)
    priority = Column(String(20), nullable=False, default=WorkItemPriority.MEDIUM.value, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    due_at = Column(DateTime(timezone=True), nullable=True, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    source_key = Column(String(255), nullable=True)
    metadata_json = Column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("tenant_id", "source_key", name="uq_collaboration_work_items_source"),
        Index("ix_collaboration_work_items_board", "tenant_id", "status", "due_at"),
        Index("ix_collaboration_work_items_assignee_status", "tenant_id", "assigned_to", "status"),
    )


class CollaborationLock(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Pessimistic lock model for module-level resource locking.

    Supports both exclusive and shared locks. Exclusive locks invalidate
    all shared locks on the same resource. Locks auto-expire after TTL.
    """

    __tablename__ = "collaboration_locks"

    tenant_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    resource_type = Column(
        String(50),
        nullable=False,
        index=True,
    )  # e.g., "document", "section", "entity"
    resource_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    locked_by = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )  # user_id
    locked_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )
    lock_type = Column(
        String(20),
        nullable=False,
        default=LockType.EXCLUSIVE.value,
    )

    __table_args__ = (
        Index("ix_collaboration_locks_tenant_id", "tenant_id"),
        Index("ix_collaboration_locks_resource", "resource_type", "resource_id"),
        Index("ix_collaboration_locks_expires_at", "expires_at"),
        Index("ix_collaboration_locks_locked_by", "locked_by"),
    )


class DocumentSnapshot(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Document snapshot model for version snapshots and restore points.

    Stores point-in-time snapshots of document content for audit and
    restore purposes.
    """

    __tablename__ = "document_snapshots"

    tenant_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    snapshot_data = Column(
        JSONB,
        nullable=False,
    )  # Stores full document state as JSON
    snapshot_type = Column(
        String(20),
        nullable=False,
        default=SnapshotType.AUTO.value,
    )
    version = Column(
        Integer,
        nullable=False,
    )  # Document version at snapshot time

    # Relations
    document = relationship("Document", lazy="selectin")

    __table_args__ = (
        Index("ix_document_snapshots_tenant_id", "tenant_id"),
        Index("ix_document_snapshots_document_id", "document_id"),
        Index("ix_document_snapshots_version", "document_id", "version"),
    )


class DocumentComment(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Document comment model for threaded discussions.

    Supports nested comments via parent_comment_id and can be attached
    to specific document entities or be general document comments.
    """

    __tablename__ = "document_comments"

    tenant_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )  # Entity within document (null for general comments)
    user_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    content = Column(
        Text,
        nullable=False,
    )
    anchor = Column(
        Text,
        nullable=True,
    )
    resolved = Column(
        Boolean,
        nullable=False,
        default=False,
    )
    parent_comment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("document_comments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Relations
    document = relationship("Document", lazy="selectin")
    parent_comment = relationship(
        "DocumentComment",
        remote_side="DocumentComment.id",
        back_populates="replies",
        lazy="selectin",
    )
    replies = relationship(
        "DocumentComment",
        back_populates="parent_comment",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_document_comments_tenant_id", "tenant_id"),
        Index("ix_document_comments_document_id", "document_id"),
        Index("ix_document_comments_entity_id", "entity_id"),
        Index("ix_document_comments_parent_id", "parent_comment_id"),
        Index("ix_document_comments_user_id", "user_id"),
    )


class CommentThread(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Comment thread model for organizing comments on documents.

    Each document can have multiple threads for different topics or entities.
    """

    __tablename__ = "comment_threads"

    tenant_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_type = Column(
        String(20),
        nullable=False,
        default=ThreadType.GENERAL.value,
    )

    # Relations
    document = relationship("Document", lazy="selectin")

    __table_args__ = (
        Index("ix_comment_threads_tenant_id", "tenant_id"),
        Index("ix_comment_threads_document_id", "document_id"),
    )


# Add relationships to Document model
from app.domains.documents.models import Document  # noqa: PLC0415

Document.snapshots = relationship(
    "DocumentSnapshot",
    back_populates="document",
    lazy="selectin",
    cascade="all, delete-orphan",
    order_by="DocumentSnapshot.created_at.desc()",
)

Document.comments = relationship(
    "DocumentComment",
    back_populates="document",
    lazy="selectin",
    cascade="all, delete-orphan",
)

Document.threads = relationship(
    "CommentThread",
    back_populates="document",
    lazy="selectin",
    cascade="all, delete-orphan",
)
