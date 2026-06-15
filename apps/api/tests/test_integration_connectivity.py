import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-secret"

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

import app.db.init_schema  # noqa: F401 - registers sqlite compilers for UUID/JSONB
import app.domains.knowledge.models  # noqa: F401 - registers knowledge tables for integration FK targets
import app.models.identity  # noqa: F401 - registers tenant/user tables for FK targets
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.integrations.models import IntegrationInboundEvent, OutboxEvent, WebhookDeliveryEvent, WebhookSubscription
from app.domains.integrations.service import IntegrationService
from app.models.identity import Tenant, User


class FakeResponse:
    def __init__(self, status_code: int = 200, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {"ok": True}
        self.text = str(self._body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeAsyncClient:
    requests: list[tuple[str, str, dict]] = []
    status_code = 200
    body: dict = {"ok": True}

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return FakeResponse(self.status_code, self.body)

    async def post(self, url: str, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return FakeResponse(self.status_code, self.body)


def make_json_request(payload: bytes) -> Request:
    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/integrations/webhooks/inbound",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )


@pytest.fixture
async def db_session():
    deduplicate_indexes()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()


def test_operations_summary_counts_managed_runtime_integration_as_configured():
    service = IntegrationService(db=None)
    config = {
        "runtime_ref": "managed-runtime://core-production-loop/tenants/tenant-id",
        "credential_ref": "managed-runtime://core-production-loop/tenants/tenant-id/credentials",
    }

    assert service._integration_has_endpoint(config)
    assert service._integration_has_auth(config)


@pytest.mark.asyncio
async def test_connection_probes_configured_endpoint_and_masks_credentials(db_session, monkeypatch):
    FakeAsyncClient.requests = []
    FakeAsyncClient.status_code = 200
    FakeAsyncClient.body = {"accountId": "jira-user"}
    monkeypatch.setattr("app.domains.integrations.service.httpx.AsyncClient", FakeAsyncClient)

    tenant_id = uuid4()
    db_session.add(Tenant(id=tenant_id, name="Tenant", slug="tenant-connectivity"))
    service = IntegrationService(db_session)
    integration = await service.create_integration(
        tenant_id=tenant_id,
        provider_type="jira",
        name="Jira",
        config={
            "base_url": "https://jira.example.com",
            "api_key": "super-secret-token",
            "health_path": "/rest/api/2/myself",
            "auth_header": "X-API-Key",
            "auth_scheme": "raw",
        },
    )

    result = await service.test_connection(integration.id, tenant_id)

    assert result["status"] == "connected"
    assert result["details"]["endpoint"] == "https://jira.example.com/rest/api/2/myself"
    assert result["details"]["status_code"] == 200
    assert "super-secret-token" not in str(result)
    method, url, kwargs = FakeAsyncClient.requests[0]
    assert method == "GET"
    assert url == "https://jira.example.com/rest/api/2/myself"
    assert kwargs["headers"]["X-API-Key"] == "super-secret-token"


@pytest.mark.asyncio
async def test_connection_reports_authentication_failure_without_fake_success(db_session, monkeypatch):
    FakeAsyncClient.requests = []
    FakeAsyncClient.status_code = 401
    FakeAsyncClient.body = {"error": "unauthorized"}
    monkeypatch.setattr("app.domains.integrations.service.httpx.AsyncClient", FakeAsyncClient)

    tenant_id = uuid4()
    db_session.add(Tenant(id=tenant_id, name="Tenant", slug="tenant-auth-fail"))
    service = IntegrationService(db_session)
    integration = await service.create_integration(
        tenant_id=tenant_id,
        provider_type="custom",
        name="Custom",
        config={"base_url": "https://api.example.com", "api_key": "bad-key", "health_path": "/health"},
    )

    result = await service.test_connection(integration.id, tenant_id)

    assert result["status"] == "authentication_failed"
    assert "HTTP 401" in result["message"]
    assert result["details"]["endpoint"] == "https://api.example.com/health"


@pytest.mark.asyncio
async def test_inbound_webhook_requires_configured_secret_in_production(db_session, monkeypatch):
    from app.core.settings import settings
    from app.domains.integrations.router import receive_inbound_webhook

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    tenant_id = uuid4()
    db_session.add(Tenant(id=tenant_id, name="Webhook Tenant", slug="webhook-tenant"))
    integration = await IntegrationService(db_session).create_integration(
        tenant_id=tenant_id,
        provider_type="custom",
        name="Unsigned Inbound",
        config={"base_url": "https://hooks.vendor.test", "api_key": "live-secret"},
    )

    request = make_json_request(b'{"event_type":"updated","data":{"id":"AMX-1"}}')

    with pytest.raises(HTTPException) as exc:
        await receive_inbound_webhook(request=request, provider_id=integration.id, db=db_session)

    assert exc.value.status_code == 401
    assert "webhook_secret" in exc.value.detail
    assert await db_session.scalar(select(IntegrationInboundEvent)) is None


@pytest.mark.asyncio
async def test_sync_calls_remote_sync_endpoint_and_records_evidence_event(db_session, monkeypatch):
    FakeAsyncClient.requests = []
    FakeAsyncClient.status_code = 200
    FakeAsyncClient.body = {"synced": 3}
    monkeypatch.setattr("app.domains.integrations.service.httpx.AsyncClient", FakeAsyncClient)

    tenant_id = uuid4()
    db_session.add(Tenant(id=tenant_id, name="Tenant", slug="tenant-sync"))
    service = IntegrationService(db_session)
    integration = await service.create_integration(
        tenant_id=tenant_id,
        provider_type="custom",
        name="Custom sync",
        config={
            "base_url": "https://api.example.com",
            "api_key": "sync-key",
            "health_path": "/health",
            "sync_path": "/sync",
            "sync_method": "POST",
        },
    )

    result = await service.sync_integration(integration.id, tenant_id)

    assert result["success"] is True
    assert result["status"] == "synced"
    assert integration.last_sync_at is not None
    assert ("POST", "https://api.example.com/sync") in [(method, url) for method, url, _ in FakeAsyncClient.requests]

    events = list((await db_session.execute(select(IntegrationInboundEvent))).scalars())
    assert len(events) == 1
    assert events[0].event_type == "integration.sync.completed"
    assert events[0].processed is True
    assert events[0].payload["external_response"] == {"synced": 3}
    assert events[0].payload["endpoint"] == "https://api.example.com/sync"


@pytest.mark.asyncio
async def test_operations_summary_reports_integration_webhook_and_outbox_evidence(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    integration_id = uuid4()
    second_integration_id = uuid4()
    webhook_id = uuid4()

    db_session.add_all([
        Tenant(id=tenant_id, name="Ops Tenant", slug="ops-tenant"),
        User(
            id=user_id,
            tenant_id=tenant_id,
            email="ops@example.com",
            full_name="Ops User",
            hashed_password="hashed",
        ),
        OutboxEvent(
            tenant_id=tenant_id,
            aggregate_type="document",
            aggregate_id=uuid4(),
            event_type="document.published",
            payload={"document_id": "doc-1"},
            published=False,
            status="pending",
        ),
        OutboxEvent(
            tenant_id=tenant_id,
            aggregate_type="document",
            aggregate_id=uuid4(),
            event_type="document.exported",
            payload={"document_id": "doc-2"},
            published=True,
            status="published",
        ),
    ])
    service = IntegrationService(db_session)
    synced = await service.create_integration(
        tenant_id=tenant_id,
        provider_type="jira",
        name="Jira",
        config={"base_url": "https://jira.example.com", "api_key": "key"},
    )
    synced.id = integration_id
    synced.last_sync_at = synced.created_at
    partial = await service.create_integration(
        tenant_id=tenant_id,
        provider_type="custom",
        name="Partial",
        config={"base_url": "https://api.example.com"},
    )
    partial.id = second_integration_id
    db_session.add_all([
        WebhookSubscription(
            id=webhook_id,
            tenant_id=tenant_id,
            integration_provider_id=integration_id,
            url="https://example.com/webhook",
            events=["document.published"],
            is_active=True,
        ),
        WebhookDeliveryEvent(
            tenant_id=tenant_id,
            webhook_subscription_id=webhook_id,
            event_id="evt-success",
            url="https://example.com/webhook",
            request_headers={},
            request_body={},
            response_status=204,
            attempts=1,
        ),
        WebhookDeliveryEvent(
            tenant_id=tenant_id,
            webhook_subscription_id=webhook_id,
            event_id="evt-failed",
            url="https://example.com/webhook",
            request_headers={},
            request_body={},
            response_status=500,
            error_message="server error",
            attempts=3,
        ),
    ])
    await db_session.flush()

    summary = await service.build_operations_summary(tenant_id)

    assert summary.status == "degraded"
    assert summary.score == 72
    assert summary.evidence.integration_count == 2
    assert summary.evidence.configured_integration_count == 1
    assert summary.evidence.synced_integration_count == 1
    assert summary.evidence.active_webhook_count == 1
    assert summary.evidence.failed_delivery_count == 1
    assert summary.evidence.pending_outbox_count == 1
    assert any("Webhook 投递失败" in blocker for blocker in summary.blockers)
    assert any("尚未绑定项目" in blocker for blocker in summary.blockers)

    command_center = await service.build_production_command_center(tenant_id)

    assert command_center.release_gate.status == "blocked"
    assert command_center.summary["failed_delivery_count"] == 1
    assert command_center.summary["pending_outbox_count"] == 1
    assert {item.code for item in command_center.risk_items} >= {
        "failed_webhook_deliveries",
        "pending_outbox",
        "missing_project_bindings",
    }
    assert command_center.priority_actions[0].href == "/integrations"
    assert command_center.operations_summary.evidence.synced_integration_count == 1
