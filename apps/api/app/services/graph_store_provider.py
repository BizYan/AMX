"""Graph Store Provider

Abstract and concrete implementations for graph storage and traversal.
"""

from abc import ABC, abstractmethod
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.knowledge.models import KnowledgeEntry, KnowledgeLink


class GraphStoreProvider(ABC):
    """Abstract base class for graph store providers."""

    @abstractmethod
    async def add_node(self, node: KnowledgeEntry) -> None:
        """Add a node to the graph.

        Args:
            node: KnowledgeEntry to add as a node
        """
        pass

    @abstractmethod
    async def add_edge(
        self,
        source_id: UUID,
        target_id: UUID,
        link_type: str,
        metadata: dict | None = None,
    ) -> KnowledgeLink:
        """Add an edge between two nodes.

        Args:
            source_id: Source entry UUID
            target_id: Target entry UUID
            link_type: Type of link (cites, extends, depends_on, implements)
            metadata: Optional metadata dict

        Returns:
            Created KnowledgeLink
        """
        pass

    @abstractmethod
    async def get_neighbors(
        self,
        entry_id: UUID,
        depth: int = 1,
        direction: str = "both",
    ) -> list[tuple[KnowledgeEntry, KnowledgeLink, int]]:
        """Get neighboring nodes up to a certain depth.

        Args:
            entry_id: Starting entry UUID
            depth: Traversal depth (default 1)
            direction: Traversal direction ("outgoing", "incoming", "both")

        Returns:
            List of tuples (KnowledgeEntry, KnowledgeLink, depth)
        """
        pass

    @abstractmethod
    async def get_path(
        self,
        source_id: UUID,
        target_id: UUID,
        max_depth: int = 10,
    ) -> list[tuple[KnowledgeEntry, KnowledgeLink]]:
        """Find a path between two nodes.

        Args:
            source_id: Source entry UUID
            target_id: Target entry UUID
            max_depth: Maximum path length

        Returns:
            List of tuples (KnowledgeEntry, KnowledgeLink) representing the path
        """
        pass

    @abstractmethod
    async def delete_edge(
        self,
        source_id: UUID,
        target_id: UUID,
    ) -> bool:
        """Delete an edge between two nodes.

        Args:
            source_id: Source entry UUID
            target_id: Target entry UUID

        Returns:
            True if edge was deleted, False if not found
        """
        pass


