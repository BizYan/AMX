"""Knowledge Domain Models

Database models for knowledge base, RAG, GraphRAG, and lineage tracking.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, Float
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


class SharingScope(str, Enum):
    """Knowledge sharing scope."""

    PRIVATE = "private"  # Only creator sees
    PROJECT = "project"  # Project members see
    TENANT = "tenant"  # All users in tenant see
    GLOBAL = "global"  # All users on platform see


class EntryType(str, Enum):
    """Knowledge entry types."""

    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    CODE = "code"


class LinkType(str, Enum):
    """Knowledge link types."""

    CITES = "cites"
    EXTENDS = "extends"
    DEPENDS_ON = "depends_on"
    IMPLEMENTS = "implements"


class LineageType(str, Enum):
    """Lineage relationship types."""

    DERIVED_FROM = "derived_from"
    VERSION_OF = "version_of"
    TRANSFORMED_FROM = "transformed_from"
    IMPORTS = "imports"


class KnowledgeEntry(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Knowledge entry model for storing searchable knowledge.

    Stores textual, tabular, image, or code content with vector embeddings
    for semantic search capabilities.
    """

    __tablename__ = "knowledge_entries"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_file_id = Column(
        UUID(as_uuid=True),
        ForeignKey("source_files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    entry_type = Column(String(20), nullable=False, default=EntryType.TEXT.value)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    vector_embedding = Column(JSONB, nullable=True)  # Store as JSON for pgvector compatibility
    metadata_json = Column(JSONB, nullable=True)
    sharing_scope = Column(
        String(20),
        nullable=False,
        default=SharingScope.PROJECT.value,
    )
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    # Relations
    project = relationship("Project", back_populates="knowledge_entries", lazy="selectin")
    source_file = relationship("SourceFile", back_populates="knowledge_entries", lazy="selectin")
    created_by = relationship("User", foreign_keys=[created_by_id], lazy="selectin")
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id], lazy="selectin")

    __table_args__ = (
        Index("ix_knowledge_entries_tenant_id", "tenant_id"),
        Index("ix_knowledge_entries_project_id", "project_id"),
        Index("ix_knowledge_entries_entry_type", "entry_type"),
        Index("ix_knowledge_entries_content_hash", "content_hash"),
    )


# Add relationship to Project model
from app.models.projects import Project  # noqa: PLC0415

Project.knowledge_entries = relationship(
    "KnowledgeEntry",
    back_populates="project",
    lazy="selectin",
    cascade="all, delete-orphan",
)

# Add relationship to SourceFile model
from app.domains.projects.models import SourceFile  # noqa: PLC0415

SourceFile.knowledge_entries = relationship(
    "KnowledgeEntry",
    back_populates="source_file",
    lazy="selectin",
    cascade="all, delete-orphan",
)


