import os
from datetime import datetime, timezone
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-secret"
os.environ["AMX_TEST_JIRA_API_TOKEN"] = "test-jira-token"

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401
import app.domains.documents.models  # noqa: F401
import app.models.identity  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.integrations.models import (
    IntegrationInboundEvent,
    IntegrationProjectBinding,
    IntegrationSyncRun,
    IntegrationSyncedAsset,
    OutboxEvent,
    WebhookDeliveryEvent,
    WebhookSubscription,
)
from app.domains.integrations.project_sync_service import IntegrationProjectSyncService
from app.domains.integrations.service import IntegrationService, OutboxService, WebhookService
from app.domains.knowledge.models import KnowledgeEntry, LineageRecord, ProvenanceRecord
from app.domains.projects.models import SourceFile
from app.models.identity import Tenant, User
from app.models.projects import Project


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


async def make_context(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    db_session.add_all(
        [
            Tenant(id=tenant_id, name="Sync Tenant", slug=f"sync-{tenant_id.hex[:8]}"),
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=f"{user_id.hex[:8]}@example.com",
                full_name="Sync Owner",
                hashed_password="hashed",
            ),
            Project(
                id=project_id,
                tenant_id=tenant_id,
                name="External Delivery",
                slug=f"external-{project_id.hex[:8]}",
                description="External integration delivery project",
                owner_id=user_id,
            ),
        ]
    )
    integration = await IntegrationService(db_session).create_integration(
        tenant_id=tenant_id,
        provider_type="jira",
        name="Delivery Jira",
        config={
            "base_url": "https://jira.example.com",
            "credential_ref": "env:AMX_TEST_JIRA_API_TOKEN",
            "sync_path": "/rest/api/2/search",
        },
    )
    await db_session.flush()
    return tenant_id, user_id, project_id, integration


class FakeProjectSyncClient:
    requests: list[tuple[str, str, dict]] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return FakeProjectSyncResponse({"issues": [{"key": "AMX-ROOT", "summary": "Root payload"}]})

    async def request(self, method: str, url: str, **kwargs):
        self.requests.append((method, url, kwargs))
        return FakeProjectSyncResponse({"issues": [{"key": "AMX-ROOT", "summary": "Root payload"}]})


class FakeProjectSyncResponse:
    def __init__(self, body: dict, status_code: int = 200):
        self._body = body
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class FakeJiraConnectorResponse:
    def __init__(self, body: dict, status_code: int = 200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body


class FakeJiraConnectorClient:
    requests: list[tuple[str, str, dict]] = []
    transient_once = False
    status_code = 200

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, method: str, url: str, **kwargs):
        self.requests.append((method, url, kwargs))
        if self.transient_once:
            self.transient_once = False
            return FakeJiraConnectorResponse({"error": "temporary"}, 500)
        if self.status_code >= 400:
            return FakeJiraConnectorResponse({"error": "blocked"}, self.status_code)
        params = kwargs.get("params") or {}
        start_at = int(params.get("startAt", 0))
        max_results = int(params.get("maxResults", 2))
        all_issues = [
            {
                "key": "AMX-101",
                "fields": {
                    "summary": "Connector requirement 101",
                    "description": "First connector item.",
                    "updated": "2026-06-18T10:00:00Z",
                },
                "self": "https://jira.example.com/rest/api/2/issue/AMX-101",
            },
            {
                "key": "AMX-102",
                "fields": {
                    "summary": "Connector requirement 102",
                    "description": "Second connector item.",
                    "updated": "2026-06-19T10:00:00Z",
                },
                "self": "https://jira.example.com/rest/api/2/issue/AMX-102",
            },
        ]
        page = all_issues[start_at : start_at + max_results]
        return FakeJiraConnectorResponse(
            {
                "startAt": start_at,
                "maxResults": max_results,
                "total": len(all_issues),
                "issues": page,
            }
        )