class PostgresGraphProvider(GraphStoreProvider):
    """PostgreSQL implementation of GraphStoreProvider.

    Uses KnowledgeLink table for edges and recursive CTEs for efficient
    graph traversal. Supports multi-hop navigation and path finding.
    """

    def __init__(self, session: AsyncSession):
        """Initialize Postgres Graph provider.

        Args:
            session: Async SQLAlchemy session
        """
        self.session = session

    async def add_node(self, node: KnowledgeEntry) -> None:
        """Add a node to the graph.

        For PostgresGraphProvider, nodes are added automatically when
        creating KnowledgeEntry. This method is a no-op but included
        for interface compliance.

        Args:
            node: KnowledgeEntry to add as a node
        """
        # Nodes are created via KnowledgeEntry, no action needed
        pass

    async def add_edge(
        self,
        source_id: UUID,
        target_id: UUID,
        link_type: str,
        metadata: dict | None = None,
    ) -> KnowledgeLink:
        """Add an edge between two nodes.

        Args:
            source_id: Source entry UUID
            target_id: Target entry UUID
            link_type: Type of link (cites, extends, depends_on, implements)
            metadata: Optional metadata dict

        Returns:
            Created KnowledgeLink
        """
        # Verify both entries exist
        source_result = await self.session.execute(
            select(KnowledgeEntry).where(KnowledgeEntry.id == source_id)
        )
        source = source_result.scalar_one_or_none()
        if not source:
            raise ValueError(f"Source entry {source_id} not found")

        target_result = await self.session.execute(
            select(KnowledgeEntry).where(KnowledgeEntry.id == target_id)
        )
        target = target_result.scalar_one_or_none()
        if not target:
            raise ValueError(f"Target entry {target_id} not found")

        # Check for existing link
        existing_result = await self.session.execute(
            select(KnowledgeLink).where(
                KnowledgeLink.source_entry_id == source_id,
                KnowledgeLink.target_entry_id == target_id,
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.link_type = link_type
            if metadata:
                existing.metadata_json = metadata
            await self.session.flush()
            return existing

        # Create new link
        link = KnowledgeLink(
            tenant_id=source.tenant_id,
            source_entry_id=source_id,
            target_entry_id=target_id,
            link_type=link_type,
            metadata_json=metadata,
        )
        self.session.add(link)
        await self.session.flush()
        await self.session.refresh(link)
        return link

    async def get_neighbors(
        self,
        entry_id: UUID,
        depth: int = 1,
        direction: str = "both",
    ) -> list[tuple[KnowledgeEntry, KnowledgeLink, int]]:
        """Get neighboring nodes up to a certain depth using recursive CTE.

        Args:
            entry_id: Starting entry UUID
            depth: Traversal depth (default 1, max 10)
            direction: Traversal direction ("outgoing", "incoming", "both")

        Returns:
            List of tuples (KnowledgeEntry, KnowledgeLink, depth)
        """
        depth = min(depth, 10)  # Limit depth to prevent runaway queries

        if direction == "outgoing":
            direction_filter = "kl.source_entry_id = current_id"
        elif direction == "incoming":
            direction_filter = "kl.target_entry_id = current_id"
        else:  # "both"
            direction_filter = "(kl.source_entry_id = current_id OR kl.target_entry_id = current_id)"

        # Use recursive CTE for graph traversal
        query = text(f"""
            WITH RECURSIVE graph_traversal AS (
                -- Base case: start with the initial entry
                SELECT
                    ke.id as entry_id,
                    ke.id as root_id,
                    0 as depth,
                    ARRAY[ke.id] as path
                FROM knowledge_entries ke
                WHERE ke.id = :entry_id AND ke.deleted_at IS NULL

                UNION ALL

                -- Recursive case: traverse to neighbors
                SELECT
                    CASE WHEN kl.source_entry_id = current_id THEN kl.target_entry_id ELSE kl.source_entry_id END,
                    root_id,
                    gt.depth + 1,
                    gt.path || CASE WHEN kl.source_entry_id = current_id THEN kl.target_entry_id ELSE kl.source_entry_id END
                FROM graph_traversal gt
                JOIN knowledge_links kl ON {direction_filter}
                JOIN knowledge_entries neighbor ON neighbor.id = CASE WHEN kl.source_entry_id = current_id THEN kl.target_entry_id ELSE kl.source_entry_id END
                WHERE gt.depth < :depth
                AND neighbor.deleted_at IS NULL
                AND NOT (CASE WHEN kl.source_entry_id = current_id THEN kl.target_entry_id ELSE kl.source_entry_id END = ANY(gt.path))
            )
            SELECT
                ke.id, ke.entry_type, ke.content, ke.content_hash, ke.metadata_json,
                ke.created_at, ke.updated_at, ke.deleted_at,
                ke.tenant_id, ke.project_id, ke.source_file_id,
                kl.id as link_id, kl.link_type, kl.confidence, kl.metadata_json as link_metadata,
                gt.depth
            FROM graph_traversal gt
            JOIN knowledge_entries ke ON ke.id = gt.entry_id
            LEFT JOIN knowledge_links kl ON (
                (kl.source_entry_id = gt.path[array_upper(gt.path, 1) - 1] AND kl.target_entry_id = gt.entry_id)
                OR (kl.target_entry_id = gt.path[array_upper(gt.path, 1) - 1] AND kl.source_entry_id = gt.entry_id)
            )
            WHERE gt.depth > 0
            ORDER BY gt.depth, ke.created_at
        """)

        result = await self.session.execute(query, {"entry_id": str(entry_id), "depth": depth})
        rows = result.fetchall()

        neighbors = []
        for row in rows:
            entry = KnowledgeEntry(
                id=row[0],
                entry_type=row[1],
                content=row[2],
                content_hash=row[3],
                metadata_json=row[4],
                created_at=row[5],
                updated_at=row[6],
                deleted_at=row[7],
                tenant_id=row[8],
                project_id=row[9],
                source_file_id=row[10],
            )

            link = None
            if row[11]:
                link = KnowledgeLink(
                    id=row[11],
                    link_type=row[12],
                    confidence=row[13],
                    metadata_json=row[14] if row[14] else None,
                )

            neighbors.append((entry, link, row[15]))

        return neighbors

    async def get_path(
        self,
        source_id: UUID,
        target_id: UUID,
        max_depth: int = 10,
    ) -> list[tuple[KnowledgeEntry, KnowledgeLink]]:
        """Find a path between two nodes using BFS-style traversal.

        Args:
            source_id: Source entry UUID
            target_id: Target entry UUID
            max_depth: Maximum path length (default 10)

        Returns:
            List of tuples (KnowledgeEntry, KnowledgeLink) representing the path
        """
        max_depth = min(max_depth, 20)  # Limit depth to prevent runaway queries

        # Use recursive CTE to find shortest path
        query = text("""
            WITH RECURSIVE path_finder AS (
                -- Base case: start from source
                SELECT
                    ke.id as current_id,
                    ke.tenant_id as tenant_id,
                    ARRAY[ke.id] as path,
                    ARRAY[]::uuid[] as link_ids,
                    0 as depth
                FROM knowledge_entries ke
                WHERE ke.id = :source_id AND ke.deleted_at IS NULL

                UNION ALL

                -- Recursive case: follow edges
                SELECT
                    CASE WHEN kl.source_entry_id = pf.current_id THEN kl.target_entry_id ELSE kl.source_entry_id END,
                    pf.tenant_id,
                    pf.path || CASE WHEN kl.source_entry_id = pf.current_id THEN kl.target_entry_id ELSE kl.source_entry_id END,
                    pf.link_ids || kl.id,
                    pf.depth + 1
                FROM path_finder pf
                JOIN knowledge_links kl ON kl.source_entry_id = pf.current_id OR kl.target_entry_id = pf.current_id
                JOIN knowledge_entries neighbor ON neighbor.id = CASE WHEN kl.source_entry_id = pf.current_id THEN kl.target_entry_id ELSE kl.source_entry_id END
                WHERE pf.depth < :max_depth
                AND neighbor.deleted_at IS NULL
                AND neighbor.tenant_id = pf.tenant_id
                AND NOT neighbor.id = ANY(pf.path)
            )
            SELECT
                path, link_ids, depth
            FROM path_finder
            WHERE current_id = :target_id
            ORDER BY depth ASC, length(path) ASC
            LIMIT 1
        """)

        result = await self.session.execute(
            query,
            {"source_id": str(source_id), "target_id": str(target_id), "max_depth": max_depth}
        )
        row = result.fetchone()

        if not row:
            return []  # No path found

        path_ids = row[0]
        link_ids = row[1]

        # Fetch all entries in path
        entries_query = select(KnowledgeEntry).where(KnowledgeEntry.id.in_(path_ids))
        entries_result = await self.session.execute(entries_query)
        entries_map = {e.id: e for e in entries_result.scalars().all()}

        # Fetch all links in path
        links_query = select(KnowledgeLink).where(KnowledgeLink.id.in_(link_ids))
        links_result = await self.session.execute(links_query)
        links_map = {l.id: l for l in links_result.scalars().all()}

        # Reconstruct ordered path
        ordered_entries = [entries_map[pid] for pid in path_ids if pid in entries_map]
        ordered_links = [links_map[lid] for lid in link_ids if lid in links_map]

        return list(zip(ordered_entries, ordered_links))

    async def delete_edge(self, source_id: UUID, target_id: UUID) -> bool:
        """Delete an edge between two nodes.

        Args:
            source_id: Source entry UUID
            target_id: Target entry UUID

        Returns:
            True if edge was deleted, False if not found
        """
        result = await self.session.execute(
            select(KnowledgeLink).where(
                KnowledgeLink.source_entry_id == source_id,
                KnowledgeLink.target_entry_id == target_id,
            )
        )
        link = result.scalar_one_or_none()

        if not link:
            return False

        await self.session.delete(link)
        await self.session.flush()
        return True