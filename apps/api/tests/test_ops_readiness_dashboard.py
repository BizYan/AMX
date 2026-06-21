"""Ops readiness dashboard and release evidence console tests."""

import ast
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.domains.ops.schemas import (
    CapabilityCommissioningResponse,
    CapabilityReadinessResponse,
)
from app.domains.providers.schemas import ProviderReadinessSummary


_RELEASE_EVIDENCE_ENV_NAMES = (
    "AMX_RELEASE_EVIDENCE_FILE",
    "AMX_ENVIRONMENT_LABEL",
    "AMX_DEPLOYED_REF",
    "AMX_DEPLOYED_SHA",
    "AMX_EXPECTED_SHA",
    "AMX_RELEASE_TAG",
    "AMX_CANDIDATE_VERIFICATION_RUN_URL",
    "AMX_PRODUCTION_DEPLOYMENT_RUN_URL",
    "AMX_LAST_AUTHENTICATED_SMOKE_STATUS",
    "AMX_LAST_AUTHENTICATED_SMOKE_RUN_URL",
    "AMX_DEPLOYMENT_PROVENANCE_STATUS",
    "AMX_GITNEXUS_REFRESH_STATUS",
    "AMX_GITNEXUS_INDEXED_SHA",
    "DEPLOYED_REF",
    "DEPLOYED_SHA",
    "EXPECTED_SHA",
    "GIT_COMMIT",
    "ENVIRONMENT",
)


def clear_release_evidence_env(monkeypatch) -> None:
    for name in _RELEASE_EVIDENCE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


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

    clear_release_evidence_env(monkeypatch)
    monkeypatch.setenv("AMX_DEPLOYED_REF", "v1.0.1")
    monkeypatch.setenv("AMX_DEPLOYED_SHA", "a" * 40)
    monkeypatch.setenv("AMX_EXPECTED_SHA", "a" * 40)
    monkeypatch.setenv("AMX_RELEASE_TAG", "v1.0.1")
    monkeypatch.setenv("AMX_ENVIRONMENT_LABEL", "production")
    monkeypatch.setenv(
        "AMX_CANDIDATE_VERIFICATION_RUN_URL",
        "https://github.com/BizYan/AMX/actions/runs/1001",
    )
    monkeypatch.setenv(
        "AMX_PRODUCTION_DEPLOYMENT_RUN_URL",
        "https://github.com/BizYan/AMX/actions/runs/1002",
    )
    monkeypatch.setenv("AMX_LAST_AUTHENTICATED_SMOKE_STATUS", "passed")
    monkeypatch.setenv(
        "AMX_LAST_AUTHENTICATED_SMOKE_RUN_URL",
        "https://github.com/BizYan/AMX/actions/runs/1002",
    )
    monkeypatch.setenv("AMX_DEPLOYMENT_PROVENANCE_STATUS", "passed")
    monkeypatch.setenv("AMX_GITNEXUS_REFRESH_STATUS", "passed")
    monkeypatch.setenv("AMX_GITNEXUS_INDEXED_SHA", "a" * 40)
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
    assert result.release_evidence.status == "blocked"
    assert result.release_evidence.sha_matches is True
    assert result.release_evidence.environment == "production"
    assert result.release_evidence.release_tag == "v1.0.1"
    assert result.evidence_export["sanitized"] is True
    assert "must-not-leak" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_ops_readiness_dashboard_reports_unrecorded_runtime_evidence(monkeypatch):
    from app.domains.ops.readiness_dashboard import OpsReadinessDashboardService

    clear_release_evidence_env(monkeypatch)

    service = OpsReadinessDashboardService(AsyncMock())

    assert service._build_deployment_evidence()["status"] == "not_recorded"
    assert service._build_smoke_evidence()["status"] == "not_recorded"
    assert service._build_gitnexus_evidence()["refresh_status"] == "not_recorded"
    release_evidence = service._build_release_evidence(
        provider_production_ready=False,
        capability_production_ready=False,
        quota_status="not_recorded",
        critical_failures=[],
        generated_at=datetime.now(timezone.utc),
    )
    assert release_evidence.status == "not_recorded"