@pytest.mark.asyncio
async def test_binding_preview_normalizes_external_items_without_persisting_assets(db_session, monkeypatch):
    tenant_id, user_id, project_id, integration = await make_context(db_session)
    service = IntegrationProjectSyncService(db_session)
    binding = await service.create_binding(
        tenant_id=tenant_id,
        integration_id=integration.id,
        project_id=project_id,
        name="Jira requirements",
        scope={"item_path": "issues", "external_scope": "project = AMX"},
        field_mapping={"external_id": "key", "title": "fields.summary", "content": "fields.description"},
        created_by=user_id,
    )
    monkeypatch.setattr(
        service,
        "_fetch_payload",
        lambda *_args, **_kwargs: {
            "issues": [
                {"key": "AMX-101", "fields": {"summary": "Import requirements", "description": "Create a durable knowledge asset."}}
            ]
        },
    )

    preview = await service.preview_binding(binding.id, tenant_id)

    assert preview.total == 1
    assert preview.items[0].external_id == "AMX-101"
    assert preview.items[0].title == "Import requirements"
    assert await db_session.scalar(select(KnowledgeEntry)) is None
    assert await db_session.scalar(select(SourceFile)) is None


@pytest.mark.asyncio
async def test_binding_preview_uses_stable_generated_external_ids_for_unkeyed_items(db_session, monkeypatch):
    tenant_id, user_id, project_id, integration = await make_context(db_session)
    service = IntegrationProjectSyncService(db_session)
    binding = await service.create_binding(
        tenant_id=tenant_id,
        integration_id=integration.id,
        project_id=project_id,
        name="Unkeyed external requirements",
        scope={"item_path": "issues"},
        field_mapping={"title": "summary", "content": "description"},
        created_by=user_id,
    )
    first_item = {"summary": "Stable requirement", "description": "Preserve identity without provider id."}
    second_item = {"summary": "Other requirement", "description": "A separate item."}
    payload = {"issues": [first_item, second_item]}
    monkeypatch.setattr(service, "_fetch_payload", lambda *_args, **_kwargs: payload)

    first_preview = await service.preview_binding(binding.id, tenant_id)
    payload["issues"] = [second_item, first_item]
    second_preview = await service.preview_binding(binding.id, tenant_id)

    first_ids = {item.title: item.external_id for item in first_preview.items}
    second_ids = {item.title: item.external_id for item in second_preview.items}
    assert first_ids == second_ids
    assert first_ids["Stable requirement"].startswith("generated-")
    assert "item-1" not in first_ids.values()
    assert "item-2" not in first_ids.values()
    assert await db_session.scalar(select(KnowledgeEntry)) is None
    assert await db_session.scalar(select(SourceFile)) is None


@pytest.mark.asyncio
async def test_sync_is_idempotent_and_updates_changed_external_asset_with_provenance(db_session, monkeypatch):
    tenant_id, user_id, project_id, integration = await make_context(db_session)
    service = IntegrationProjectSyncService(db_session)
    binding = await service.create_binding(
        tenant_id=tenant_id,
        integration_id=integration.id,
        project_id=project_id,
        name="Jira requirements",
        scope={"item_path": "issues"},
        field_mapping={"external_id": "key", "title": "summary", "content": "description", "updated_at": "updated"},
        created_by=user_id,
    )
    payload = {
        "issues": [
            {
                "key": "AMX-101",
                "summary": "Import requirements",
                "description": "Initial requirement",
                "updated": "2026-06-10T10:00:00Z",
            }
        ]
    }
    monkeypatch.setattr(service, "_fetch_payload", lambda *_args, **_kwargs: payload)

    first = await service.sync_binding(binding.id, tenant_id, user_id)
    second = await service.sync_binding(binding.id, tenant_id, user_id)
    payload["issues"][0]["description"] = "Changed requirement"
    payload["issues"][0]["updated"] = "2026-06-11T10:00:00Z"
    third = await service.sync_binding(binding.id, tenant_id, user_id)

    assert (first.created_count, first.updated_count, first.unchanged_count) == (1, 0, 0)
    assert (second.created_count, second.updated_count, second.unchanged_count) == (0, 0, 1)
    assert (third.created_count, third.updated_count, third.unchanged_count) == (0, 1, 0)
    assert len(list((await db_session.scalars(select(IntegrationSyncedAsset))).all())) == 1
    assert len(list((await db_session.scalars(select(SourceFile))).all())) == 1
    entries = list((await db_session.scalars(select(KnowledgeEntry))).all())
    assert len(entries) == 1
    assert entries[0].content == "Changed requirement"
    assert len(list((await db_session.scalars(select(ProvenanceRecord))).all())) == 1
    assert len(list((await db_session.scalars(select(LineageRecord))).all())) == 1
    runs = list((await db_session.scalars(select(IntegrationSyncRun))).all())
    assert [run.status for run in runs] == ["completed", "completed", "completed"]
    summary = await IntegrationService(db_session).build_operations_summary(tenant_id)
    assert summary.evidence.project_binding_count == 1
    assert summary.evidence.completed_project_sync_count == 3
    assert summary.evidence.synced_asset_count == 1


