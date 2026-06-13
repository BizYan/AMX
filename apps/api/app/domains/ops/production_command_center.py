"""Production operations command center aggregation service."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.ops.capability_commissioning import CapabilityCommissioningService
from app.domains.ops.capability_readiness import CapabilityReadinessService
from app.domains.ops.schemas import (
    CapabilityCommissioningCheck,
    CapabilityCommissioningResponse,
    CapabilityReadinessItem,
    CapabilityReadinessResponse,
    ProductionOpsBlocker,
    ProductionOpsCommandCenterResponse,
    ProductionOpsPriorityAction,
    ProductionOpsReleaseGate,
)


SEVERITY_RANK = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "info": 3,
}


class ProductionOpsCommandCenterService:
    """Build an actionable production operations snapshot from existing evidence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build(self, tenant_id: UUID | None) -> ProductionOpsCommandCenterResponse:
        readiness = await CapabilityReadinessService(self.db).build(tenant_id)
        commissioning = await CapabilityCommissioningService(self.db).build(tenant_id)
        blockers = self._build_blockers(readiness, commissioning)
        priority_actions = self._build_priority_actions(blockers)
        summary = self._build_summary(readiness, commissioning, blockers)
        release_gate = self._build_release_gate(readiness, commissioning, summary)
        next_steps = self._build_next_steps(readiness, commissioning, priority_actions)

        return ProductionOpsCommandCenterResponse(
            generated_at=datetime.now(timezone.utc),
            tenant_id=tenant_id,
            release_gate=release_gate,
            summary=summary,
            blockers=blockers,
            priority_actions=priority_actions,
            readiness=readiness,
            commissioning=commissioning,
            next_steps=next_steps,
        )

    def _build_blockers(
        self,
        readiness: CapabilityReadinessResponse,
        commissioning: CapabilityCommissioningResponse,
    ) -> list[ProductionOpsBlocker]:
        blockers: list[ProductionOpsBlocker] = []

        for check in commissioning.checks:
            if check.status not in {"failed", "warning"} and check.run_status not in {"failed", "skipped"}:
                continue
            blockers.append(self._commissioning_blocker(check))

        commissioning_capabilities = {blocker.capability_key for blocker in blockers}
        for capability in readiness.capabilities:
            if capability.status == "ready" or not capability.blockers:
                continue
            if capability.key in commissioning_capabilities:
                continue
            blockers.append(self._readiness_blocker(capability))

        return sorted(
            blockers,
            key=lambda item: (
                SEVERITY_RANK.get(item.severity, 9),
                item.source != "commissioning",
                item.label,
            ),
        )

    def _commissioning_blocker(self, check: CapabilityCommissioningCheck) -> ProductionOpsBlocker:
        summary = check.blockers[0] if check.blockers else check.summary
        return ProductionOpsBlocker(
            key=check.key,
            capability_key=check.capability_key,
            label=check.label,
            severity=check.severity,
            source="commissioning",
            summary=summary,
            action_label=check.action.label,
            action_href=check.action.href,
            api_endpoint=check.action.api_endpoint,
        )

    def _readiness_blocker(self, capability: CapabilityReadinessItem) -> ProductionOpsBlocker:
        severity = "critical" if capability.status == "blocked" else "high"
        return ProductionOpsBlocker(
            key=f"{capability.key}_readiness",
            capability_key=capability.key,
            label=capability.label,
            severity=severity,
            source="readiness",
            summary=capability.blockers[0],
            action_label="处理能力阻塞",
            action_href=self._capability_action_href(capability),
        )

    def _build_priority_actions(self, blockers: list[ProductionOpsBlocker]) -> list[ProductionOpsPriorityAction]:
        actions: list[ProductionOpsPriorityAction] = []
        seen: set[tuple[str, str]] = set()

        for blocker in blockers:
            if not blocker.action_href:
                continue
            key = (blocker.capability_key, blocker.action_href)
            if key in seen:
                continue
            seen.add(key)
            actions.append(
                ProductionOpsPriorityAction(
                    key=blocker.key,
                    label=blocker.action_label or blocker.label,
                    href=blocker.action_href,
                    capability_key=blocker.capability_key,
                    severity=blocker.severity,
                    description=blocker.summary,
                    api_endpoint=blocker.api_endpoint,
                )
            )

        return actions[:8]

    def _build_summary(
        self,
        readiness: CapabilityReadinessResponse,
        commissioning: CapabilityCommissioningResponse,
        blockers: list[ProductionOpsBlocker],
    ) -> dict[str, int]:
        return {
            "capabilities": len(readiness.capabilities),
            "ready_capabilities": sum(1 for item in readiness.capabilities if item.status == "ready"),
            "degraded_capabilities": sum(1 for item in readiness.capabilities if item.status == "degraded"),
            "blocked_capabilities": sum(1 for item in readiness.capabilities if item.status == "blocked"),
            "commissioning_checks": len(commissioning.checks),
            "failed_checks": sum(1 for item in commissioning.checks if item.status == "failed"),
            "warning_checks": sum(1 for item in commissioning.checks if item.status == "warning"),
            "runnable_checks": sum(1 for item in commissioning.checks if item.can_run),
            "critical_blockers": sum(1 for item in blockers if item.severity == "critical"),
            "high_blockers": sum(1 for item in blockers if item.severity == "high"),
        }

    def _build_release_gate(
        self,
        readiness: CapabilityReadinessResponse,
        commissioning: CapabilityCommissioningResponse,
        summary: dict[str, int],
    ) -> ProductionOpsReleaseGate:
        can_release = (
            readiness.production_ready
            and commissioning.production_usable
            and summary["critical_blockers"] == 0
            and summary["failed_checks"] == 0
        )

        if can_release:
            status = "ready"
            message = "核心能力和投产校准均已通过，可以进入发布窗口。"
        elif summary["critical_blockers"] > 0 or summary["failed_checks"] > 0 or summary["blocked_capabilities"] > 0:
            status = "blocked"
            message = "存在关键阻塞，发布前必须完成处置和复核。"
        else:
            status = "attention"
            message = "仍有高优先级关注项，建议完成校准后再发布。"

        return ProductionOpsReleaseGate(
            status=status,
            can_release=can_release,
            readiness_score=readiness.overall_score,
            commissioning_score=commissioning.overall_score,
            summary=message,
        )

    def _build_next_steps(
        self,
        readiness: CapabilityReadinessResponse,
        commissioning: CapabilityCommissioningResponse,
        actions: list[ProductionOpsPriorityAction],
    ) -> list[str]:
        steps: list[str] = []
        steps.extend(commissioning.next_steps)
        for capability in readiness.capabilities:
            steps.extend(capability.recommended_actions[:1])
        steps.extend(action.description for action in actions[:3])

        unique_steps: list[str] = []
        for step in steps:
            if step and step not in unique_steps:
                unique_steps.append(step)

        return unique_steps[:8] or ["当前没有需要立即处理的生产运维动作。"]

    def _capability_action_href(self, capability: CapabilityReadinessItem) -> str:
        mapping = {
            "provider_llm": "/providers",
            "provider_operations": "/providers",
            "knowledge_graph": "/knowledge/graph",
            "orchestration_runtime": "/agents",
            "external_integrations": "/settings?tab=integrations",
            "external_integration_sync": "/settings?tab=integrations",
            "collaboration_execution": "/collaboration",
            "notification_alert_handling": "/notifications",
            "export_release": "/exports",
            "team_access": "/team",
            "ops_observability": "/system-health",
        }
        return mapping.get(capability.key, capability.recommended_actions[0] if capability.recommended_actions else "/system-health")
