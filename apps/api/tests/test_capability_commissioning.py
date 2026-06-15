"""Core production commissioning service tests."""

import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost/postgres"
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from app.domains.ops.capability_commissioning import CapabilityCommissioningService
from app.domains.ops.schemas import (
    CapabilityCommissioningRunRequest,
    CapabilityReadinessItem,
    CapabilityReadinessResponse,
)


class FakeExecuteResult:
    def __init__(self, *, rows=None, count: int | None = None):
        self._rows = rows or []
        self._count = count

    def scalar_one_or_none(self):
        return self._count

    def scalars(self):
        result = MagicMock()
        result.all.return_value = self._rows
        result.first.return_value = self._rows[0] if self._rows else None
        return result


def readiness_response(*, tenant_id, production_ready=False):
    return CapabilityReadinessResponse(
        generated_at="2026-06-03T00:00:00Z",
        tenant_id=tenant_id,
        overall_status="ready" if production_ready else "blocked",
        overall_score=92 if production_ready else 45,
        production_ready=production_ready,
        capabilities=[
            CapabilityReadinessItem(
                key="provider_llm",
                label="Provider and LLM generation",
                status="ready" if production_ready else "blocked",
                score=100 if production_ready else 20,
                summary="Provider summary",
                evidence={"live_llm_count": 1 if production_ready else 0},
                blockers=[] if production_ready else ["Missing live LLM provider."],
                recommended_actions=[],
            ),
            CapabilityReadinessItem(
                key="knowledge_graph",
                label="Knowledge graph",
                status="ready" if production_ready else "blocked",
                score=90 if production_ready else 25,
                summary="Knowledge summary",
                evidence={
                    "source_file_count": 3 if production_ready else 0,
                    "knowledge_entry_count": 12 if production_ready else 0,
                    "knowledge_link_count": 8 if production_ready else 0,
                },
                blockers=[] if production_ready else ["Missing knowledge evidence."],
                recommended_actions=[],
            ),
            CapabilityReadinessItem(
                key="external_integrations",
                label="External integrations",
                status="ready" if production_ready else "blocked",
                score=85 if production_ready else 30,
                summary="Integration summary",
                evidence={"configured_integration_count": 1 if production_ready else 0},
                blockers=[] if production_ready else ["Missing integration endpoint."],
                recommended_actions=[],
            ),
            CapabilityReadinessItem(
                key="external_integration_sync",
                label="External integration project sync",
                status="ready" if production_ready else "blocked",
                score=90 if production_ready else 25,
                summary="Integration sync summary",
                evidence={
                    "enabled_binding_count": 1 if production_ready else 0,
                    "completed_sync_run_count": 1 if production_ready else 0,
                    "synced_asset_count": 2 if production_ready else 0,
                },
                blockers=[] if production_ready else ["Missing integration sync evidence."],
                recommended_actions=[],
            ),
            CapabilityReadinessItem(
                key="collaboration_execution",
                label="Collaboration execution",
                status="ready" if production_ready else "blocked",
                score=95 if production_ready else 25,
                summary="Collaboration summary",
                evidence={
                    "work_item_count": 2 if production_ready else 0,
                    "done_work_item_count": 1 if production_ready else 0,
                    "blocked_work_item_count": 0,
                    "overdue_work_item_count": 0,
                },
                blockers=[] if production_ready else ["Missing collaboration execution evidence."],
                recommended_actions=[],
            ),
            CapabilityReadinessItem(
                key="notification_alert_handling",
                label="Notification and alert handling",
                status="ready" if production_ready else "blocked",
                score=95 if production_ready else 25,
                summary="Notification summary",
                evidence={
                    "preference_count": 1 if production_ready else 0,
                    "sent_notification_event_count": 1 if production_ready else 0,
                    "failed_notification_event_count": 0,
                    "unacknowledged_required_notification_count": 0,
                    "escalated_notification_count": 0,
                },
                blockers=[] if production_ready else ["Missing notification handling evidence."],
                recommended_actions=[],
            ),
            CapabilityReadinessItem(
                key="export_release",
                label="Export release",
                status="ready" if production_ready else "blocked",
                score=90 if production_ready else 30,
                summary="Export summary",
                evidence={
                    "completed_export_count": 1 if production_ready else 0,
                    "document_count": 2 if production_ready else 0,
                },
                blockers=[] if production_ready else ["Missing export evidence."],
                recommended_actions=[],
            ),
            CapabilityReadinessItem(
                key="team_access",
                label="Team access",
                status="ready" if production_ready else "blocked",
                score=95 if production_ready else 30,
                summary="Team summary",
                evidence={
                    "active_user_count": 2 if production_ready else 0,
                    "role_count": 2 if production_ready else 0,
                    "audit_log_count": 3 if production_ready else 0,
                    "policy_count": 2 if production_ready else 0,
                    "field_permission_count": 4 if production_ready else 0,
                },
                blockers=[] if production_ready else ["Missing team evidence."],
                recommended_actions=[],
            ),
            CapabilityReadinessItem(
                key="ops_observability",
                label="Ops observability",
                status="ready" if production_ready else "blocked",
                score=95 if production_ready else 30,
                summary="Ops summary",
                evidence={
                    "metric_event_count": 3 if production_ready else 0,
                    "quota_usage_count": 2 if production_ready else 0,
                    "active_alert_rule_count": 1 if production_ready else 0,
                },
                blockers=[] if production_ready else ["Missing ops evidence."],
                recommended_actions=[],
            ),
        ],
    )