@pytest.mark.asyncio
async def test_project_binding_sync_requires_configured_source_path(db_session, monkeypatch):
    tenant_id, user_id, project_id, _integration = await make_context(db_session)
    integration = await IntegrationService(db_session).create_integration(
        tenant_id=tenant_id,
        provider_type="jira",
        name="Health-only Jira",
        config={
            "base_url": "https://jira.example.com",
            "credential_ref": "env:AMX_TEST_JIRA_API_TOKEN",
        },
    )
    service = IntegrationProjectSyncService(db_session)
    binding = await service.create_binding(
        tenant_id=tenant_id,
        integration_id=integration.id,
        project_id=project_id,
        name="Missing source",
        scope={"item_path": "issues"},
        field_mapping={"external_id": "key", "title": "summary", "content": "summary"},
        created_by=user_id,
    )
    FakeProjectSyncClient.requests = []
    monkeypatch.setattr("app.domains.integrations.project_sync_service.httpx.AsyncClient", FakeProjectSyncClient)

    run = await service.sync_binding(binding.id, tenant_id, user_id)

    assert run.status == "failed"
    assert "sync_path or scope.path" in (run.error_message or "")
    assert binding.last_sync_status == "failed"
    assert FakeProjectSyncClient.requests == []
    assert await db_session.scalar(select(KnowledgeEntry)) is None
    assert await db_session.scalar(select(SourceFile)) is None


@pytest.mark.asyncio
async def test_sync_records_failed_run_when_remote_payload_cannot_be_loaded(db_session, monkeypatch):
    tenant_id, user_id, project_id, integration = await make_context(db_session)
    service = IntegrationProjectSyncService(db_session)
    binding = await service.create_binding(
        tenant_id=tenant_id,
        integration_id=integration.id,
        project_id=project_id,
        name="Jira requirements",
        scope={},
        field_mapping={},
        created_by=user_id,
    )

    async def fail(*_args, **_kwargs):
        raise RuntimeError("remote unavailable")

    monkeypatch.setattr(service, "_fetch_payload", fail)
    run = await service.sync_binding(binding.id, tenant_id, user_id)

    assert run.status == "failed"
    assert "remote unavailable" in (run.error_message or "")
    assert binding.last_sync_status == "failed"

    queue = await IntegrationService(db_session).build_incident_queue(tenant_id)
    assert queue.total == 1
    assert queue.items[0].category == "project_sync"
    assert queue.items[0].action_type == "retry_sync"