def test_release_evidence_manifest_is_allowlisted_and_overrides_environment(monkeypatch, tmp_path: Path):
    from app.domains.ops.readiness_dashboard import OpsReadinessDashboardService

    clear_release_evidence_env(monkeypatch)
    manifest_path = tmp_path / "release-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "environment": "candidate",
                "deployed_ref": "v1.1.0-rc1",
                "deployed_sha": "b" * 40,
                "expected_sha": "b" * 40,
                "release_tag": "v1.1.0-rc1",
                "candidate_verification_run_url": "https://github.com/BizYan/AMX/actions/runs/2001",
                "production_deployment_run_url": "https://github.com/BizYan/AMX/actions/runs/2002",
                "authenticated_smoke_run_url": "https://github.com/BizYan/AMX/actions/runs/2002",
                "smoke_status": "passed",
                "provenance_status": "passed",
                "gitnexus_status": "passed",
                "gitnexus_indexed_sha": "b" * 40,
                "exported_at": "2026-06-21T01:00:00Z",
                "api_key": "must-not-leak",
                "raw_prompt": "must-not-leak",
                "customer_content": "must-not-leak",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AMX_RELEASE_EVIDENCE_FILE", str(manifest_path))
    monkeypatch.setenv("AMX_DEPLOYED_SHA", "a" * 40)

    evidence = OpsReadinessDashboardService(AsyncMock())._build_release_evidence(
        provider_production_ready=True,
        capability_production_ready=True,
        quota_status="healthy",
        critical_failures=[],
        generated_at=datetime.now(timezone.utc),
    )

    payload = evidence.model_dump_json()
    assert evidence.status == "ready"
    assert evidence.deployed_sha == "b" * 40
    assert evidence.source == "sanitized_manifest"
    assert "must-not-leak" not in payload
    assert "api_key" not in payload
    assert "raw_prompt" not in payload
    assert "customer_content" not in payload


def test_release_evidence_blocks_sha_mismatch(monkeypatch):
    from app.domains.ops.readiness_dashboard import OpsReadinessDashboardService

    clear_release_evidence_env(monkeypatch)
    monkeypatch.setenv("AMX_DEPLOYED_SHA", "a" * 40)
    monkeypatch.setenv("AMX_EXPECTED_SHA", "b" * 40)
    monkeypatch.setenv("AMX_LAST_AUTHENTICATED_SMOKE_STATUS", "passed")
    monkeypatch.setenv("AMX_DEPLOYMENT_PROVENANCE_STATUS", "passed")
    monkeypatch.setenv("AMX_GITNEXUS_REFRESH_STATUS", "passed")
    monkeypatch.setenv("AMX_GITNEXUS_INDEXED_SHA", "a" * 40)

    evidence = OpsReadinessDashboardService(AsyncMock())._build_release_evidence(
        provider_production_ready=True,
        capability_production_ready=True,
        quota_status="healthy",
        critical_failures=[],
        generated_at=datetime.now(timezone.utc),
    )

    assert evidence.status == "blocked"
    assert evidence.sha_matches is False
    assert "sha_mismatch" in {blocker.code for blocker in evidence.blockers}


def test_release_evidence_invalid_manifest_fails_closed(monkeypatch, tmp_path: Path):
    from app.domains.ops.readiness_dashboard import OpsReadinessDashboardService

    clear_release_evidence_env(monkeypatch)
    manifest_path = tmp_path / "release-evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "deployed_sha": "not-a-sha",
                "smoke_status": "passed",
                "candidate_verification_run_url": "https://github.com:invalid/BizYan/AMX/actions/runs/1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AMX_RELEASE_EVIDENCE_FILE", str(manifest_path))

    evidence = OpsReadinessDashboardService(AsyncMock())._build_release_evidence(
        provider_production_ready=True,
        capability_production_ready=True,
        quota_status="healthy",
        critical_failures=[],
        generated_at=datetime.now(timezone.utc),
    )

    assert evidence.status == "attention"
    assert evidence.deployed_sha is None
    assert evidence.candidate_verification_run_url is None


def test_release_evidence_never_reads_environment_files(monkeypatch, tmp_path: Path):
    from app.domains.ops.readiness_dashboard import OpsReadinessDashboardService

    clear_release_evidence_env(monkeypatch)
    env_file = tmp_path / ".env.production"
    env_file.write_text(json.dumps({"deployed_sha": "a" * 40}), encoding="utf-8")
    monkeypatch.setenv("AMX_RELEASE_EVIDENCE_FILE", str(env_file))

    evidence = OpsReadinessDashboardService(AsyncMock())._build_release_evidence(
        provider_production_ready=True,
        capability_production_ready=True,
        quota_status="healthy",
        critical_failures=[],
        generated_at=datetime.now(timezone.utc),
    )

    assert evidence.status == "not_recorded"
    assert evidence.deployed_sha is None


def test_release_evidence_export_route_is_get_only():
    router_path = Path(__file__).parents[1] / "app" / "domains" / "ops" / "router.py"
    module = ast.parse(router_path.read_text(encoding="utf-8"))
    endpoint = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "export_ops_release_evidence"
    )
    decorators = [decorator for decorator in endpoint.decorator_list if isinstance(decorator, ast.Call)]

    assert len(decorators) == 1
    assert isinstance(decorators[0].func, ast.Attribute)
    assert decorators[0].func.attr == "get"
    assert ast.literal_eval(decorators[0].args[0]) == "/readiness-dashboard/evidence"
    response_model = next(keyword.value for keyword in decorators[0].keywords if keyword.arg == "response_model")
    assert isinstance(response_model, ast.Name)
    assert response_model.id == "OpsReleaseEvidenceExportResponse"
