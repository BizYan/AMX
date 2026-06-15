"""Core capability readiness and provider production-gate tests."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from app.domains.integrations.models import IntegrationProvider
from app.domains.ops.capability_readiness import CapabilityReadinessService
from app.domains.providers.models import Provider, ProviderStatus, ProviderType
from app.domains.providers.router import test_provider as call_test_provider
from app.domains.providers.schemas import ProviderTestRequest


class FakeExecuteResult:
    """Tiny SQLAlchemy result double for service-level tests."""

    def __init__(self, *, rows=None, count: int | None = None):
        self._rows = rows or []
        self._count = count

    def scalar_one_or_none(self):
        return self._count

    def scalars(self):
        result = MagicMock()
        result.all.return_value = self._rows
        return result


def make_provider(
    *,
    name="MiniMax Live",
    provider_type=ProviderType.LLM.value,
    status=ProviderStatus.ACTIVE.value,
    config=None,
) -> Provider:
    provider = Provider()
    provider.id = uuid4()
    provider.tenant_id = uuid4()
    provider.name = name
    provider.provider_type = provider_type
    provider.status = status
    provider.config_json = config if config is not None else {"api_key": "live-secret"}
    provider.deleted_at = None
    return provider


def make_integration(config=None, enabled=True) -> IntegrationProvider:
    provider = IntegrationProvider()
    provider.id = uuid4()
    provider.tenant_id = uuid4()
    provider.name = "Jira"
    provider.provider_type = "jira"
    provider.config_json = config if config is not None else {"endpoint": "https://jira.example.test"}
    provider.is_enabled = enabled
    provider.deleted_at = None
    return provider


def count_result(value: int) -> FakeExecuteResult:
    return FakeExecuteResult(count=value)


def test_readiness_counts_managed_runtime_integration_as_configured():
    service = CapabilityReadinessService(AsyncMock())

    assert service._has_integration_endpoint(
        {
            "runtime_ref": "managed-runtime://core-production-loop/tenants/tenant-id",
            "credential_ref": "managed-runtime://core-production-loop/tenants/tenant-id/credentials",
        }
    )


@pytest.mark.asyncio
async def test_provider_test_rejects_sandbox_as_production_ready():
    provider = make_provider(
        name="Sandbox LLM",
        config={"api_key": "mock", "mode": "sandbox"},
    )
    registry = SimpleNamespace(get_provider=AsyncMock(return_value=provider))

    with patch("app.domains.providers.router.get_registry", return_value=registry):
        response = await call_test_provider(
            provider_id=provider.id,
            data=ProviderTestRequest(capability_type="text_generation"),
            db=AsyncMock(),
            current_user=SimpleNamespace(tenant_id=provider.tenant_id),
        )

    assert response.success is False
    assert response.production_ready is False
    assert response.sandbox_fallback is True
    assert response.status == "sandbox"


@pytest.mark.asyncio
async def test_provider_test_allows_explicit_sandbox_probe_without_production_ready():
    provider = make_provider(
        name="Sandbox LLM",
        config={"api_key": "mock", "mode": "sandbox"},
    )
    registry = SimpleNamespace(get_provider=AsyncMock(return_value=provider))

    with patch("app.domains.providers.router.get_registry", return_value=registry):
        response = await call_test_provider(
            provider_id=provider.id,
            data=ProviderTestRequest(capability_type="text_generation", allow_sandbox=True),
            db=AsyncMock(),
            current_user=SimpleNamespace(tenant_id=provider.tenant_id),
        )

    assert response.success is True
    assert response.mode == "sandbox"
    assert response.production_ready is False
    assert response.sandbox_fallback is True


@pytest.mark.asyncio
async def test_gitnexus_provider_test_supports_health_capability():
    provider = make_provider(
        name="GitNexus",
        provider_type=ProviderType.GITNEXUS.value,
        config={
            "endpoint": "http://gitnexus-server:4747",
            "service_key": "live-secret",
            "health_path": "/api/health",
        },
    )
    registry = SimpleNamespace(get_provider=AsyncMock(return_value=provider))

    with (
        patch("app.domains.providers.router.get_registry", return_value=registry),
        patch(
            "app.integrations.gitnexus.adapter.GitNexusProvider.check_health",
            new=AsyncMock(return_value={"status": "ok"}),
        ),
    ):
        response = await call_test_provider(
            provider_id=provider.id,
            data=ProviderTestRequest(capability_type="health", params={"repo_url": "https://github.com/BizYan/AMX"}),
            db=AsyncMock(),
            current_user=SimpleNamespace(tenant_id=provider.tenant_id),
        )

    assert response.success is True
    assert response.status == "connected"
    assert response.capability_type == "health"
    assert response.output == {"status": "ok"}
    assert response.production_ready is True
    assert response.sandbox_fallback is False


@pytest.mark.asyncio
async def test_readiness_blocks_when_core_assets_are_missing():
    sandbox_provider = make_provider(
        name="Mock Provider",
        config={"api_key": "mock", "mode": "sandbox"},
    )
    db = AsyncMock()
    db.execute.side_effect = [
        FakeExecuteResult(rows=[sandbox_provider]),
        *[count_result(0) for _ in range(12)],
        FakeExecuteResult(rows=[]),
        *[count_result(0) for _ in range(14)],
        *[count_result(0) for _ in range(11)],
    ]

    response = await CapabilityReadinessService(db).build(sandbox_provider.tenant_id)

    assert response.overall_status == "blocked"
    assert response.production_ready is False
    provider_capability = next(item for item in response.capabilities if item.key == "provider_llm")
    assert provider_capability.status == "degraded"
    assert provider_capability.evidence["sandbox_provider_count"] == 1


@pytest.mark.asyncio
async def test_readiness_includes_latest_production_gate_capabilities():
    tenant_id = uuid4()
    live_provider = make_provider(config={"api_key": "live-secret", "base_url": "https://api.example.test"})
    live_provider.tenant_id = tenant_id

    db = AsyncMock()
    db.execute.side_effect = [
        FakeExecuteResult(rows=[live_provider]),
        *[count_result(1) for _ in range(40)],
    ]

    response = await CapabilityReadinessService(db).build(tenant_id)

    capability_keys = {item.key for item in response.capabilities}
    assert {
        "external_integration_sync",
        "collaboration_execution",
        "notification_alert_handling",
    } <= capability_keys


@pytest.mark.asyncio
async def test_knowledge_graph_requires_source_lineage_before_ready():
    db = AsyncMock()
    db.execute.side_effect = [
        count_result(0),  # source files
        count_result(5),  # knowledge entries
        count_result(3),  # knowledge links
    ]

    capability = await CapabilityReadinessService(db)._knowledge_capability(uuid4())

    assert capability.key == "knowledge_graph"
    assert capability.status == "degraded"
    assert capability.evidence == {
        "source_file_count": 0,
        "knowledge_entry_count": 5,
        "knowledge_link_count": 3,
    }
    assert any("来源" in blocker or "source" in blocker.lower() for blocker in capability.blockers)


@pytest.mark.asyncio
async def test_readiness_is_ready_when_live_core_assets_exist():
    tenant_id = uuid4()
    live_provider = make_provider(config={"api_key": "live-secret", "base_url": "https://api.example.test"})
    live_provider.tenant_id = tenant_id
    integration = make_integration()
    integration.tenant_id = tenant_id

    db = AsyncMock()
    db.execute.side_effect = [
        FakeExecuteResult(rows=[live_provider]),
        count_result(4),  # documents
        count_result(2),  # generation sessions
        count_result(3),  # templates
        count_result(3),  # template versions
        count_result(12),  # template sections
        count_result(8),  # published skills
        count_result(3),  # active agents
        count_result(2),  # active workflows
        count_result(2),  # active workflow versions
        count_result(20),  # source files
        count_result(50),  # knowledge entries
        count_result(35),  # knowledge links
        FakeExecuteResult(rows=[integration]),
        count_result(1),  # enabled integration project bindings
        count_result(1),  # completed sync runs
        count_result(2),  # synced assets
        count_result(2),  # collaboration work items
        count_result(1),  # done work items
        count_result(1),  # active work items
        count_result(0),  # blocked work items
        count_result(0),  # overdue work items
        count_result(1),  # notification preferences
        count_result(0),  # unacknowledged required notifications
        count_result(0),  # escalated notifications
        count_result(1),  # notification events
        count_result(1),  # sent notification events
        count_result(0),  # failed notification events
        count_result(5),  # export jobs
        count_result(2),  # completed exports
        count_result(4),  # documents for export
        count_result(4),  # active users
        count_result(3),  # roles
        count_result(8),  # audit logs
        count_result(2),  # policies
        count_result(4),  # field permissions
        count_result(12),  # metric events
        count_result(3),  # quota usages
        count_result(2),  # active alert rules
    ]

    response = await CapabilityReadinessService(db).build(tenant_id)

    assert response.overall_status == "ready"
    assert response.production_ready is True
    assert response.overall_score >= 90
    assert all(item.status == "ready" for item in response.capabilities)
    capability_keys = {item.key for item in response.capabilities}
    assert {"team_access", "ops_observability"} <= capability_keys
    team_capability = next(item for item in response.capabilities if item.key == "team_access")
    assert team_capability.evidence["policy_count"] == 2
    assert team_capability.evidence["field_permission_count"] == 4
