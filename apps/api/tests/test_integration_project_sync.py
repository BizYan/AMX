import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-secret"

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401
import app.domains.documents.models  # noqa: F401
import app.models.identity  # noqa: F401
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.integrations.models import (
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
            "api_key": "secret",
            "sync_path": "/rest/api/2/search",
        },
    )
    await db_session.flush()
    return tenant_id, user_id, project_id, integration


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
