"""Knowledge Graph Tool Adapter

Provides tool adapter for querying and building knowledge graphs.
"""

import re
from typing import Any

from app.domains.agent.tools.base import BaseToolAdapter, ToolExecutionError


class KnowledgeGraphToolAdapter(BaseToolAdapter):
    """Tool adapter for knowledge graph operations.

    Supports:
    - Query knowledge entries
    - Search by semantic similarity
    - Build entity relationships
    """

    @property
    def tool_name(self) -> str:
        return "knowledge_graph"

    async def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute knowledge graph query.

        Args:
            input_data: {
                "action": "query" | "search" | "build",
                "params": {...}
            }

        Returns:
            {"success": bool, "data": Any, "error": str | None}
        """
        action = input_data.get("action", "query")

        try:
            if action == "query":
                return await self._query_entries(input_data)
            elif action == "search":
                return await self._semantic_search(input_data)
            elif action == "build":
                return await self._build_graph(input_data)
            else:
                raise ToolExecutionError(
                    f"Unknown action: {action}",
                    tool_name=self.tool_name,
                )
        except ToolExecutionError:
            raise
        except Exception as e:
            raise ToolExecutionError(
                str(e),
                tool_name=self.tool_name,
                details={"action": action, "input": input_data},
            )

    async def _query_entries(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Query knowledge entries from database."""
        from uuid import UUID
        from sqlalchemy import select, and_
        from app.db.session import AsyncSessionLocal
        from app.domains.knowledge.models import KnowledgeEntry

        project_id = input_data.get("project_id")
        entry_type = input_data.get("entry_type")
        limit = input_data.get("limit", 50)

        async with AsyncSessionLocal() as db:
            query = select(KnowledgeEntry).where(KnowledgeEntry.deleted_at.is_(None))
            if project_id:
                query = query.where(KnowledgeEntry.project_id == UUID(project_id))
            if entry_type:
                query = query.where(KnowledgeEntry.entry_type == entry_type)

            query = query.limit(limit)
            result = await db.execute(query)
            entries = list(result.scalars().all())

        return {
            "success": True,
            "data": {
                "entries": [
                    {
                        "id": str(e.id),
                        "entry_type": e.entry_type,
                        "content": e.content,
                        "metadata": e.metadata_json or {},
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                    }
                    for e in entries
                ],
                "count": len(entries),
            },
        }

    async def _semantic_search(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Search knowledge entries with deterministic lexical relevance scoring."""
        query_text = str(input_data.get("query", "")).strip()
        limit = int(input_data.get("limit", 10) or 10)
        project_id = input_data.get("project_id")

        if not query_text:
            raise ToolExecutionError("query is required for search", tool_name=self.tool_name)

        from uuid import UUID
        from sqlalchemy import select
        from app.db.session import AsyncSessionLocal
        from app.domains.knowledge.models import KnowledgeEntry

        async with AsyncSessionLocal() as db:
            stmt = select(KnowledgeEntry).where(KnowledgeEntry.deleted_at.is_(None))
            if project_id:
                stmt = stmt.where(KnowledgeEntry.project_id == UUID(str(project_id)))
            result = await db.execute(stmt.limit(max(limit * 5, 50)))
            entries = list(result.scalars().all())
            ranked = self._rank_entries(entries, query_text=query_text, limit=limit)

        return {
            "success": True,
            "summary": f"Found {len(ranked)} knowledge entrie(s) matching: {query_text}",
            "data": {
                "query": query_text,
                "results": [
                    {
                        "id": str(e.id),
                        "entry_type": e.entry_type,
                        "content": e.content[:200],
                        "metadata": e.metadata_json or {},
                        "relevance_score": score,
                        "similarity": score,
                        "match_terms": match_terms,
                    }
                    for e, score, match_terms in ranked
                ],
                "count": len(ranked),
                "scoring": "lexical_relevance",
            },
        }

    def _rank_entries(
        self,
        entries: list[Any],
        *,
        query_text: str,
        limit: int,
    ) -> list[tuple[Any, float, list[str]]]:
        query_terms = _tokenize(query_text)
        if not query_terms:
            return []

        ranked: list[tuple[Any, float, list[str]]] = []
        normalized_query = " ".join(query_terms)
        for entry in entries:
            metadata = entry.metadata_json or {}
            haystack = " ".join(
                [
                    str(entry.content or ""),
                    str(metadata.get("title") or ""),
                    str(metadata.get("name") or ""),
                    str(metadata.get("summary") or ""),
                    str(metadata.get("source") or ""),
                    str(metadata.get("filename") or ""),
                ]
            )
            haystack_terms = set(_tokenize(haystack))
            matched = sorted(term for term in set(query_terms) if term in haystack_terms)
            if not matched:
                continue
            score = len(matched) / len(set(query_terms))
            if normalized_query and normalized_query in " ".join(_tokenize(haystack)):
                score = min(1.0, score + 0.25)
            ranked.append((entry, round(score, 4), matched))

        return sorted(ranked, key=lambda item: item[1], reverse=True)[:limit]

    async def _build_graph(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Build knowledge graph from entries."""
        from uuid import UUID
        from sqlalchemy import select
        from app.db.session import AsyncSessionLocal
        from app.domains.knowledge.models import KnowledgeEntry, KnowledgeLink

        project_id = input_data.get("project_id")
        if not project_id:
            return {"success": False, "error": "project_id required"}

        async with AsyncSessionLocal() as db:
            # Get all entries for project
            entries_result = await db.execute(
                select(KnowledgeEntry).where(
                    KnowledgeEntry.project_id == UUID(project_id),
                    KnowledgeEntry.deleted_at.is_(None),
                )
            )
            entries = list(entries_result.scalars().all())

            # Get all links
            entry_ids = [e.id for e in entries]
            links_result = await db.execute(
                select(KnowledgeLink).where(
                    KnowledgeLink.source_entry_id.in_(entry_ids),
                    KnowledgeLink.target_entry_id.in_(entry_ids),
                )
            )
            links = list(links_result.scalars().all())

        nodes = [
            {
                "id": str(e.id),
                "type": e.entry_type,
                "label": e.content[:50] + "...",
            }
            for e in entries
        ]
        edges = [
            {
                "id": str(l.id),
                "source": str(l.source_entry_id),
                "target": str(l.target_entry_id),
                "type": l.link_type,
            }
            for l in links
        ]

        return {
            "success": True,
            "data": {
                "nodes": nodes,
                "edges": edges,
                "node_count": len(nodes),
                "edge_count": len(edges),
            },
        }


def _tokenize(value: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[\w\u4e00-\u9fff]+", value or "") if token.strip()]
