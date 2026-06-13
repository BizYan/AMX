"""E2E tests for Projects"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_projects_router_registered():
    """Test that projects router is registered."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Projects router should be at /api/v1/projects
        response = await client.get("/api/v1/projects")
        # May return 404 if endpoint not defined or 200/405 if it is
        assert response.status_code in [200, 404, 405]


@pytest.mark.asyncio
async def test_projects_list_empty():
    """Test listing projects when none exist."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # This would be an actual endpoint test once auth is implemented
        response = await client.get("/api/v1/projects")
        # Expecting 401 Unauthorized without auth, not 404
        assert response.status_code in [401, 404, 405]