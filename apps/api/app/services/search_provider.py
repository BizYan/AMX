"""Search Provider

Abstract and concrete implementations for full-text search using PostgreSQL FTS.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.knowledge.schemas import FTSearchResult


class SearchProvider(ABC):
    """Abstract base class for search providers."""

    @abstractmethod
    async def index_document(
        self,
        entry_id: UUID,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """Index a document for full-text search.

        Args:
            entry_id: UUID of the knowledge entry
            content: Text content to index
            metadata: Optional metadata dict
        """
        pass

    @abstractmethod
    async def search(
        self,
        query: str,
        top_k: int,
        filters: dict | None = None,
    ) -> list[FTSearchResult]:
        """Search for documents matching query.

        Args:
            query: Search query string
            top_k: Number of results to return
            filters: Optional filters (tenant_id, project_id, etc.)

        Returns:
            List of FTSearchResult ordered by relevance
        """
        pass

    @abstractmethod
    async def delete_document(self, entry_id: UUID) -> None:
        """Delete a document from the search index.

        Args:
            entry_id: UUID of the knowledge entry
        """
        pass

    @abstractmethod
    async def reindex_entry(self, entry_id: UUID) -> None:
        """Reindex an entry (delete and recreate).

        Args:
            entry_id: UUID of the knowledge entry
        """
        pass


class PostgresFTSProvider(SearchProvider):
    """PostgreSQL full-text search implementation of SearchProvider.

    Uses PostgreSQL's tsvector and tsquery for indexing and searching.
    Supports websearch_to_tsquery for natural language queries.
    """

    def __init__(self, session: AsyncSession):
        """Initialize Postgres FTS provider.

        Args:
            session: Async SQLAlchemy session
        """
        self.session = session

    async def index_document(
        self,
        entry_id: UUID,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """Index a document using PostgreSQL tsvector.

        Stores the document content and metadata in a searchDocuments
        table with tsvector for full-text search.

        Args:
            entry_id: UUID of the knowledge entry
            content: Text content to index
            metadata: Optional metadata dict
        """
        from app.domains.knowledge.models import KnowledgeEntry

        # Verify entry exists
        result = await self.session.execute(
            select(KnowledgeEntry).where(KnowledgeEntry.id == entry_id)
        )
        entry = result.scalar_one_or_none()

        if not entry:
            raise ValueError(f"KnowledgeEntry {entry_id} not found")

        # Use raw SQL for tsvector creation
        # Insert or update on conflict
        await self.session.execute(
            text("""
                INSERT INTO knowledge_fts_documents (entry_id, content, metadata, search_vector)
                VALUES (:entry_id, :content, :metadata, to_tsvector('english', :content))
                ON CONFLICT (entry_id) DO UPDATE SET
                    content = EXCLUDED.content,
                    metadata = EXCLUDED.metadata,
                    search_vector = to_tsvector('english', EXCLUDED.content),
                    updated_at = NOW()
            """),
            {
                "entry_id": str(entry_id),
                "content": content,
                "metadata": metadata,
            }
        )
        await self.session.flush()

    async def search(
        self,
        query: str,
        top_k: int,
        filters: dict | None = None,
    ) -> list[FTSearchResult]:
        """Search using PostgreSQL full-text search.

        Uses websearch_to_tsquery for natural language query parsing
        and ts_rank for relevance scoring.

        Args:
            query: Search query string
            top_k: Number of results to return
            filters: Optional filters (tenant_id, project_id, entry_type, etc.)

        Returns:
            List of FTSearchResult ordered by relevance rank
        """
        # Build the search query with ranking
        query_template = """
            SELECT
                f.entry_id,
                ts_rank(f.search_vector, query) as rank,
                ts_headline('english', f.content, query, 'StartSel=<mark>, StopSel=</mark>, MaxWords=50, MinWords=20') as headline,
                f.metadata
            FROM knowledge_fts_documents f,
                 websearch_to_tsquery('english', :query) query
            WHERE f.search_vector @@ query
            AND f.deleted_at IS NULL
        """

        params = {"query": query, "top_k": top_k}

        # Apply filters
        if filters:
            if filters.get("tenant_id"):
                query_template += """
                    AND f.entry_id IN (
                        SELECT id FROM knowledge_entries
                        WHERE tenant_id = :tenant_id AND deleted_at IS NULL
                    )
                """
                params["tenant_id"] = str(filters["tenant_id"])
            if filters.get("project_id"):
                query_template += """
                    AND f.entry_id IN (
                        SELECT id FROM knowledge_entries
                        WHERE project_id = :project_id AND deleted_at IS NULL
                    )
                """
                params["project_id"] = str(filters["project_id"])
            if filters.get("entry_type"):
                query_template += """
                    AND f.entry_id IN (
                        SELECT id FROM knowledge_entries
                        WHERE entry_type = :entry_type AND deleted_at IS NULL
                    )
                """
                params["entry_type"] = filters["entry_type"]
            if filters.get("source_file_ids"):
                placeholders = ", ".join([f":source_file_{i}" for i in range(len(filters["source_file_ids"]))])
                query_template += f"""
                    AND f.entry_id IN (
                        SELECT id FROM knowledge_entries
                        WHERE source_file_id IN ({placeholders}) AND deleted_at IS NULL
                    )
                """
                for i, sfid in enumerate(filters["source_file_ids"]):
                    params[f"source_file_{i}"] = str(sfid)

        query_template += " ORDER BY rank DESC LIMIT :top_k"

        result = await self.session.execute(text(query_template), params)
        rows = result.fetchall()

        return [
            FTSearchResult(
                entry_id=row[0],
                rank=float(row[1]) if row[1] is not None else 0.0,
                headline=row[2],
                metadata=row[3] if len(row) > 3 else None,
            )
            for row in rows
        ]

    async def delete_document(self, entry_id: UUID) -> None:
        """Delete a document from the search index.

        Args:
            entry_id: UUID of the knowledge entry
        """
        from app.domains.knowledge.models import FTSDocument

        result = await self.session.execute(
            select(FTSDocument).where(FTSDocument.entry_id == entry_id)
        )
        doc = result.scalar_one_or_none()

        if doc:
            doc.deleted_at = datetime.now(timezone.utc)
            await self.session.flush()

    async def reindex_entry(self, entry_id: UUID) -> None:
        """Reindex an entry by deleting and recreating.

        Args:
            entry_id: UUID of the knowledge entry
        """
        await self.delete_document(entry_id)

        from app.domains.knowledge.models import KnowledgeEntry

        result = await self.session.execute(
            select(KnowledgeEntry).where(KnowledgeEntry.id == entry_id)
        )
        entry = result.scalar_one_or_none()

        if entry:
            await self.index_document(entry_id, entry.content, entry.metadata_json)