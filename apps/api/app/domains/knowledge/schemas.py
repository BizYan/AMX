"""Knowledge Domain Schemas

Pydantic v2 schemas for request/response validation.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


# Sharing Scope Enum
class SharingScope(str, Enum):
    PRIVATE = "private"
    PROJECT = "project"
    TENANT = "tenant"
    GLOBAL = "global"


# Entry Type Enum
class EntryType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    CODE = "code"


# Link Type Enum
class LinkType(str, Enum):
    CITES = "cites"
    EXTENDS = "extends"
    DEPENDS_ON = "depends_on"
    IMPLEMENTS = "implements"


# Lineage Type Enum
class LineageType(str, Enum):
    DERIVED_FROM = "derived_from"
    VERSION_OF = "version_of"
    TRANSFORMED_FROM = "transformed_from"
    IMPORTS = "imports"


# Knowledge Entry Schemas
class KnowledgeEntryBase(BaseModel):
    """Base knowledge entry schema."""

    project_id: UUID
    source_file_id: UUID | None = None
    entry_type: str = Field(..., pattern="^(text|table|image|code)$")
    content: str
    metadata: dict[str, Any] | None = None
    sharing_scope: SharingScope = Field(default=SharingScope.PROJECT, description="Sharing scope")


class KnowledgeEntryCreate(KnowledgeEntryBase):
    """Schema for creating a knowledge entry."""

    generate_embedding: bool = Field(default=True, description="Whether to generate vector embedding")


class KnowledgeEntryUpdate(BaseModel):
    """Schema for updating a knowledge entry."""

    content: str | None = None
    entry_type: str | None = Field(None, pattern="^(text|table|image|code)$")
    metadata: dict[str, Any] | None = None
    sharing_scope: SharingScope | None = None


class KnowledgeEntryResponse(KnowledgeEntryBase):
    """Schema for knowledge entry response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    content_hash: str
    vector_embedding: list[float] | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    created_by_id: UUID | None = None
    reviewed_by_id: UUID | None = None
    reviewed_at: datetime | None = None


class KnowledgeEntryListResponse(PaginatedResponse[KnowledgeEntryResponse]):
    """Schema for paginated knowledge entry list response."""

    pass


# Knowledge Link Schemas
class KnowledgeLinkBase(BaseModel):
    """Base knowledge link schema."""

    source_entry_id: UUID
    target_entry_id: UUID
    link_type: str = Field(..., pattern="^(cites|extends|depends_on|implements)$")


class KnowledgeLinkCreate(KnowledgeLinkBase):
    """Schema for creating a knowledge link."""

    confidence: float | None = Field(default=1.0, le=1.0, ge=0.0)
    metadata: dict[str, Any] | None = None


class KnowledgeLinkUpdate(BaseModel):
    """Schema for updating a knowledge link."""

    link_type: str | None = Field(None, pattern="^(cites|extends|depends_on|implements)$")
    confidence: float | None = Field(None, le=1.0, ge=0.0)
    metadata: dict[str, Any] | None = None


