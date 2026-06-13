"""Knowledge Domain API Router

FastAPI endpoints for knowledge management, RAG, GraphRAG, and lineage tracking.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.domains.identity.models import User
from app.domains.knowledge.models import KnowledgeEntry, KnowledgeLink, LineageRecord, ProvenanceRecord
from app.domains.knowledge.schemas import (
    KnowledgeEntryCreate,
    KnowledgeEntryUpdate,
    KnowledgeEntryResponse,
    KnowledgeEntryListResponse,
    KnowledgeLinkCreate,
    KnowledgeLinkUpdate,
    KnowledgeLinkResponse,
    KnowledgeLinkListResponse,
    KnowledgeGraphWorkbenchResponse,
    ProvenanceRecordCreate,
    ProvenanceRecordResponse,
    ProvenanceRecordListResponse,
    LineageRecordCreate,
    LineageRecordResponse,
    LineageRecordListResponse,
    KnowledgeQuery,
    KnowledgeQueryResponse,
    KnowledgeSearchResult,
    GraphNeighborResponse,
    GraphPathResponse,
    BulkEntryCreate,
    BulkEntryResponse,
    PaginatedResponse,
)
from app.domains.knowledge.service import KnowledgeService
from app.integrations.llm.gateway import LLMGateway
from app.services.retrieval_service import RetrievalService

router = APIRouter(tags=["knowledge"])
security = HTTPBearer()


# ============================================================================
# Dependency Injection
# ============================================================================


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Dependency to get current authenticated user from JWT token.

    Args:
        credentials: HTTP Bearer token credentials
        db: Database session

    Returns:
        User: Current authenticated user

    Raises:
        HTTPException: 401 if not authenticated
    """
    from app.domains.identity.service import AuthService

    auth_service = AuthService(db)
    token = credentials.credentials

    user = await auth_service.get_current_user(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return user


def get_llm_gateway() -> LLMGateway | None:
    """Get LLM gateway with fallback if configured."""
    from app.core.settings import settings
    from app.integrations.llm.gateway import GatewayFactory

    if settings.OPENAI_API_KEY:
        return GatewayFactory.create_with_openai_fallback(
            minimax_api_key=settings.OPENAI_API_KEY,
            minimax_base_url=settings.OPENAI_BASE_URL,
            minimax_model=settings.OPENAI_MODEL,
            openai_api_key=settings.LLM_FALLBACK_API_KEY or None,
            openai_base_url=settings.LLM_FALLBACK_BASE_URL,
            openai_model=settings.LLM_FALLBACK_MODEL,
        )
    return None


def get_knowledge_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeService:
    """Factory for KnowledgeService."""
    llm_gateway = get_llm_gateway()
    return KnowledgeService(db, llm_gateway)


def get_retrieval_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RetrievalService:
    """Factory for RetrievalService."""
    return RetrievalService(db)


# ============================================================================
# Knowledge Entry Endpoints
# ============================================================================


@router.get("/entries", response_model=KnowledgeEntryListResponse)
async def list_entries(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: UUID | None = Query(default=None),
    entry_type: str | None = Query(default=None),
    source_file_id: UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> KnowledgeEntryListResponse:
    """List knowledge entries with pagination and filters.

    Args:
        user: Current authenticated user
        db: Database session
        project_id: Optional project filter
        entry_type: Optional entry type filter (text, table, image, code)
        source_file_id: Optional source file filter
        page: Page number (1-indexed)
        page_size: Items per page (max 100)

    Returns:
        Paginated list of knowledge entries
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    result = await service.list_entries(
        tenant_id=user.tenant_id,
        project_id=project_id,
        entry_type=entry_type,
        source_file_id=source_file_id,
        page=page,
        page_size=page_size,
        user_id=user.id,
    )

    return KnowledgeEntryListResponse(
        items=result.items,
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        has_more=result.has_more,
    )


@router.post("/entries", response_model=KnowledgeEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_entry(
    data: KnowledgeEntryCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> KnowledgeEntryResponse:
    """Create a new knowledge entry.

    Args:
        data: Entry creation data
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Returns:
        Created knowledge entry
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    entry = await service.create_entry(
        tenant_id=user.tenant_id,
        project_id=data.project_id,
        entry_type=data.entry_type,
        content=data.content,
        source_file_id=data.source_file_id,
        metadata=data.metadata,
        generate_embedding=data.generate_embedding,
        sharing_scope=data.sharing_scope.value if hasattr(data.sharing_scope, 'value') else data.sharing_scope,
        created_by_id=user.id,
    )

    return entry


@router.get("/entries/{entry_id}", response_model=KnowledgeEntryResponse)
async def get_entry(
    entry_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeEntryResponse:
    """Get a knowledge entry by ID.

    Args:
        entry_id: Entry UUID
        user: Current authenticated user
        db: Database session

    Returns:
        Knowledge entry details

    Raises:
        HTTPException: 404 if not found
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    entry = await service.get_entry(entry_id, tenant_id=user.tenant_id, user_id=user.id)

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge entry not found",
        )

    return entry


@router.patch("/entries/{entry_id}", response_model=KnowledgeEntryResponse)
async def update_entry(
    entry_id: UUID,
    data: KnowledgeEntryUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> KnowledgeEntryResponse:
    """Update a knowledge entry.

    Args:
        entry_id: Entry UUID
        data: Update data
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Returns:
        Updated knowledge entry

    Raises:
        HTTPException: 404 if not found
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    entry = await service.update_entry(entry_id, tenant_id=user.tenant_id, updates=data)

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge entry not found",
        )

    return entry


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> None:
    """Soft delete a knowledge entry.

    Args:
        entry_id: Entry UUID
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Raises:
        HTTPException: 404 if not found
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    deleted = await service.delete_entry(entry_id, tenant_id=user.tenant_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge entry not found",
        )


@router.post("/entries/{entry_id}/link", response_model=KnowledgeLinkResponse, status_code=status.HTTP_201_CREATED)
async def link_entries(
    entry_id: UUID,
    data: KnowledgeLinkCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> KnowledgeLinkResponse:
    """Create a knowledge link from an entry to another entry.

    Args:
        entry_id: Source entry UUID
        data: Link creation data
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Returns:
        Created knowledge link

    Raises:
        HTTPException: 404 if source or target not found
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    link = await service.link_entries(
        source_id=entry_id,
        target_id=data.target_entry_id,
        link_type=data.link_type,
        tenant_id=user.tenant_id,
        confidence=data.confidence,
        metadata=data.metadata,
    )

    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source or target entry not found",
        )

    return link


@router.get("/entries/{entry_id}/links", response_model=list[KnowledgeLinkResponse])
async def get_entry_links(
    entry_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    direction: str = Query(default="both", pattern="^(outgoing|incoming|both)$"),
) -> list[KnowledgeLinkResponse]:
    """Get all links for a knowledge entry.

    Args:
        entry_id: Entry UUID
        user: Current authenticated user
        db: Database session
        direction: Link direction (outgoing, incoming, both)

    Returns:
        List of knowledge links
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    return await service.get_entry_links(entry_id, tenant_id=user.tenant_id, direction=direction)


@router.get("/links", response_model=KnowledgeLinkListResponse)
async def list_links(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: UUID | None = Query(default=None),
    source_file_id: UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=300),
) -> KnowledgeLinkListResponse:
    """List graph links for graph workbench compatibility."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    graph = await service.get_graph_workbench(
        tenant_id=user.tenant_id,
        project_id=project_id,
        source_file_id=source_file_id,
        limit=page * page_size,
        user_id=user.id,
    )
    offset = (page - 1) * page_size
    edge_slice = graph.edges[offset : offset + page_size]
    items = [
        KnowledgeLinkResponse(
            id=edge.id,
            tenant_id=user.tenant_id,
            source_entry_id=edge.source,
            target_entry_id=edge.target,
            link_type=edge.type,
            confidence=edge.confidence,
            metadata_json=edge.metadata,
            created_at=edge.created_at,
        )
        for edge in edge_slice
    ]
    return KnowledgeLinkListResponse(
        items=items,
        total=len(graph.edges),
        page=page,
        page_size=page_size,
        has_more=(offset + len(items)) < len(graph.edges),
    )