def test_commissioning_counts_managed_runtime_integration_as_configured():
    provider = MagicMock()
    provider.config_json = {
        "runtime_ref": "managed-runtime://core-production-loop/tenants/tenant-id",
        "credential_ref": "managed-runtime://core-production-loop/tenants/tenant-id/credentials",
    }

    assert CapabilityCommissioningService(AsyncMock())._integration_has_endpoint(provider)


@pytest.mark.asyncio
async def test_commissioning_build_surfaces_actionable_blockers():
    tenant_id = uuid4()
    db = AsyncMock()
    db.execute.side_effect = [
        FakeExecuteResult(count=0),  # source files
        FakeExecuteResult(count=0),  # knowledge entries
        FakeExecuteResult(count=0),  # knowledge links
        FakeExecuteResult(rows=[]),  # integrations
        FakeExecuteResult(count=0),  # enabled bindings
        FakeExecuteResult(count=0),  # completed sync runs
        FakeExecuteResult(count=0),  # synced assets
        FakeExecuteResult(count=0),  # completed exports
        FakeExecuteResult(count=0),  # exportable documents
        FakeExecuteResult(rows=[]),  # live providers
        FakeExecuteResult(count=0),  # active users
        FakeExecuteResult(count=0),  # roles
        FakeExecuteResult(count=0),  # audit logs
        FakeExecuteResult(count=0),  # policies
        FakeExecuteResult(count=0),  # field permissions
        FakeExecuteResult(count=0),  # metric events
        FakeExecuteResult(count=0),  # quota usages
        FakeExecuteResult(count=0),  # active alert rules
        FakeExecuteResult(count=0),  # work items
        FakeExecuteResult(count=0),  # done work items
        FakeExecuteResult(count=0),  # active work items
        FakeExecuteResult(count=0),  # blocked work items
        FakeExecuteResult(count=0),  # overdue work items
        FakeExecuteResult(count=0),  # notification preferences
        FakeExecuteResult(count=0),  # unacknowledged required notifications
        FakeExecuteResult(count=0),  # escalated notifications
        FakeExecuteResult(count=0),  # notification events
        FakeExecuteResult(count=0),  # sent notification events
        FakeExecuteResult(count=0),  # failed notification events
    ]

    with patch(
        "app.domains.ops.capability_commissioning.CapabilityReadinessService.build",
        AsyncMock(return_value=readiness_response(tenant_id=tenant_id)),
    ):
        response = await CapabilityCommissioningService(db).build(tenant_id)

    checks = {check.key: check for check in response.checks}
    assert response.production_usable is False
    assert checks["live_llm_provider"].status == "failed"
    assert checks["live_llm_provider"].action.href == "/providers"
    assert checks["knowledge_graph_evidence"].status == "failed"
    assert checks["knowledge_graph_evidence"].action.href == "/projects"
    assert checks["external_integration_project_sync"].status == "failed"
    assert checks["external_integration_project_sync"].action.href == "/settings"
    assert checks["collaboration_execution_evidence"].status == "failed"
    assert checks["collaboration_execution_evidence"].action.href == "/team"
    assert checks["notification_alert_handling_evidence"].status == "failed"
    assert checks["notification_alert_handling_evidence"].action.href == "/health"
    assert checks["export_validation"].status == "failed"
    assert checks["export_validation"].action.href == "/exports"
    assert checks["team_permission_audit"].status == "failed"
    assert checks["team_permission_audit"].action.href == "/team"
    assert checks["ops_observability_evidence"].status == "failed"
    assert checks["ops_observability_evidence"].action.href == "/health"


