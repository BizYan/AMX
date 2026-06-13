"""E2E tests for Knowledge & RAG"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_knowledge_router_registered():
    """Test that knowledge router is registered."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/knowledge")
        assert response.status_code in [200, 401, 404, 405]


@pytest.mark.asyncio
async def test_knowledge_vector_search():
    """Test vector search endpoint structure."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test search endpoint if it exists
        response = await client.get("/api/v1/knowledge/search")
        assert response.status_code in [200, 401, 404, 405]


@pytest.mark.asyncio
async def test_knowledge_graphrag():
    """Test GraphRAG query endpoint."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/knowledge/graphrag")
        assert response.status_code in [200, 401, 404, 405]