@router.patch("/links/{link_id}", response_model=KnowledgeLinkResponse)
async def update_link(
    link_id: UUID,
    data: KnowledgeLinkUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> KnowledgeLinkResponse:
    """Update a graph relationship type, confidence, or metadata."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    link = await service.update_link(
        link_id=link_id,
        tenant_id=user.tenant_id,
        link_type=data.link_type,
        confidence=data.confidence,
        metadata=data.metadata,
    )
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge link not found",
        )
    return link


@router.delete("/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(
    link_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> None:
    """Soft delete a graph relationship."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    deleted = await service.delete_link(link_id=link_id, tenant_id=user.tenant_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge link not found",
        )


@router.get("/entries/{entry_id}/lineage", response_model=list[LineageRecordResponse])
async def get_entry_lineage(
    entry_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[LineageRecordResponse]:
    """Get lineage records for a knowledge entry.

    Args:
        entry_id: Entry UUID
        user: Current authenticated user
        db: Database session

    Returns:
        List of lineage records
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    return await service.get_lineage(entry_id, tenant_id=user.tenant_id)


# ============================================================================
# Search Endpoints
# ============================================================================


@router.get("/search", response_model=KnowledgeQueryResponse)
async def search_knowledge(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = Query(..., min_length=1, description="Search query"),
    type: str = Query(default="hybrid", pattern="^(vector|fulltext|hybrid)$"),
    project_id: UUID | None = Query(default=None),
    top_k: int = Query(default=10, ge=1, le=100),
    alpha: float = Query(default=0.5, ge=0.0, le=1.0, description="Weight for vector search in hybrid mode"),
) -> KnowledgeQueryResponse:
    """Search knowledge entries using vector, full-text, or hybrid search.

    Args:
        user: Current authenticated user
        db: Database session
        q: Search query string
        type: Search type (vector, fulltext, hybrid)
        project_id: Optional project filter
        top_k: Number of results to return
        alpha: Weight for vector search in hybrid mode (0 = FTS only, 1 = vector only)

    Returns:
        Search results with scores
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    retrieval_service = get_retrieval_service(db)

    if type == "vector":
        # For vector search, we need an embedding
        llm_gateway = get_llm_gateway()
        if not llm_gateway:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Vector search requires LLM gateway configuration",
            )

        embed_response = await llm_gateway.embed([q])
        query_embedding = embed_response.embeddings[0] if embed_response.embeddings else []

        results = await retrieval_service.vector_search(
            query_embedding=query_embedding,
            tenant_id=user.tenant_id,
            project_id=project_id,
            top_k=top_k,
        )
    elif type == "fulltext":
        results = await retrieval_service.full_text_search(
            query=q,
            tenant_id=user.tenant_id,
            project_id=project_id,
            top_k=top_k,
        )
    else:  # hybrid
        llm_gateway = get_llm_gateway()
        if not llm_gateway:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Hybrid search requires LLM gateway configuration",
            )

        embed_response = await llm_gateway.embed([q])
        query_embedding = embed_response.embeddings[0] if embed_response.embeddings else []

        results = await retrieval_service.hybrid_search(
            query=q,
            query_embedding=query_embedding,
            tenant_id=user.tenant_id,
            project_id=project_id,
            top_k=top_k,
            alpha=alpha,
        )

    return KnowledgeQueryResponse(
        results=results,
        query=q,
        total=len(results),
        search_type=type,
    )


