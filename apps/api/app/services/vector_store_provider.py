"""Vector Store Provider

Abstract and concrete implementations for vector storage and similarity search.
"""

import json
from abc import ABC, abstractmethod
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.knowledge.schemas import VectorSearchResult


class VectorStoreProvider(ABC):
    """Abstract base class for vector store providers."""

    @abstractmethod
    async def upsert_vector(
        self,
        entry_id: UUID,
        embedding: list[float],
        metadata: dict | None = None,
    ) -> None:
        """Insert or update a vector embedding.

        Args:
            entry_id: UUID of the knowledge entry
            embedding: Vector embedding as list of floats
            metadata: Optional metadata dict
        """
        pass

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict | None = None,
    ) -> list[VectorSearchResult]:
        """Search for similar vectors.

        Args:
            query_embedding: Query vector embedding
            top_k: Number of results to return
            filters: Optional filters (tenant_id, project_id, etc.)

        Returns:
            List of VectorSearchResult
        """
        pass

    @abstractmethod
    async def delete_vector(self, entry_id: UUID) -> None:
        """Delete a vector by entry ID.

        Args:
            entry_id: UUID of the knowledge entry
        """
        pass

    @abstractmethod
    async def get_vector(self, entry_id: UUID) -> list[float] | None:
        """Get vector embedding by entry ID.

        Args:
            entry_id: UUID of the knowledge entry

        Returns:
            Vector embedding as list of floats or None if not found
        """
        pass


class PGVectorProvider(VectorStoreProvider):
    """PostgreSQL pgvector implementation of VectorStoreProvider.

    Uses the knowledge_vectors table for vector storage and performs
    cosine similarity search using the <=> operator.
    """

    def __init__(self, session: AsyncSession):
        """Initialize PGVector provider.

        Args:
            session: Async SQLAlchemy session
        """
        self.session = session

    async def upsert_vector(
        self,
        entry_id: UUID,
        embedding: list[float],
        metadata: dict | None = None,
    ) -> None:
        """Insert or update vector using knowledge_vectors table.

        Args:
            entry_id: UUID of the knowledge entry
            embedding: Vector embedding as list of floats
            metadata: Optional metadata dict (used for vector_index)
        """
        from app.domains.knowledge.models import KnowledgeVector

        vector_index = metadata.get("vector_index") if metadata else None

        # Check if vector exists
        result = await self.session.execute(
            select(KnowledgeVector).where(KnowledgeVector.entry_id == entry_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.vector_embedding = embedding
            if vector_index:
                existing.vector_index = vector_index
        else:
            # Get tenant_id from the knowledge entry
            from app.domains.knowledge.models import KnowledgeEntry

            entry_result = await self.session.execute(
                select(KnowledgeEntry).where(KnowledgeEntry.id == entry_id)
            )
            entry = entry_result.scalar_one_or_none()

            if not entry:
                raise ValueError(f"KnowledgeEntry {entry_id} not found")

            vector = KnowledgeVector(
                tenant_id=entry.tenant_id,
                entry_id=entry_id,
                vector_embedding=embedding,
                vector_index=vector_index,
            )
            self.session.add(vector)

        await self.session.flush()

    async def search(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict | None = None,
    ) -> list[VectorSearchResult]:
        """Search for similar vectors using cosine similarity.

        Uses the <=> (cosine distance) operator for similarity search.
        Results are ordered by similarity score (1 - cosine_distance).

        Args:
            query_embedding: Query vector embedding
            top_k: Number of results to return
            filters: Optional filters (tenant_id, project_id, entry_type, etc.)

        Returns:
            List of VectorSearchResult ordered by similarity
        """
        from app.domains.knowledge.models import KnowledgeVector, KnowledgeEntry

        # Build the query with cosine similarity
        # Using 1 - (vector <=> embedding) for cosine similarity score
        embedding_json = json.dumps(query_embedding)

        query = text("""
            SELECT
                kv.entry_id,
                1 - (kv.vector_embedding <=> :embedding::vector) as similarity,
                kv.metadata
            FROM knowledge_vectors kv
            JOIN knowledge_entries ke ON ke.id = kv.entry_id
            WHERE kv.deleted_at IS NULL
            AND ke.deleted_at IS NULL
        """)

        params = {"embedding": embedding_json}

        # Apply filters
        conditions = []
        if filters:
            if filters.get("tenant_id"):
                conditions.append("ke.tenant_id = :tenant_id")
                params["tenant_id"] = str(filters["tenant_id"])
            if filters.get("project_id"):
                conditions.append("ke.project_id = :project_id")
                params["project_id"] = str(filters["project_id"])
            if filters.get("entry_type"):
                conditions.append("ke.entry_type = :entry_type")
                params["entry_type"] = filters["entry_type"]
            if filters.get("entry_ids"):
                placeholders = ", ".join([f":entry_id_{i}" for i in range(len(filters["entry_ids"]))])
                conditions.append(f"kv.entry_id IN ({placeholders})")
                for i, eid in enumerate(filters["entry_ids"]):
                    params[f"entry_id_{i}"] = str(eid)

        if conditions:
            query = text(str(query) + " AND " + " AND ".join(conditions))

        query = text(str(query) + " ORDER BY similarity DESC LIMIT :top_k")
        params["top_k"] = top_k

        result = await self.session.execute(query, params)
        rows = result.fetchall()

        return [
            VectorSearchResult(
                entry_id=row[0],
                score=float(row[1]) if row[1] is not None else 0.0,
                metadata=row[2] if len(row) > 2 else None,
            )
            for row in rows
        ]

    async def delete_vector(self, entry_id: UUID) -> None:
        """Delete vector by entry ID.

        Args:
            entry_id: UUID of the knowledge entry
        """
        from app.domains.knowledge.models import KnowledgeVector

        result = await self.session.execute(
            select(KnowledgeVector).where(KnowledgeVector.entry_id == entry_id)
        )
        vector = result.scalar_one_or_none()

        if vector:
            await self.session.delete(vector)
            await self.session.flush()

    async def get_vector(self, entry_id: UUID) -> list[float] | None:
        """Get vector embedding by entry ID.

        Args:
            entry_id: UUID of the knowledge entry

        Returns:
            Vector embedding as list of floats or None if not found
        """
        from app.domains.knowledge.models import KnowledgeVector

        result = await self.session.execute(
            select(KnowledgeVector).where(KnowledgeVector.entry_id == entry_id)
        )
        vector = result.scalar_one_or_none()

        return vector.vector_embedding if vector else None