@pytest.mark.asyncio
async def test_commissioning_returns_structured_setup_requirements_and_requires_validation_evidence():
    tenant_id = uuid4()
    configured_integration = MagicMock()
    configured_integration.config_json = {
        "base_url": "https://jira.example.test",
        "api_key": "live-token",
    }
    configured_integration.last_sync_at = None
    live_provider = MagicMock()
    live_provider.status = "active"
    live_provider.provider_type = "llm"
    live_provider.config_json = {"api_key": "live-secret", "base_url": "https://api.example.test"}
    live_provider.name = "Live LLM"

    db = AsyncMock()
    db.execute.side_effect = [
        FakeExecuteResult(count=3),  # source files
        FakeExecuteResult(count=12),  # knowledge entries
        FakeExecuteResult(count=8),  # knowledge links
        FakeExecuteResult(rows=[configured_integration]),  # configured integrations
        FakeExecuteResult(count=0),  # enabled bindings
        FakeExecuteResult(count=0),  # completed sync runs
        FakeExecuteResult(count=0),  # synced assets
        FakeExecuteResult(count=1),  # completed exports
        FakeExecuteResult(count=2),  # exportable documents
        FakeExecuteResult(rows=[live_provider]),  # live providers
        FakeExecuteResult(count=2),  # active users
        FakeExecuteResult(count=2),  # roles
        FakeExecuteResult(count=3),  # audit logs
        FakeExecuteResult(count=2),  # policies
        FakeExecuteResult(count=4),  # field permissions
        FakeExecuteResult(count=3),  # metric events
        FakeExecuteResult(count=2),  # quota usages
        FakeExecuteResult(count=1),  # active alert rules
        FakeExecuteResult(count=0),  # work items
        FakeExecuteResult(count=0),  # done work items
        FakeExecuteResult(count=0),  # active work items
        FakeExecuteResult(count=0),  # blocked work items
        FakeExecuteResult(count=0),  # overdue work items
        FakeExecuteResult(count=0),  # notification preferences
        FakeExecuteResult(count=0),  # unacknowledged required notifications
        FakeExecuteResult(count=0),  # escalated notifications
        FakeExecuteResult(count=0),  # notification events
        FakeExecuteResult(count=0),  # sent notification events
        FakeExecuteResult(count=0),  # failed notification events
    ]

    with patch(
        "app.domains.ops.capability_commissioning.CapabilityReadinessService.build",
        AsyncMock(return_value=readiness_response(tenant_id=tenant_id, production_ready=True)),
    ):
        response = await CapabilityCommissioningService(db).build(tenant_id)

    checks = {check.key: check for check in response.checks}
    provider_check = checks["live_llm_provider"]
    integration_check = checks["external_integration_connectivity"]

    assert provider_check.configuration_requirements["required_fields"] == [
        "api_key/token/service_key",
        "base_url",
        "model",
    ]
    assert "/api/v1/providers/{provider_id}/test" in provider_check.validation_steps
    assert "successful_live_provider_test" in provider_check.evidence_requirements

    assert integration_check.status == "failed"
    assert integration_check.evidence["configured_integration_count"] == 1
    assert integration_check.evidence["validated_integration_count"] == 0
    assert integration_check.configuration_requirements["required_fields"] == [
        "base_url",
        "api_key",
        "health_path",
        "sync_path",
    ]
    assert "/api/v1/integrations/providers/{integration_id}/test" in integration_check.validation_steps
    assert "integration.sync.completed event or last_sync_at" in integration_check.evidence_requirements
    assert response.production_usable is False


@pytest.mark.asyncio
async def test_commissioning_run_marks_selected_checks_from_current_evidence():
    tenant_id = uuid4()
    db = AsyncMock()
    db.execute.side_effect = [
        FakeExecuteResult(count=3),  # source files
        FakeExecuteResult(count=12),  # knowledge entries
        FakeExecuteResult(count=8),  # knowledge links
        FakeExecuteResult(rows=[object()]),  # integrations
        FakeExecuteResult(count=1),  # enabled bindings
        FakeExecuteResult(count=1),  # completed sync runs
        FakeExecuteResult(count=1),  # synced assets
        FakeExecuteResult(count=1),  # completed exports
        FakeExecuteResult(count=2),  # exportable documents
        FakeExecuteResult(rows=[object()]),  # live providers
        FakeExecuteResult(count=2),  # active users
        FakeExecuteResult(count=2),  # roles
        FakeExecuteResult(count=3),  # audit logs
        FakeExecuteResult(count=2),  # policies
        FakeExecuteResult(count=4),  # field permissions
        FakeExecuteResult(count=3),  # metric events
        FakeExecuteResult(count=2),  # quota usages
        FakeExecuteResult(count=1),  # active alert rules
        FakeExecuteResult(count=2),  # work items
        FakeExecuteResult(count=1),  # done work items
        FakeExecuteResult(count=1),  # active work items
        FakeExecuteResult(count=0),  # blocked work items
        FakeExecuteResult(count=0),  # overdue work items
        FakeExecuteResult(count=1),  # notification preferences
        FakeExecuteResult(count=0),  # unacknowledged required notifications
        FakeExecuteResult(count=0),  # escalated notifications
        FakeExecuteResult(count=1),  # notification events
        FakeExecuteResult(count=1),  # sent notification events
        FakeExecuteResult(count=0),  # failed notification events
    ]

    with patch(
        "app.domains.ops.capability_commissioning.CapabilityReadinessService.build",
        AsyncMock(return_value=readiness_response(tenant_id=tenant_id, production_ready=True)),
    ):
        response = await CapabilityCommissioningService(db).run(
            tenant_id,
            CapabilityCommissioningRunRequest(
                checks=["live_llm_provider", "knowledge_graph_evidence", "export_validation"],
            ),
        )

    checks = {check.key: check for check in response.checks}
    assert response.executed is True
    assert response.production_usable is True
    assert checks["live_llm_provider"].run_status == "passed"
    assert checks["knowledge_graph_evidence"].run_status == "passed"
    assert checks["export_validation"].run_status == "passed"
