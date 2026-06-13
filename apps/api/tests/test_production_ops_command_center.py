"""Production operations command center tests."""

from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest

from app.domains.ops.schemas import (
    CapabilityCommissioningAction,
    CapabilityCommissioningCheck,
    CapabilityCommissioningResponse,
    CapabilityReadinessItem,
    CapabilityReadinessResponse,
)


def readiness_response(tenant_id):
    return CapabilityReadinessResponse(
        generated_at=datetime.now(timezone.utc),
        tenant_id=tenant_id,
        overall_status="degraded",
        overall_score=72,
        production_ready=False,
        capabilities=[
            CapabilityReadinessItem(
                key="provider_llm",
                label="Provider 与 LLM 生成",
                status="ready",
                score=90,
                summary="真实 LLM Provider 已配置。",
                evidence={"live_llm_count": 1},
                blockers=[],
                recommended_actions=[],
            ),
            CapabilityReadinessItem(
                key="notification_alert_handling",
                label="通知确认与告警处置",
                status="blocked",
                score=45,
                summary="仍有未确认高优先级通知。",
                evidence={"unacknowledged_notifications": 2, "failed_notification_event_count": 1},
                blockers=["2 条关键通知未确认"],
                recommended_actions=["进入通知中心确认或升级关键通知。"],
            ),
        ],
    )


def commissioning_response(tenant_id, readiness):
    return CapabilityCommissioningResponse(
        generated_at=datetime.now(timezone.utc),
        tenant_id=tenant_id,
        production_usable=False,
        executed=False,
        overall_status="blocked",
        overall_score=68,
        readiness=readiness,
        checks=[
            CapabilityCommissioningCheck(
                key="notification_alert_handling_evidence",
                capability_key="notification_alert_handling",
                label="通知确认与告警投递校准",
                status="failed",
                severity="critical",
                summary="存在失败投递和未确认通知。",
                evidence={"failed_notification_event_count": 1},
                blockers=["告警邮件投递失败"],
                action=CapabilityCommissioningAction(
                    label="处理通知",
                    href="/notifications",
                    api_endpoint="/api/v1/ops/notification-deliveries",
                    method="GET",
                    description="进入通知中心处理未确认和失败投递。",
                ),
                can_run=True,
                validation_steps=["Retry failed delivery"],
                evidence_requirements=["sent notification delivery"],
            ),
            CapabilityCommissioningCheck(
                key="ops_observability_evidence",
                capability_key="ops_observability",
                label="运维观测校准",
                status="warning",
                severity="high",
                summary="缺少活跃告警规则。",
                evidence={"active_alert_rule_count": 0},
                blockers=["未配置活跃告警规则"],
                action=CapabilityCommissioningAction(
                    label="检查运维监控",
                    href="/system-health",
                    api_endpoint="/api/v1/ops/capabilities/commissioning",
                    method="GET",
                    description="进入系统健康页补齐告警规则证据。",
                ),
                can_run=True,
                validation_steps=[],
                evidence_requirements=[],
            ),
        ],
        summary={"failed": 1, "warning": 1},
        next_steps=["先处理通知中心关键阻塞。"],
    )


@pytest.mark.asyncio
async def test_production_ops_command_center_summarizes_release_blockers():
    from app.domains.ops.production_command_center import ProductionOpsCommandCenterService

    tenant_id = uuid4()
    readiness = readiness_response(tenant_id)
    commissioning = commissioning_response(tenant_id, readiness)

    with (
        patch(
            "app.domains.ops.production_command_center.CapabilityReadinessService.build",
            AsyncMock(return_value=readiness),
        ),
        patch(
            "app.domains.ops.production_command_center.CapabilityCommissioningService.build",
            AsyncMock(return_value=commissioning),
        ),
    ):
        result = await ProductionOpsCommandCenterService(AsyncMock()).build(tenant_id)

    assert result.release_gate.status == "blocked"
    assert result.release_gate.can_release is False
    assert result.release_gate.readiness_score == 72
    assert result.release_gate.commissioning_score == 68
    assert result.summary["blocked_capabilities"] == 1
    assert result.summary["critical_blockers"] == 1
    assert result.summary["runnable_checks"] == 2
    assert result.blockers[0].severity == "critical"
    assert result.blockers[0].source == "commissioning"
    assert result.blockers[0].action_href == "/notifications"
    assert any(action.href == "/notifications" for action in result.priority_actions)
    assert "先处理通知中心关键阻塞。" in result.next_steps
