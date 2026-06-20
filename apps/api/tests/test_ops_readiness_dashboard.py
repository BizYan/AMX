"""Ops readiness dashboard evidence aggregation tests."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.domains.ops.schemas import (
    CapabilityCommissioningResponse,
    CapabilityReadinessResponse,
)
from app.domains.providers.schemas import ProviderReadinessSummary


@pytest.mark.asyncio
async def test_ops_readiness_dashboard_aggregates_sanitized_evidence(monkeypatch):
    from app.domains.ops.readiness_dashboard import OpsReadinessDashboardService

    tenant_id = uuid4()
    generated_at = datetime.now(timezone.utc)
    readiness = CapabilityReadinessResponse(
        generated_at=generated_at,
        tenant_id=tenant_id,
        overall_status="degraded",
        overall_score=82,
        production_ready=False,
        capabilities=[],
    )
    commissioning = CapabilityCommissioningResponse(
        generated_at=generated_at,
        tenant_id=tenant_id,
        production_usable=False,
        executed=False,
        overall_status="degraded",
        overall_score=78,
        readiness=readiness,
        checks=[],
        summary={},
        next_steps=[],
    )
    provider_readiness = ProviderReadinessSummary(
        tenant_id=tenant_id,
        total_providers=1,
        live_providers=1,
        sandbox_providers=0,
        mock_providers=0,
        unconfigured_providers=0,
        inactive_providers=0,
        degraded_providers=0,
        failed_providers=0,
        readiness_score=100,
        production_ready=True,
        missing_required_types=[],
        required_types=[],
        items=[],
        recommended_actions=[],
    )

    monkeypatch.setenv("AMX_DEPLOYED_REF", "v1.0.1")
    monkeypatch.setenv("AMX_DEPLOYED_SHA", "a" * 40)
    monkeypatch.setenv("AMX_LAST_AUTHENTICATED_SMOKE_STATUS", "passed")
    monkeypatch.setenv("AMX_GITNEXUS_REFRESH_STATUS", "passed")
    monkeypatch.setenv("AMX_GITNEXUS_SERVICE_KEY", "must-not-leak")

    with (
        patch.object(OpsReadinessDashboardService, "_build_provider_readiness", AsyncMock(return_value=provider_readiness)),
        patch.object(OpsReadinessDashboardService, "_build_capability_readiness", AsyncMock(return_value=readiness)),
        patch.object(OpsReadinessDashboardService, "_build_capability_commissioning", AsyncMock(return_value=commissioning)),
        patch.object(
            OpsReadinessDashboardService,
            "_build_quota",
            AsyncMock(return_value={"status": "attention", "used": 8, "limit": 10, "usage_percent": 80.0}),
        ),
        patch.object(
            OpsReadinessDashboardService,
            "_build_metrics",
            AsyncMock(return_value={"total_api_calls_24h": 12, "error_rate_percent": 0.0, "avg_latency_ms": 25.0}),
        ),
        patch.object(
            OpsReadinessDashboardService,
            "_build_alerts",
            AsyncMock(return_value={"active_rules": 1, "failed_notifications": 0, "pending_notifications": 0}),
        ),
        patch.object(
            OpsReadinessDashboardService,
            "_build_agent_run_health",
            AsyncMock(return_value={"status": "healthy", "running": 1, "failed_24h": 0, "completed_24h": 2}),
        ),
        patch.object(
            OpsReadinessDashboardService,
            "_build_latest_critical_failures",
            AsyncMock(return_value=[]),
        ),
    ):
        result = await OpsReadinessDashboardService(AsyncMock()).build(tenant_id)

    assert result.health["status"] == "healthy"
    assert result.provider_readiness.production_ready is True
    assert result.capability_readiness.overall_score == 82
    assert result.quota["usage_percent"] == 80.0
    assert result.deployment["ref"] == "v1.0.1"
    assert result.latest_smoke["status"] == "passed"
    assert result.gitnexus["refresh_status"] == "passed"
    assert result.agent_run_health["status"] == "healthy"
    assert result.evidence_export["sanitized"] is True
    assert "must-not-leak" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_ops_readiness_dashboard_reports_unrecorded_runtime_evidence(monkeypatch):
    from app.domains.ops.readiness_dashboard import OpsReadinessDashboardService

    monkeypatch.delenv("AMX_DEPLOYED_REF", raising=False)
    monkeypatch.delenv("AMX_DEPLOYED_SHA", raising=False)
    monkeypatch.delenv("AMX_LAST_AUTHENTICATED_SMOKE_STATUS", raising=False)
    monkeypatch.delenv("AMX_GITNEXUS_REFRESH_STATUS", raising=False)

    service = OpsReadinessDashboardService(AsyncMock())

    assert service._build_deployment_evidence()["status"] == "not_recorded"
    assert service._build_smoke_evidence()["status"] == "not_recorded"
    assert service._build_gitnexus_evidence()["refresh_status"] == "not_recorded"