# ============================================================================
# Graph Endpoints
# ============================================================================


@router.get("/graph", response_model=KnowledgeGraphWorkbenchResponse)
async def get_graph_workbench(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: UUID | None = Query(default=None),
    source_file_id: UUID | None = Query(default=None),
    entry_type: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=300),
) -> KnowledgeGraphWorkbenchResponse:
    """Get a complete graph workbench payload for the authenticated tenant."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    return await service.get_graph_workbench(
        tenant_id=user.tenant_id,
        project_id=project_id,
        source_file_id=source_file_id,
        entry_type=entry_type,
        limit=limit,
        user_id=user.id,
    )


@router.get("/graph/{entry_id}/neighbors", response_model=list[GraphNeighborResponse])
async def get_graph_neighbors(
    entry_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    depth: int = Query(default=1, ge=1, le=10),
    direction: str = Query(default="both", pattern="^(outgoing|incoming|both)$"),
) -> list[GraphNeighborResponse]:
    """Get neighboring entries in the knowledge graph.

    Args:
        entry_id: Starting entry UUID
        user: Current authenticated user
        db: Database session
        depth: Traversal depth (1-10)
        direction: Traversal direction (outgoing, incoming, both)

    Returns:
        List of neighboring entries with link info
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    return await service.get_neighbors(
        entry_id=entry_id,
        tenant_id=user.tenant_id,
        depth=depth,
        direction=direction,
    )