class KnowledgeLinkResponse(KnowledgeLinkBase):
    """Schema for knowledge link response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    confidence: float | None
    metadata_json: dict[str, Any] | None
    created_at: datetime


class KnowledgeLinkListResponse(PaginatedResponse[KnowledgeLinkResponse]):
    """Schema for paginated knowledge link list response."""

    pass


class KnowledgeGraphNode(BaseModel):
    """Node payload for the knowledge graph workbench."""

    id: UUID
    type: str
    title: str
    summary: str
    project_id: UUID
    source_file_id: UUID | None = None
    source_label: str
    status: str = "ready"
    confidence: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime | None = None


class KnowledgeGraphEdge(BaseModel):
    """Edge payload for the knowledge graph workbench."""

    id: UUID
    source: UUID
    target: UUID
    type: str
    confidence: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class KnowledgeGraphSummary(BaseModel):
    """Aggregated graph readiness metrics."""

    node_count: int
    edge_count: int
    source_count: int
    ready_count: int
    gap_count: int
    conflict_count: int
    isolated_count: int


class KnowledgeGraphWorkbenchResponse(BaseModel):
    """Workbench payload containing graph, risks, and next-action evidence."""

    nodes: list[KnowledgeGraphNode]
    edges: list[KnowledgeGraphEdge]
    summary: KnowledgeGraphSummary
    gaps: list[KnowledgeGraphNode]
    isolated_nodes: list[KnowledgeGraphNode]


# Provenance Record Schemas
class ProvenanceRecordBase(BaseModel):
    """Base provenance record schema."""

    project_id: UUID
    entry_id: UUID
    provider_id: str
    provider_version_id: str | None = None
    raw_artifact_id: str | None = None


class ProvenanceRecordCreate(ProvenanceRecordBase):
    """Schema for creating a provenance record."""

    confidence: float | None = Field(default=1.0, le=1.0, ge=0.0)
    normalization_notes: str | None = None


class ProvenanceRecordResponse(ProvenanceRecordBase):
    """Schema for provenance record response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    confidence: float | None
    normalization_notes: str | None
    created_at: datetime


class ProvenanceRecordListResponse(PaginatedResponse[ProvenanceRecordResponse]):
    """Schema for paginated provenance record list response."""

    pass


# Search Schemas
class KnowledgeSearchResult(BaseModel):
    """Schema for knowledge search result."""

    entry: KnowledgeEntryResponse
    score: float
    highlight: str | None = None


class KnowledgeQuery(BaseModel):
    """Schema for knowledge search query."""

    query: str
    project_id: UUID | None = None
    entry_types: list[str] | None = None
    source_file_ids: list[UUID] | None = None
    top_k: int = Field(default=10, ge=1, le=100)
    filters: dict[str, Any] | None = None


class KnowledgeQueryResponse(BaseModel):
    """Schema for knowledge query response."""

    results: list[KnowledgeSearchResult]
    query: str
    total: int
    search_type: str  # "vector", "fulltext", or "hybrid"


# Lineage Record Schemas
class LineageRecordBase(BaseModel):
    """Base lineage record schema."""

    project_id: UUID
    source_type: str
    source_id: UUID
    target_type: str
    target_id: UUID
    lineage_type: str = Field(..., pattern="^(derived_from|version_of|transformed_from|imports)$")


class LineageRecordCreate(LineageRecordBase):
    """Schema for creating a lineage record."""

    metadata: dict[str, Any] | None = None


class LineageRecordResponse(LineageRecordBase):
    """Schema for lineage record response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    metadata_json: dict[str, Any] | None
    created_at: datetime


class LineageRecordListResponse(PaginatedResponse[LineageRecordResponse]):
    """Schema for paginated lineage record list response."""

    pass


# Graph Traversal Schemas
class GraphNeighborResponse(BaseModel):
    """Schema for graph neighbor response."""

    entry: KnowledgeEntryResponse
    link_type: str
    depth: int


class GraphPathResponse(BaseModel):
    """Schema for graph path response."""

    entries: list[KnowledgeEntryResponse]
    link_types: list[str]
    total_hops: int


# Vector Search Result
class VectorSearchResult(BaseModel):
    """Schema for vector search result."""

    entry_id: UUID
    score: float
    metadata: dict[str, Any] | None = None


# FTS Search Result
class FTSearchResult(BaseModel):
    """Schema for full-text search result."""

    entry_id: UUID
    rank: float
    headline: str | None = None
    metadata: dict[str, Any] | None = None


# Bulk Operations
class BulkEntryCreate(BaseModel):
    """Schema for bulk creating knowledge entries."""

    entries: list[KnowledgeEntryCreate]
    generate_embeddings: bool = Field(default=True)


class BulkEntryResponse(BaseModel):
    """Schema for bulk operation response."""

    created: int
    failed: int
    errors: list[str] = Field(default_factory=list)
