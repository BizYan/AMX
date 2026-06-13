"""Export Domain Models

Database models for export jobs and artifacts tracking.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import (
    Base,
    TenantMixin,
    TimestampMixin,
    UuidMixin,
)

if TYPE_CHECKING:
    pass


class ExportType(str, Enum):
    """Export type enumeration."""

    WORD = "word"
    MARKDOWN = "markdown"
    PPTX = "pptx"
    PROJECT_PACKAGE = "project_package"


class ExportStatus(str, Enum):
    """Export job status enumeration."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportJob(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Export job model for tracking document exports.

    Tracks the status and metadata of export operations
    for Word, Markdown, and PPTX formats.
    """

    __tablename__ = "export_jobs"

    project_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    document_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    template_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    export_type = Column(
        String(20),
        nullable=False,
        default=ExportType.WORD.value,
    )
    status = Column(
        String(20),
        nullable=False,
        default=ExportStatus.PENDING.value,
    )
    output_path = Column(Text, nullable=True)
    file_hash = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relations
    artifacts = relationship(
        "ExportArtifact",
        back_populates="job",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_export_jobs_tenant_id", "tenant_id"),
        Index("ix_export_jobs_project_id", "project_id"),
        Index("ix_export_jobs_document_id", "document_id"),
        Index("ix_export_jobs_status", "status"),
        Index("ix_export_jobs_created_by", "created_by"),
    )


class ExportArtifact(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Export artifact model for stored export files.

    Stores metadata about generated export files for download.
    """

    __tablename__ = "export_artifacts"

    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("export_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)
    storage_path = Column(Text, nullable=False)
    file_hash = Column(String(64), nullable=True)

    # Relations
    job = relationship("ExportJob", back_populates="artifacts")

    __table_args__ = (
        Index("ix_export_artifacts_job_id", "job_id"),
        Index("ix_export_artifacts_tenant_id", "tenant_id"),
    )

