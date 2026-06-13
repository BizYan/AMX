"""Retrieval Service

High-level service for knowledge retrieval combining vector, full-text, and graph search.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.knowledge.models import KnowledgeEntry, KnowledgeLink
from app.domains.knowledge.schemas import (
    KnowledgeSearchResult,
    KnowledgeEntryResponse,
    VectorSearchResult,
    FTSearchResult,
)
from app.services.vector_store_provider import VectorStoreProvider, PGVectorProvider
from app.services.search_provider import SearchProvider, PostgresFTSProvider
from app.services.graph_store_provider import GraphStoreProvider, PostgresGraphProvider


class RetrievalService:
    """High-level service for knowledge retrieval.

    Combines vector search, full-text search, and graph traversal
    for comprehensive knowledge retrieval capabilities.
    """

    def __init__(self, session: AsyncSession):
        """Initialize retrieval service.

        Args:
            session: Async SQLAlchemy session
        """
        self.session = session
        self.vector_provider = PGVectorProvider(session)
        self.search_provider = PostgresFTSProvider(session)
        self.graph_provider = PostgresGraphProvider(session)

    async def vector_search(
        self,
        query_embedding: list[float],
        tenant_id: UUID,
        project_id: UUID | None = None,
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[KnowledgeSearchResult]:
        """Perform vector similarity search.

        Args:
            query_embedding: Query vector embedding
            tenant_id: Tenant UUID for filtering
            project_id: Optional project UUID for filtering
            top_k: Number of results to return
            filters: Additional filters

        Returns:
            List of KnowledgeSearchResult ordered by similarity
        """
        filters = filters or {}
        filters["tenant_id"] = tenant_id
        if project_id:
            filters["project_id"] = project_id

        vector_results = await self.vector_provider.search(query_embedding, top_k, filters)

        # Fetch full entry data
        results = []
        for vr in vector_results:
            entry_result = await self.session.execute(
                select(KnowledgeEntry).where(KnowledgeEntry.id == vr.entry_id)
            )
            entry = entry_result.scalar_one_or_none()

            if entry and entry.deleted_at is None:
                response = KnowledgeEntryResponse(
                    id=entry.id,
                    tenant_id=entry.tenant_id,
                    project_id=entry.project_id,
                    source_file_id=entry.source_file_id,
                    entry_type=entry.entry_type,
                    content=entry.content,
                    content_hash=entry.content_hash,
                    vector_embedding=entry.vector_embedding,
                    metadata=entry.metadata_json,
                    created_at=entry.created_at,
                    updated_at=entry.updated_at,
                    deleted_at=entry.deleted_at,
                )
                results.append(KnowledgeSearchResult(
                    entry=response,
                    score=vr.score,
                ))

        return results

    async def full_text_search(
        self,
        query: str,
        tenant_id: UUID,
        project_id: UUID | None = None,
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[KnowledgeSearchResult]:
        """Perform full-text search.

        Args:
            query: Search query string
            tenant_id: Tenant UUID for filtering
            project_id: Optional project UUID for filtering
            top_k: Number of results to return
            filters: Additional filters

        Returns:
            List of KnowledgeSearchResult ordered by relevance
        """
        filters = filters or {}
        filters["tenant_id"] = tenant_id
        if project_id:
            filters["project_id"] = project_id

        fts_results = await self.search_provider.search(query, top_k, filters)

        # Fetch full entry data
        results = []
        for fr in fts_results:
            entry_result = await self.session.execute(
                select(KnowledgeEntry).where(KnowledgeEntry.id == fr.entry_id)
            )
            entry = entry_result.scalar_one_or_none()

            if entry and entry.deleted_at is None:
                response = KnowledgeEntryResponse(
                    id=entry.id,
                    tenant_id=entry.tenant_id,
                    project_id=entry.project_id,
                    source_file_id=entry.source_file_id,
                    entry_type=entry.entry_type,
                    content=entry.content,
                    content_hash=entry.content_hash,
                    vector_embedding=entry.vector_embedding,
                    metadata=entry.metadata_json,
                    created_at=entry.created_at,
                    updated_at=entry.updated_at,
                    deleted_at=entry.deleted_at,
                )
                results.append(KnowledgeSearchResult(
                    entry=response,
                    score=fr.rank,
                    highlight=fr.headline,
                ))

        return results

    async def hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        tenant_id: UUID,
        project_id: UUID | None = None,
        top_k: int = 10,
        alpha: float = 0.5,
    ) -> list[KnowledgeSearchResult]:
        """Perform hybrid search combining vector and full-text.

        Args:
            query: Search query string (for FTS)
            query_embedding: Query vector embedding (for vector search)
            tenant_id: Tenant UUID for filtering
            project_id: Optional project UUID for filtering
            top_k: Number of results to return
            alpha: Weight for vector search (1-alpha for FTS), default 0.5

        Returns:
            List of KnowledgeSearchResult with combined scores
        """
        # Run both searches in parallel
        vector_results = await self.vector_search(
            query_embedding, tenant_id, project_id, top_k * 2
        )
        fts_results = await self.full_text_search(
            query, tenant_id, project_id, top_k * 2
        )

        # Create score maps
        vector_scores: dict[UUID, float] = {r.entry.id: r.score for r in vector_results}
        fts_scores: dict[UUID, float] = {r.entry.id: r.score for r in fts_results}

        # Get union of all entry IDs
        all_entry_ids = set(vector_scores.keys()) | set(fts_scores.keys())

        # Calculate combined scores
        combined_results = []
        for entry_id in all_entry_ids:
            v_score = vector_scores.get(entry_id, 0.0)
            f_score = fts_scores.get(entry_id, 0.0)

            # Normalize scores to 0-1 range (assuming cosine similarity)
            # and combine with alpha weighting
            combined_score = alpha * v_score + (1 - alpha) * f_score

            # Get entry from vector results or FTS results
            entry_response = None
            highlight = None
            for r in vector_results:
                if r.entry.id == entry_id:
                    entry_response = r.entry
                    break
            if not entry_response:
                for r in fts_results:
                    if r.entry.id == entry_id:
                        entry_response = r.entry
                        highlight = r.highlight
                        break

            if entry_response:
                combined_results.append(KnowledgeSearchResult(
                    entry=entry_response,
                    score=combined_score,
                    highlight=highlight,
                ))

        # Sort by combined score and return top_k
        combined_results.sort(key=lambda x: x.score, reverse=True)
        return combined_results[:top_k]

    async def graph_traverse(
        self,
        entry_id: UUID,
        tenant_id: UUID,
        depth: int = 3,
        direction: str = "both",
    ) -> list[KnowledgeEntry]:
        """Traverse the knowledge graph from a starting entry.

        Args:
            entry_id: Starting entry UUID
            tenant_id: Tenant UUID for verification
            depth: Traversal depth (default 3, max 10)
            direction: Traversal direction ("outgoing", "incoming", "both")

        Returns:
            List of KnowledgeEntry reachable from start
        """
        neighbors = await self.graph_provider.get_neighbors(entry_id, depth, direction)

        # Filter by tenant_id and extract entries
        entries = []
        for entry, link, d in neighbors:
            if entry.tenant_id == tenant_id:
                entries.append(entry)

        return entries

    async def get_connected_entries(
        self,
        entry_id: UUID,
        tenant_id: UUID,
        link_type: str | None = None,
    ) -> list[tuple[KnowledgeEntry, KnowledgeLink]]:
        """Get entries directly connected to a given entry.

        Args:
            entry_id: Entry UUID
            tenant_id: Tenant UUID for verification
            link_type: Optional filter by link type

        Returns:
            List of tuples (connected entry, link)
        """
        result = await self.session.execute(
            select(KnowledgeEntry, KnowledgeLink).where(
                KnowledgeEntry.id == entry_id,
                KnowledgeEntry.tenant_id == tenant_id,
                KnowledgeEntry.deleted_at.is_(None),
            )
        )
        start_entry = result.scalar_one_or_none()

        if not start_entry:
            return []

        # Get outgoing links
        query = select(KnowledgeEntry, KnowledgeLink).join(
            KnowledgeLink,
            KnowledgeLink.target_entry_id == KnowledgeEntry.id,
        ).where(
            KnowledgeLink.source_entry_id == entry_id,
            KnowledgeEntry.tenant_id == tenant_id,
            KnowledgeEntry.deleted_at.is_(None),
        )

        if link_type:
            query = query.where(KnowledgeLink.link_type == link_type)

        outgoing_result = await self.session.execute(query)
        outgoing = list(outgoing_result.all())

        # Get incoming links
        query = select(KnowledgeEntry, KnowledgeLink).join(
            KnowledgeLink,
            KnowledgeLink.source_entry_id == KnowledgeEntry.id,
        ).where(
            KnowledgeLink.target_entry_id == entry_id,
            KnowledgeEntry.tenant_id == tenant_id,
            KnowledgeEntry.deleted_at.is_(None),
        )

        if link_type:
            query = query.where(KnowledgeLink.link_type == link_type)

        incoming_result = await self.session.execute(query)
        incoming = list(incoming_result.all())

        return outgoing + incoming