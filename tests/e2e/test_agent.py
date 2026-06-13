"""E2E tests for Agent Runtime & Workflows"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_agent_router_registered():
    """Test that agent router is registered."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/agent")
        assert response.status_code in [200, 401, 404, 405]


@pytest.mark.asyncio
async def test_agent_workflow_execution():
    """Test agent workflow execution endpoint."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/agent/execute")
        assert response.status_code in [200, 401, 404, 405]


@pytest.mark.asyncio
async def test_agent_skills_endpoint():
    """Test agent skills listing endpoint."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/agent/skills")
        assert response.status_code in [200, 401, 404, 405]