"""API router registration contract tests."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/postgres")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from app.api.v1 import api_router


def test_integrations_router_is_registered_under_v1_api():
    paths = {route.path for route in api_router.routes}

    assert "/integrations" in paths
    assert "/integrations/operations/summary" in paths
    assert "/integrations/{integration_id}/test" in paths
    assert "/integrations/{integration_id}/sync" in paths
    assert "/integrations/{integration_id}/project-bindings" in paths
    assert "/integrations/project-bindings/{binding_id}/preview" in paths
    assert "/integrations/project-bindings/{binding_id}/sync" in paths
    assert "/integrations/project-bindings/{binding_id}/runs" in paths
    assert "/integrations/sync-runs/{run_id}/retry" in paths
