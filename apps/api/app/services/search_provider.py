"""Search Provider

Abstract and concrete implementations for full-text search using PostgreSQL FTS.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import re
from uuid import UUID

from sqlalchemy import func, or_, select, text
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

    def _dialect_name(self) -> str:
        bind = self.session.get_bind()
        return bind.dialect.name if bind is not None else ""

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

        if self._dialect_name() != "postgresql":
            from app.domains.knowledge.models import FTSDocument

            existing = (
                await self.session.execute(
                    select(FTSDocument).where(FTSDocument.entry_id == entry_id)
                )
            ).scalar_one_or_none()
            if existing:
                existing.content = content
                existing.metadata_json = metadata
                existing.search_vector = content
                existing.updated_at = datetime.now(timezone.utc)
            else:
                self.session.add(
                    FTSDocument(
                        entry_id=entry_id,
                        content=content,
                        metadata_json=metadata,
                        search_vector=content,
                    )
                )
            await self.session.flush()
            return

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
        if self._dialect_name() != "postgresql":
            return await self._portable_search(query, top_k, filters)

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

    async def _portable_search(
        self,
        query: str,
        top_k: int,
        filters: dict | None = None,
    ) -> list[FTSearchResult]:
        """Run deterministic lexical search for non-PostgreSQL disposable databases."""
        from app.domains.knowledge.models import FTSDocument, KnowledgeEntry

        normalized_query = query.strip().lower()
        terms = [term for term in re.split(r"\W+", normalized_query) if term]
        predicates = [func.lower(FTSDocument.content).contains(normalized_query)]
        predicates.extend(func.lower(FTSDocument.content).contains(term) for term in terms)

        statement = (
            select(FTSDocument, KnowledgeEntry)
            .join(KnowledgeEntry, KnowledgeEntry.id == FTSDocument.entry_id)
            .where(FTSDocument.deleted_at.is_(None), KnowledgeEntry.deleted_at.is_(None))
        )
        if predicates:
            statement = statement.where(or_(*predicates))

        filters = filters or {}
        if filters.get("tenant_id"):
            statement = statement.where(KnowledgeEntry.tenant_id == filters["tenant_id"])
        if filters.get("project_id"):
            statement = statement.where(KnowledgeEntry.project_id == filters["project_id"])
        if filters.get("entry_type"):
            statement = statement.where(KnowledgeEntry.entry_type == filters["entry_type"])
        if filters.get("source_file_ids"):
            statement = statement.where(KnowledgeEntry.source_file_id.in_(filters["source_file_ids"]))

        rows = (await self.session.execute(statement.limit(top_k * 4))).all()
        ranked: list[tuple[int, FTSDocument]] = []
        for document, _entry in rows:
            content_lower = document.content.lower()
            rank = int(normalized_query in content_lower)
            rank += sum(1 for term in terms if term in content_lower)
            ranked.append((rank, document))

        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            FTSearchResult(
                entry_id=document.entry_id,
                rank=float(rank),
                headline=document.content[:240],
                metadata=document.metadata_json,
            )
            for rank, document in ranked[:top_k]
            if rank > 0
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