@router.get("/graph/{entry_id}/path/{target_id}", response_model=GraphPathResponse)
async def get_graph_path(
    entry_id: UUID,
    target_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    max_depth: int = Query(default=10, ge=1, le=20),
) -> GraphPathResponse:
    """Find a path between two entries in the knowledge graph.

    Args:
        entry_id: Source entry UUID
        target_id: Target entry UUID
        user: Current authenticated user
        db: Database session
        max_depth: Maximum path length (1-20)

    Returns:
        Path between entries with link types
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    from app.services.graph_store_provider import PostgresGraphProvider

    graph_provider = PostgresGraphProvider(db)
    path = await graph_provider.get_path(entry_id, target_id, max_depth)

    # Filter by tenant and transform
    entries = []
    link_types = []
    for entry, link in path:
        if entry.tenant_id != user.tenant_id:
            continue
        from app.domains.knowledge.schemas import KnowledgeEntryResponse
        entries.append(KnowledgeEntryResponse(
            id=entry.id,
            tenant_id=entry.tenant_id,
            project_id=entry.project_id,
            source_file_id=entry.source_file_id,
            entry_type=entry.entry_type,
            content=entry.content,
            content_hash=entry.content_hash,
            vector_embedding=entry.vector_embedding,
            metadata=entry.metadata_json,
            sharing_scope=entry.sharing_scope,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            deleted_at=entry.deleted_at,
            created_by_id=entry.created_by_id,
            reviewed_by_id=entry.reviewed_by_id,
            reviewed_at=entry.reviewed_at,
        ))
        if link:
            link_types.append(link.link_type)

    return GraphPathResponse(
        entries=entries,
        link_types=link_types,
        total_hops=len(entries) - 1 if entries else 0,
    )


# ============================================================================
# Provenance Endpoints
# ============================================================================


@router.get("/provenance/{entry_id}", response_model=list[ProvenanceRecordResponse])
async def get_entry_provenance(
    entry_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProvenanceRecordResponse]:
    """Get provenance records for a knowledge entry.

    Args:
        entry_id: Entry UUID
        user: Current authenticated user
        db: Database session

    Returns:
        List of provenance records
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    return await service.get_provenance(entry_id, tenant_id=user.tenant_id)


@router.post("/provenance", response_model=ProvenanceRecordResponse, status_code=status.HTTP_201_CREATED)
async def create_provenance(
    data: ProvenanceRecordCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> ProvenanceRecordResponse:
    """Create a provenance record for a knowledge entry.

    Args:
        data: Provenance creation data
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Returns:
        Created provenance record
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    return await service.add_provenance(
        tenant_id=user.tenant_id,
        project_id=data.project_id,
        entry_id=data.entry_id,
        provider_id=data.provider_id,
        provider_version_id=data.provider_version_id,
        raw_artifact_id=data.raw_artifact_id,
        confidence=data.confidence,
        normalization_notes=data.normalization_notes,
    )


# ============================================================================
# Lineage Endpoints
# ============================================================================


@router.post("/lineage", response_model=LineageRecordResponse, status_code=status.HTTP_201_CREATED)
async def create_lineage(
    data: LineageRecordCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> LineageRecordResponse:
    """Create a lineage record tracking relationship between entities.

    Args:
        data: Lineage creation data
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Returns:
        Created lineage record
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = get_knowledge_service(db)
    return await service.add_lineage(
        tenant_id=user.tenant_id,
        project_id=data.project_id,
        source_type=data.source_type,
        source_id=data.source_id,
        target_type=data.target_type,
        target_id=data.target_id,
        lineage_type=data.lineage_type,
        metadata=data.metadata,
    )


# ============================================================================
# Bulk Operations
# ============================================================================


@router.post("/entries/bulk", response_model=BulkEntryResponse, status_code=status.HTTP_201_CREATED)
async def bulk_create_entries(
    data: BulkEntryCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> BulkEntryResponse:
    """Bulk create knowledge entries.

    Args:
        data: Bulk creation data with list of entries
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Returns:
        Bulk operation results with counts
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    if not data.entries:
        return BulkEntryResponse(created=0, failed=0, errors=[])

    # Use first entry's project_id as default (all entries should have same project)
    project_id = data.entries[0].project_id

    service = get_knowledge_service(db)
    return await service.bulk_create_entries(
        tenant_id=user.tenant_id,
        project_id=project_id,
        entries=data.entries,
        generate_embeddings=data.generate_embeddings,
    )


# ============================================================================
# Source File Ingestion
# ============================================================================


@router.post("/ingest/{source_file_id}", response_model=list[KnowledgeEntryResponse], status_code=status.HTTP_201_CREATED)
async def ingest_source_file(
    source_file_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: UUID = Query(..., description="Target project ID for ingestion"),
) -> list[KnowledgeEntryResponse]:
    """Ingest a source file into knowledge entries.

    Processes a source file and creates knowledge entries from its content.

    Args:
        source_file_id: Source file UUID
        user: Current authenticated user
        db: Database session
        project_id: Target project ID for ingestion
        request: HTTP request

    Returns:
        List of created knowledge entries
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    from app.domains.projects.service import SourceFileService

    service = SourceFileService(db)
    entries = await service.ingest_source_file(
        source_file_id=source_file_id,
        tenant_id=user.tenant_id,
        project_id=project_id,
    )

    return entries
