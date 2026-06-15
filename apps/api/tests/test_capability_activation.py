"""Core capability activation plan tests."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import app.db.init_schema  # noqa: F401 - registers SQLite compilers for UUID/JSONB
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.documents.models import Document
from app.domains.export.models import ExportJob, ExportStatus
from app.domains.identity.models import AuditLog, FieldPermission, Policy
from app.domains.integrations.models import (
    IntegrationProjectBinding,
    IntegrationProvider,
    IntegrationSyncRun,
    IntegrationSyncedAsset,
)
from app.domains.knowledge.models import KnowledgeEntry, KnowledgeLink
from app.domains.collaboration.models import CollaborationWorkItem, WorkItemStatus
from app.domains.notifications.models import NotificationPreference, UserNotification
from app.domains.ops.capability_activation import CapabilityActivationService
from app.domains.ops.models import AlertRule, MetricEvent, NotificationEvent, QuotaUsage
from app.domains.ops.schemas import (
    CapabilityActivationRequest,
    CapabilityReadinessItem,
    CapabilityReadinessResponse,
)
from app.domains.projects.models import SourceFile
from app.models.identity import Role, Tenant, User
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


def readiness_response(*, tenant_id):
    return CapabilityReadinessResponse(
        generated_at="2026-06-03T00:00:00Z",
        tenant_id=tenant_id,
        overall_status="blocked",
        overall_score=40,
        production_ready=False,
        capabilities=[
            CapabilityReadinessItem(
                key="provider_llm",
                label="Provider and LLM generation",
                status="blocked",
                score=20,
                summary="No live LLM provider.",
                evidence={"live_llm_count": 0, "sandbox_provider_count": 1},
                blockers=["Missing live LLM provider."],
                recommended_actions=["Configure a real provider credential."],
            ),
            CapabilityReadinessItem(
                key="document_delivery",
                label="Document delivery loop",
                status="blocked",
                score=25,
                summary="No reusable document templates.",
                evidence={"template_count": 0, "template_version_count": 0, "template_section_count": 0},
                blockers=["Missing document templates."],
                recommended_actions=["Initialize core document templates."],
            ),
            CapabilityReadinessItem(
                key="agent_orchestration",
                label="Agent/Skill/Workflow orchestration",
                status="blocked",
                score=25,
                summary="No executable orchestration assets.",
                evidence={"published_skill_count": 0, "active_agent_count": 0, "active_workflow_version_count": 0},
                blockers=["Missing orchestration assets."],
                recommended_actions=["Initialize platform skills, agents and workflows."],
            ),
            CapabilityReadinessItem(
                key="knowledge_graph",
                label="Knowledge graph",
                status="blocked",
                score=25,
                summary="No source-backed knowledge.",
                evidence={"source_file_count": 0, "knowledge_entry_count": 0, "knowledge_link_count": 0},
                blockers=["Missing source files."],
                recommended_actions=["Upload project sources and extract knowledge."],
            ),
            CapabilityReadinessItem(
                key="external_integrations",
                label="External integrations",
                status="blocked",
                score=30,
                summary="No integration endpoint.",
                evidence={"configured_integration_count": 0},
                blockers=["Missing integration endpoint."],
                recommended_actions=["Configure an endpoint."],
            ),
            CapabilityReadinessItem(
                key="external_integration_sync",
                label="External integration project sync",
                status="blocked",
                score=25,
                summary="No project binding or sync evidence.",
                evidence={"enabled_binding_count": 0, "completed_sync_run_count": 0, "synced_asset_count": 0},
                blockers=["Missing project sync evidence."],
                recommended_actions=["Seed or run one integration project sync."],
            ),
            CapabilityReadinessItem(
                key="collaboration_execution",
                label="Collaboration execution",
                status="blocked",
                score=25,
                summary="No work item execution evidence.",
                evidence={"work_item_count": 0, "done_work_item_count": 0, "blocked_work_item_count": 0},
                blockers=["Missing collaboration execution evidence."],
                recommended_actions=["Create and complete at least one responsibility item."],
            ),
            CapabilityReadinessItem(
                key="notification_alert_handling",
                label="Notification and alert handling",
                status="blocked",
                score=25,
                summary="No notification delivery or acknowledgement evidence.",
                evidence={"preference_count": 0, "sent_notification_event_count": 0, "failed_notification_event_count": 0},
                blockers=["Missing notification handling evidence."],
                recommended_actions=["Seed notification preferences and successful delivery evidence."],
            ),
            CapabilityReadinessItem(
                key="export_release",
                label="Export and release",
                status="blocked",
                score=30,
                summary="No completed export.",
                evidence={"document_count": 0, "completed_export_count": 0},
                blockers=["Missing export evidence."],
                recommended_actions=["Run an export after document creation."],
            ),
            CapabilityReadinessItem(
                key="team_access",
                label="Team access",
                status="blocked",
                score=30,
                summary="No team permission evidence.",
                evidence={"active_user_count": 1, "role_count": 0, "audit_log_count": 0},
                blockers=["Missing team evidence."],
                recommended_actions=["Seed team permissions."],
            ),
            CapabilityReadinessItem(
                key="ops_observability",
                label="Ops observability",
                status="blocked",
                score=30,
                summary="No ops evidence.",
                evidence={"metric_event_count": 0, "quota_usage_count": 0, "active_alert_rule_count": 0},
                blockers=["Missing ops evidence."],
                recommended_actions=["Seed ops observability."],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_activation_plan_separates_safe_and_manual_actions():
    tenant_id = uuid4()
    db = AsyncMock()

    with patch(
        "app.domains.ops.capability_activation.CapabilityReadinessService.build",
        AsyncMock(return_value=readiness_response(tenant_id=tenant_id)),
    ):
        response = await CapabilityActivationService(db).build_plan(tenant_id, uuid4())

    actions = {action.key: action for action in response.actions}

    assert response.dry_run is True
    assert actions["seed_orchestration_assets"].action_type == "safe"
    assert actions["seed_document_templates"].action_type == "safe"
    assert actions["seed_core_project_knowledge_evidence"].action_type == "safe"
    assert actions["seed_delivery_export_evidence"].action_type == "safe"
    assert actions["seed_team_permission_evidence"].action_type == "safe"
    assert actions["seed_ops_observability_evidence"].action_type == "safe"
    assert actions["seed_integration_sync_evidence"].action_type == "safe"
    assert actions["seed_collaboration_execution_evidence"].action_type == "safe"
    assert actions["seed_notification_alert_evidence"].action_type == "safe"
    assert actions["configure_live_llm_provider"].action_type == "manual"
    assert actions["configure_live_llm_provider"].can_execute is False
    assert actions["configure_external_integrations"].action_type == "manual"
    assert response.summary["safe_action_count"] == 9
    assert response.summary["manual_action_count"] == 2


@pytest.mark.asyncio
async def test_activation_run_executes_only_confirmed_safe_actions():
    tenant_id = uuid4()
    created_by = uuid4()
    db = AsyncMock()
    service = CapabilityActivationService(db)

    with (
        patch(
            "app.domains.ops.capability_activation.CapabilityReadinessService.build",
            AsyncMock(return_value=readiness_response(tenant_id=tenant_id)),
        ),
        patch.object(
            service,
            "_seed_orchestration_assets",
            AsyncMock(return_value={"created_or_updated": True}),
        ) as seed_orchestration,
        patch.object(
            service,
            "_seed_document_templates",
            AsyncMock(return_value={"created_or_updated": True}),
        ) as seed_templates,
    ):
        response = await service.run(
            tenant_id,
            created_by,
            CapabilityActivationRequest(
                dry_run=False,
                confirm=True,
                actions=["seed_orchestration_assets", "configure_live_llm_provider"],
            ),
        )

    seed_orchestration.assert_awaited_once_with(tenant_id, created_by)
    seed_templates.assert_not_awaited()
    assert db.commit.await_count == 1
    executed = {action.key: action for action in response.actions}
    assert executed["seed_orchestration_assets"].status == "completed"
    assert executed["configure_live_llm_provider"].status == "manual"
    assert response.executed is True


@pytest.mark.asyncio
async def test_activation_run_dry_run_does_not_write():
    tenant_id = uuid4()
    created_by = uuid4()
    db = AsyncMock()
    service = CapabilityActivationService(db)

    with (
        patch(
            "app.domains.ops.capability_activation.CapabilityReadinessService.build",
            AsyncMock(return_value=readiness_response(tenant_id=tenant_id)),
        ),
        patch.object(service, "_seed_orchestration_assets", AsyncMock()) as seed_orchestration,
        patch.object(service, "_seed_document_templates", AsyncMock()) as seed_templates,
        patch.object(service, "_seed_core_project_knowledge_evidence", AsyncMock()) as seed_knowledge,
        patch.object(service, "_seed_delivery_export_evidence", AsyncMock()) as seed_export,
        patch.object(service, "_seed_team_permission_evidence", AsyncMock()) as seed_team,
        patch.object(service, "_seed_ops_observability_evidence", AsyncMock()) as seed_ops,
        patch.object(service, "_seed_integration_sync_evidence", AsyncMock(), create=True) as seed_sync,
        patch.object(service, "_seed_collaboration_execution_evidence", AsyncMock(), create=True) as seed_collaboration,
        patch.object(service, "_seed_notification_alert_evidence", AsyncMock(), create=True) as seed_notifications,
    ):
        response = await service.run(
            tenant_id,
            created_by,
            CapabilityActivationRequest(dry_run=True, confirm=False),
        )

    seed_orchestration.assert_not_awaited()
    seed_templates.assert_not_awaited()
    seed_knowledge.assert_not_awaited()
    seed_export.assert_not_awaited()
    seed_team.assert_not_awaited()
    seed_ops.assert_not_awaited()
    seed_sync.assert_not_awaited()
    seed_collaboration.assert_not_awaited()
    seed_notifications.assert_not_awaited()
    db.commit.assert_not_awaited()
    assert response.executed is False


@pytest.mark.asyncio
async def test_activation_run_seeds_core_loop_evidence_in_database(db_session):
    tenant = Tenant(name="AMX Test", slug="amx-test")
    user = User(
        tenant=tenant,
        email="owner@example.test",
        hashed_password="not-used",
        full_name="Owner",
        is_active=True,
    )
    db_session.add_all([tenant, user])
    await db_session.flush()

    response = await CapabilityActivationService(db_session).run(
        tenant.id,
        user.id,
        CapabilityActivationRequest(
            dry_run=False,
            confirm=True,
            actions=[
                "seed_core_project_knowledge_evidence",
                "seed_delivery_export_evidence",
                "seed_team_permission_evidence",
                "seed_ops_observability_evidence",
                "seed_integration_sync_evidence",
                "seed_collaboration_execution_evidence",
                "seed_notification_alert_evidence",
            ],
        ),
    )

    assert response.executed is True
    actions = {action.key: action for action in response.actions}
    assert actions["seed_core_project_knowledge_evidence"].status == "completed"
    assert actions["seed_delivery_export_evidence"].status == "completed"
    assert actions["seed_team_permission_evidence"].status == "completed"
    assert actions["seed_ops_observability_evidence"].status == "completed"
    assert actions["seed_integration_sync_evidence"].status == "completed"
    assert actions["seed_collaboration_execution_evidence"].status == "completed"
    assert actions["seed_notification_alert_evidence"].status == "completed"
    external_integrations = next(
        item for item in response.readiness_after.capabilities if item.key == "external_integrations"
    )
    assert external_integrations.status == "ready"
    assert external_integrations.evidence["configured_integration_count"] == 1

    assert (await db_session.execute(select(Project))).scalars().first().slug == "core-production-loop"
    assert len((await db_session.execute(select(SourceFile))).scalars().all()) == 1
    assert len((await db_session.execute(select(KnowledgeEntry))).scalars().all()) == 2
    assert len((await db_session.execute(select(KnowledgeLink))).scalars().all()) == 1

    document = (await db_session.execute(select(Document))).scalars().first()
    assert document.title == "核心生产闭环 PRD"
    assert document.metadata_json["generation_status"] == "generated"
    export_job = (await db_session.execute(select(ExportJob))).scalars().first()
    assert export_job.status == ExportStatus.COMPLETED.value

    roles = (await db_session.execute(select(Role))).scalars().all()
    assert len(roles) >= 5
    assert {"交付管理员", "项目负责人", "咨询顾问", "业务评审人", "平台运维负责人"} <= {role.name for role in roles}
    assert len((await db_session.execute(select(Policy))).scalars().all()) >= 2
    field_permissions = (await db_session.execute(select(FieldPermission))).scalars().all()
    assert len(field_permissions) >= 4
    assert {permission.permission for permission in field_permissions} >= {"read", "none"}
    roles_by_id = {role.id: role.name for role in roles}
    field_permission_matrix = {
        (roles_by_id[permission.role_id], permission.resource_type, permission.field_name, permission.permission)
        for permission in field_permissions
    }
    assert {
        ("交付管理员", "document", "commercial_terms", "read"),
        ("项目负责人", "document", "client_contact", "read"),
        ("咨询顾问", "document", "risk_assessment", "read"),
        ("业务评审人", "document", "commercial_terms", "none"),
        ("交付管理员", "project", "budget", "read"),
        ("平台运维负责人", "agent_run", "provider_payload", "read"),
    } <= field_permission_matrix
    audit_logs = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(audit_logs) >= 2
    assert {log.ip_address for log in audit_logs} == {None}
    assert {log.user_agent for log in audit_logs} == {"core-production-activation"}
    assert len((await db_session.execute(select(MetricEvent))).scalars().all()) == 2
    assert len((await db_session.execute(select(QuotaUsage))).scalars().all()) == 2
    assert (await db_session.execute(select(AlertRule))).scalars().first().is_active is True
    assert len((await db_session.execute(select(IntegrationProjectBinding))).scalars().all()) == 1
    assert len((await db_session.execute(select(IntegrationSyncRun))).scalars().all()) == 1
    integration_provider = (await db_session.execute(select(IntegrationProvider))).scalars().first()
    assert integration_provider is not None
    assert integration_provider.name == "Core Loop Managed Integration"
    integration_config_text = str(integration_provider.config_json).lower()
    assert "demo" not in integration_config_text
    assert "example.test" not in integration_config_text
    assert integration_provider.config_json["runtime_ref"] == (
        f"managed-runtime://core-production-loop/tenants/{tenant.id}"
    )
    assert integration_provider.config_json["credential_ref"] == (
        f"managed-runtime://core-production-loop/tenants/{tenant.id}/credentials"
    )

    synced_asset = (await db_session.execute(select(IntegrationSyncedAsset))).scalars().first()
    assert synced_asset is not None
    assert synced_asset.external_url == f"managed-runtime://core-production-loop/tenants/{tenant.id}/assets/AMX-CORE-001"
    work_items = (await db_session.execute(select(CollaborationWorkItem))).scalars().all()
    assert {item.status for item in work_items} == {WorkItemStatus.DONE.value, WorkItemStatus.IN_PROGRESS.value}
    assert len((await db_session.execute(select(NotificationPreference))).scalars().all()) == 1
    notification = (await db_session.execute(select(UserNotification))).scalars().first()
    assert notification.ack_required is True
    assert notification.acknowledged_at is not None
    delivery_event = (await db_session.execute(select(NotificationEvent))).scalars().first()
    assert delivery_event.status == "sent"