class KnowledgeLink(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Knowledge link model for representing relationships between entries.

    Supports various link types like citations, extensions, dependencies,
    and implementations for building a knowledge graph.
    """

    __tablename__ = "knowledge_links"

    source_entry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_entry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    link_type = Column(String(20), nullable=False, default=LinkType.CITES.value)
    confidence = Column(Float, nullable=True, default=1.0)
    metadata_json = Column(JSONB, nullable=True)

    # Relations
    source_entry = relationship(
        "KnowledgeEntry",
        foreign_keys=[source_entry_id],
        back_populates="outgoing_links",
        lazy="selectin",
    )
    target_entry = relationship(
        "KnowledgeEntry",
        foreign_keys=[target_entry_id],
        back_populates="incoming_links",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_knowledge_links_tenant_id", "tenant_id"),
        Index("ix_knowledge_links_source_entry_id", "source_entry_id"),
        Index("ix_knowledge_links_target_entry_id", "target_entry_id"),
        Index("ix_knowledge_links_link_type", "link_type"),
        Index("ix_knowledge_links_source_target", "source_entry_id", "target_entry_id"),
    )


# Add relationships to KnowledgeEntry
KnowledgeEntry.outgoing_links = relationship(
    "KnowledgeLink",
    foreign_keys=[KnowledgeLink.source_entry_id],
    back_populates="source_entry",
    lazy="selectin",
    cascade="all, delete-orphan",
)

KnowledgeEntry.incoming_links = relationship(
    "KnowledgeLink",
    foreign_keys=[KnowledgeLink.target_entry_id],
    back_populates="target_entry",
    lazy="selectin",
)


class ProvenanceRecord(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Provenance record model for tracking entry origins.

    Records the provider, version, and raw artifact information
    that was used to create a knowledge entry.
    """

    __tablename__ = "provenance_records"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_id = Column(String(100), nullable=False)
    provider_version_id = Column(String(100), nullable=True)
    raw_artifact_id = Column(String(255), nullable=True)
    confidence = Column(Float, nullable=True, default=1.0)
    normalization_notes = Column(Text, nullable=True)

    # Relations
    project = relationship("Project", back_populates="provenance_records", lazy="selectin")
    entry = relationship("KnowledgeEntry", back_populates="provenance_records", lazy="selectin")

    __table_args__ = (
        Index("ix_provenance_records_tenant_id", "tenant_id"),
        Index("ix_provenance_records_project_id", "project_id"),
        Index("ix_provenance_records_entry_id", "entry_id"),
        Index("ix_provenance_records_provider_id", "provider_id"),
    )


# Add relationships to Project
Project.provenance_records = relationship(
    "ProvenanceRecord",
    back_populates="project",
    lazy="selectin",
    cascade="all, delete-orphan",
)

# Add relationships to KnowledgeEntry
KnowledgeEntry.provenance_records = relationship(
    "ProvenanceRecord",
    back_populates="entry",
    lazy="selectin",
    cascade="all, delete-orphan",
)


class KnowledgeVector(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Knowledge vector model for dedicated vector storage.

    Separate table for vector data to enable efficient vector operations
    and separate indexing strategies.
    """

    __tablename__ = "knowledge_vectors"

    tenant_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    entry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vector_embedding = Column(JSONB, nullable=False)  # Store vector as JSON
    vector_index = Column(String(50), nullable=True)  # Index name for multi-index support

    # Relations
    entry = relationship("KnowledgeEntry", back_populates="vectors", lazy="selectin")

    __table_args__ = (
        Index("ix_knowledge_vectors_entry_id", "entry_id"),
        Index("ix_knowledge_vectors_tenant_id", "tenant_id"),
        Index("ix_knowledge_vectors_vector_index", "vector_index"),
    )


# Add relationship to KnowledgeEntry
KnowledgeEntry.vectors = relationship(
    "KnowledgeVector",
    back_populates="entry",
    lazy="selectin",
    cascade="all, delete-orphan",
)


class LineageRecord(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Lineage record model for tracking data transformations.

    Records the relationships between different data entities across
    transformations, versions, and derivations.
    """

    __tablename__ = "lineage_records"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type = Column(String(50), nullable=False)
    source_id = Column(UUID(as_uuid=True), nullable=False)
    target_type = Column(String(50), nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=False)
    lineage_type = Column(String(50), nullable=False, default=LineageType.DERIVED_FROM.value)
    metadata_json = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_lineage_records_tenant_id", "tenant_id"),
        Index("ix_lineage_records_project_id", "project_id"),
        Index("ix_lineage_records_source", "source_type", "source_id"),
        Index("ix_lineage_records_target", "target_type", "target_id"),
        Index("ix_lineage_records_lineage_type", "lineage_type"),
    )


class FTSDocument(Base, UuidMixin, TimestampMixin, SoftDeleteMixin):
    """Full-text search document model for PostgreSQL FTS.

    Stores document content and tsvector for full-text search capabilities.
    This is a separate table from KnowledgeEntry to optimize FTS operations.
    """

    __tablename__ = "knowledge_fts_documents"

    entry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_entries.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    content = Column(Text, nullable=False)
    metadata_json = Column("metadata", JSONB, nullable=True)
    search_vector = Column(Text, nullable=True)  # Stores tsvector as text for JSON compatibility

    # Relation
    entry = relationship("KnowledgeEntry", back_populates="fts_document", lazy="selectin")

    __table_args__ = (
        Index("ix_fts_documents_entry_id", "entry_id"),
    )


# Add relationship to KnowledgeEntry
KnowledgeEntry.fts_document = relationship(
    "FTSDocument",
    back_populates="entry",
    lazy="selectin",
    cascade="all, delete-orphan",
)