@pytest.mark.asyncio
async def test_operations_queue_retries_webhook_and_outbox_failures(db_session, monkeypatch):
    tenant_id, user_id, _, integration = await make_context(db_session)
    subscription = WebhookSubscription(
        tenant_id=tenant_id,
        integration_provider_id=integration.id,
        url="https://hooks.example.com/amx",
        events=["project.updated"],
        is_active=True,
    )
    outbox = OutboxEvent(
        tenant_id=tenant_id,
        aggregate_type="project",
        aggregate_id=uuid4(),
        event_type="project.updated",
        payload={"status": "ready"},
        status="failed",
        attempts=3,
        max_attempts=3,
        last_error="target unavailable",
        published=False,
    )
    db_session.add_all([subscription, outbox])
    await db_session.flush()
    delivery = WebhookDeliveryEvent(
        tenant_id=tenant_id,
        webhook_subscription_id=subscription.id,
        event_id="evt-failed",
        url=subscription.url,
        request_headers={"Content-Type": "application/json"},
        request_body={"event_id": "evt-failed"},
        attempts=3,
        error_message="connection timeout",
    )
    db_session.add(delivery)
    await db_session.flush()

    queue = await IntegrationService(db_session).build_incident_queue(tenant_id)
    assert {item.category for item in queue.items} == {"webhook", "outbox"}
    assert queue.critical_count == 2

    async def successful_retry(*_args, **_kwargs):
        return True

    webhook_service = WebhookService(db_session)
    monkeypatch.setattr(webhook_service, "_attempt_delivery", successful_retry)
    retried_delivery = await webhook_service.retry_delivery(delivery.id, tenant_id)
    retried_outbox = await OutboxService(db_session).retry_event(outbox.id, tenant_id)

    assert retried_delivery.delivered_at is not None
    assert retried_delivery.attempts == 4
    assert retried_outbox.status == "pending"
    assert retried_outbox.last_error is None


@pytest.mark.asyncio
async def test_failed_webhook_delivery_enqueues_arq_retry_without_fake_attempt(db_session, monkeypatch):
    tenant_id, _user_id, _project_id, integration = await make_context(db_session)
    subscription = await WebhookService(db_session).create_subscription(
        tenant_id=tenant_id,
        integration_id=integration.id,
        url="https://hooks.example.com/amx",
        events=["project.updated"],
        secret="webhook-secret",
    )
    calls = []

    class FakeRedis:
        async def enqueue_job(self, name, *args, **kwargs):
            calls.append(("enqueue", name, args, kwargs))

        async def aclose(self):
            calls.append(("closed",))

    async def fake_create_pool(redis_settings):
        calls.append(("pool", redis_settings))
        return FakeRedis()

    service = WebhookService(db_session)

    async def failed_attempt(_subscription, _payload, delivery):
        delivery.error_message = "target unavailable"
        return False

    monkeypatch.setattr("arq.create_pool", fake_create_pool)
    monkeypatch.setattr(service, "_attempt_delivery", failed_attempt)

    delivery = await service.deliver_webhook(
        subscription.id,
        {"event_id": "evt-retry", "event_type": "project.updated"},
    )

    assert delivery.delivered_at is None
    assert delivery.error_message == "target unavailable"
    assert delivery.attempts == 1
    assert calls[0][0] == "pool"
    assert calls[1] == (
        "enqueue",
        "retry_webhook_delivery",
        (str(delivery.id),),
        {"_defer_by": 5},
    )
    assert calls[2] == ("closed",)


