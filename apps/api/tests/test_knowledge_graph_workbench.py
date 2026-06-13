"""Knowledge graph workbench service contracts."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.domains.knowledge.models import KnowledgeEntry, KnowledgeLink
from app.domains.knowledge.service import KnowledgeService


def make_entry(*, tenant_id, project_id, title, status="ready", source="source.md"):
    entry = MagicMock(spec=KnowledgeEntry)
    entry.id = uuid4()
    entry.tenant_id = tenant_id
    entry.project_id = project_id
    entry.source_file_id = uuid4()
    entry.entry_type = "text"
    entry.content = f"{title} content"
    entry.content_hash = "a" * 64
    entry.vector_embedding = None
    entry.metadata_json = {
      "title": title,
      "summary": f"{title} summary",
      "sourceFileName": source,
      "state": status,
      "confidence": 0.82,
    }
    if status == "gap":
        entry.metadata_json["gap"] = "missing acceptance evidence"
    if status == "conflict":
        entry.metadata_json["conflict"] = "conflicting timeline"
    entry.sharing_scope = "project"
    entry.created_by_id = uuid4()
    entry.reviewed_by_id = None
    entry.reviewed_at = None
    entry.created_at = datetime.now(timezone.utc)
    entry.updated_at = entry.created_at
    entry.deleted_at = None
    return entry


def make_link(*, tenant_id, source_id, target_id):
    link = MagicMock(spec=KnowledgeLink)
    link.id = uuid4()
    link.tenant_id = tenant_id
    link.source_entry_id = source_id
    link.target_entry_id = target_id
    link.link_type = "depends_on"
    link.confidence = 0.9
    link.metadata_json = {"source": "test"}
    link.created_at = datetime.now(timezone.utc)
    return link


@pytest.mark.asyncio
async def test_graph_workbench_returns_nodes_edges_and_readiness_summary():
    tenant_id = uuid4()
    project_id = uuid4()
    ready = make_entry(tenant_id=tenant_id, project_id=project_id, title="Ready rule")
    gap = make_entry(tenant_id=tenant_id, project_id=project_id, title="Gap evidence", status="gap")
    conflict = make_entry(tenant_id=tenant_id, project_id=project_id, title="Timeline conflict", status="conflict")
    link = make_link(tenant_id=tenant_id, source_id=ready.id, target_id=gap.id)

    entry_result = MagicMock()
    entry_result.scalars.return_value.all.return_value = [ready, gap, conflict]
    link_result = MagicMock()
    link_result.scalars.return_value.all.return_value = [link]

    db = AsyncMock()
    db.execute.side_effect = [entry_result, link_result]

    service = KnowledgeService(db)
    response = await service.get_graph_workbench(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=uuid4(),
    )

    assert response.summary.node_count == 3
    assert response.summary.edge_count == 1
    assert response.summary.ready_count == 1
    assert response.summary.gap_count == 1
    assert response.summary.conflict_count == 1
    assert response.summary.isolated_count == 1
    assert {node.title for node in response.gaps} == {"Gap evidence", "Timeline conflict"}
    assert response.edges[0].source == ready.id
    assert response.edges[0].target == gap.id


@pytest.mark.asyncio
async def test_update_and_delete_link_support_graph_governance():
    tenant_id = uuid4()
    source_id = uuid4()
    target_id = uuid4()
    link = make_link(tenant_id=tenant_id, source_id=source_id, target_id=target_id)

    update_result = MagicMock()
    update_result.scalar_one_or_none.return_value = link
    delete_result = MagicMock()
    delete_result.scalar_one_or_none.return_value = link

    db = AsyncMock()
    db.execute.side_effect = [update_result, delete_result]

    service = KnowledgeService(db)
    updated = await service.update_link(
        link_id=link.id,
        tenant_id=tenant_id,
        link_type="cites",
        confidence=0.7,
        metadata={"reason": "manual correction"},
    )

    assert updated is not None
    assert updated.link_type == "cites"
    assert updated.confidence == 0.7
    assert updated.metadata_json == {"reason": "manual correction"}
    db.refresh.assert_awaited_once_with(link)

    deleted = await service.delete_link(link_id=link.id, tenant_id=tenant_id)

    assert deleted is True
    assert link.deleted_at is not None
    assert db.flush.await_count == 2