@pytest.mark.asyncio
async def test_outbox_publish_routes_by_provider_and_event_type(db_session, monkeypatch):
    tenant_id, _user_id, _project_id, integration = await make_context(db_session)
    other_integration = await IntegrationService(db_session).create_integration(
        tenant_id=tenant_id,
        provider_type="confluence",
        name="Delivery Confluence",
        config={"base_url": "https://confluence.example.com", "api_key": "secret"},
    )
    matching_subscription = WebhookSubscription(
        tenant_id=tenant_id,
        integration_provider_id=integration.id,
        url="https://hooks.example.com/matching",
        events=["project.updated"],
        is_active=True,
    )
    wrong_event_subscription = WebhookSubscription(
        tenant_id=tenant_id,
        integration_provider_id=integration.id,
        url="https://hooks.example.com/wrong-event",
        events=["project.deleted"],
        is_active=True,
    )
    wrong_provider_subscription = WebhookSubscription(
        tenant_id=tenant_id,
        integration_provider_id=other_integration.id,
        url="https://hooks.example.com/wrong-provider",
        events=["project.updated"],
        is_active=True,
    )
    event = OutboxEvent(
        tenant_id=tenant_id,
        aggregate_type="integration_provider",
        aggregate_id=integration.id,
        event_type="project.updated",
        payload={"status": "ready"},
        published=False,
    )
    db_session.add_all(
        [
            matching_subscription,
            wrong_event_subscription,
            wrong_provider_subscription,
            event,
        ]
    )
    await db_session.flush()
    delivered_subscription_ids = []

    async def fake_deliver_webhook(self, subscription_id, event_payload):
        delivered_subscription_ids.append(subscription_id)
        return WebhookDeliveryEvent(
            tenant_id=tenant_id,
            webhook_subscription_id=subscription_id,
            event_id=event_payload["event_id"],
            url="https://hooks.example.com/matching",
            request_headers={},
            request_body=event_payload,
            delivered_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(WebhookService, "deliver_webhook", fake_deliver_webhook)

    result = await OutboxService(db_session).publish_pending_events(batch_size=10)

    assert delivered_subscription_ids == [matching_subscription.id]
    assert result == {"processed": 1, "published": 1, "failed": 0}
    assert event.published is True


@pytest.mark.asyncio
async def test_jira_connector_rejects_raw_credentials_and_requires_preview_before_sync(db_session):
    tenant_id, user_id, project_id, _integration = await make_context(db_session)
    service = IntegrationService(db_session)

    with pytest.raises(ValueError):
        await service.create_integration(
            tenant_id=tenant_id,
            provider_type="jira",
            name="Unsafe Jira",
            config={
                "base_url": "https://jira.example.com",
                "api_key": "raw-secret-must-not-persist",
                "sync_path": "/rest/api/2/search",
            },
        )

    integration = await service.create_integration(
        tenant_id=tenant_id,
        provider_type="jira",
        name="Safe Jira",
        config={
            "base_url": "https://jira.example.com",
            "credential_ref": "env:AMX_TEST_JIRA_API_TOKEN",
            "sync_path": "/rest/api/2/search",
            "connector_profile": "jira_project_sync_v1",
        },
    )
    assert "raw-secret-must-not-persist" not in str(integration.config_json)

    binding = await IntegrationProjectSyncService(db_session).create_binding(
        tenant_id=tenant_id,
        integration_id=integration.id,
        project_id=project_id,
        name="Jira production connector",
        scope={
            "item_path": "issues",
            "connector_profile": "jira_project_sync_v1",
            "external_scope": "project = AMX",
        },
        field_mapping={"external_id": "key", "title": "fields.summary", "content": "fields.description"},
        created_by=user_id,
    )

    run = await IntegrationProjectSyncService(db_session).sync_binding(binding.id, tenant_id, user_id)

    assert run.status == "failed"
    assert run.details_json["failure_state"] == "preview_required"
    assert binding.last_sync_status == "failed"


@pytest.mark.asyncio
async def test_jira_connector_preview_paginated_sync_retry_audit_and_outbox(db_session, monkeypatch):
    tenant_id, user_id, project_id, integration = await make_context(db_session)
    integration.config_json = {
        **integration.config_json,
        "connector_profile": "jira_project_sync_v1",
        "page_size": 1,
        "max_pages": 5,
        "retry_attempts": 1,
    }
    service = IntegrationProjectSyncService(db_session)
    binding = await service.create_binding(
        tenant_id=tenant_id,
        integration_id=integration.id,
        project_id=project_id,
        name="Jira production connector",
        scope={
            "item_path": "issues",
            "connector_profile": "jira_project_sync_v1",
            "external_scope": "project = AMX",
            "page_size": 1,
            "max_pages": 5,
        },
        field_mapping={
            "external_id": "key",
            "title": "fields.summary",
            "content": "fields.description",
            "updated_at": "fields.updated",
            "external_url": "self",
        },
        created_by=user_id,
    )
    FakeJiraConnectorClient.requests = []
    FakeJiraConnectorClient.transient_once = True
    FakeJiraConnectorClient.status_code = 200
    monkeypatch.setattr("app.domains.integrations.project_sync_service.httpx.AsyncClient", FakeJiraConnectorClient)

    preview = await service.preview_binding(binding.id, tenant_id)
    run = await service.sync_binding(binding.id, tenant_id, user_id)

    assert preview.total == 2
    assert run.status == "completed"
    assert run.created_count == 2
    assert run.details_json["fetch_evidence"]["mode"] == "jira_paginated_fetch"
    assert run.details_json["fetch_evidence"]["pages_fetched"] == 2
    assert run.details_json["fetch_evidence"]["bounded"] is True
    assert binding.cursor_json["last_item_count"] == 2
    assert len(list((await db_session.scalars(select(IntegrationSyncedAsset))).all())) == 2

    request_headers = [kwargs["headers"] for _method, _url, kwargs in FakeJiraConnectorClient.requests]
    assert any(headers["Authorization"] == "Bearer test-jira-token" for headers in request_headers)
    assert "test-jira-token" not in str(integration.config_json)
    assert "test-jira-token" not in str(run.details_json)

    event_types = [event.event_type for event in (await db_session.scalars(select(IntegrationInboundEvent))).all()]
    assert "integration.project_sync.started" in event_types
    assert "integration.project_sync.completed" in event_types

    outbox_events = list((await db_session.scalars(select(OutboxEvent))).all())
    assert any(event.event_type == "integration.project_sync.completed" for event in outbox_events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("credential_ref", "status_code", "expected_state"),
    [
        ("env:AMX_MISSING_JIRA_TOKEN", 200, "missing_credential"),
        ("env:AMX_TEST_JIRA_API_TOKEN", 401, "expired_credential"),
        ("env:AMX_TEST_JIRA_API_TOKEN", 429, "rate_limited"),
    ],
)
async def test_jira_connector_records_clear_failure_states(
    db_session,
    monkeypatch,
    credential_ref,
    status_code,
    expected_state,
):
    tenant_id, user_id, project_id, integration = await make_context(db_session)
    integration.config_json = {
        "base_url": "https://jira.example.com",
        "credential_ref": credential_ref,
        "sync_path": "/rest/api/2/search",
        "connector_profile": "jira_project_sync_v1",
        "retry_attempts": 0,
    }
    service = IntegrationProjectSyncService(db_session)
    binding = await service.create_binding(
        tenant_id=tenant_id,
        integration_id=integration.id,
        project_id=project_id,
        name=f"Jira failure {expected_state}",
        scope={
            "item_path": "issues",
            "connector_profile": "jira_project_sync_v1",
            "require_preview_before_sync": False,
        },
        field_mapping={"external_id": "key", "title": "fields.summary", "content": "fields.description"},
        created_by=user_id,
    )
    FakeJiraConnectorClient.requests = []
    FakeJiraConnectorClient.transient_once = False
    FakeJiraConnectorClient.status_code = status_code
    monkeypatch.setattr("app.domains.integrations.project_sync_service.httpx.AsyncClient", FakeJiraConnectorClient)

    run = await service.sync_binding(binding.id, tenant_id, user_id)

    assert run.status == "failed"
    assert run.details_json["failure_state"] == expected_state
    assert binding.last_sync_status == "failed"
    event = await db_session.scalar(
        select(IntegrationInboundEvent).where(IntegrationInboundEvent.event_type == "integration.project_sync.failed")
    )
    assert event is not None
    assert event.payload["failure_state"] == expected_state
