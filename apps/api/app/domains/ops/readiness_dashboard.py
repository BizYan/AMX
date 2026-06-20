"""Ops readiness dashboard evidence aggregation."""

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.agent.models import AgentRun, AgentRunStatus
from app.domains.ops.capability_commissioning import CapabilityCommissioningService
from app.domains.ops.capability_readiness import CapabilityReadinessService
from app.domains.ops.models import AlertRule, MetricEvent, NotificationEvent
from app.domains.ops.schemas import (
    CapabilityCommissioningResponse,
    CapabilityReadinessResponse,
    HealthResponse,
    OpsReadinessCriticalFailure,
    OpsReadinessDashboardResponse,
)
from app.domains.providers.readiness import build_provider_readiness_summary
from app.domains.providers.registry import ProviderRegistry
from app.domains.providers.schemas import ProviderReadinessSummary
from app.services.quota_service import QuotaService, QuotaType


class OpsReadinessDashboardService:
    """Build a dashboard-ready, sanitized ops evidence snapshot."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build(self, tenant_id: UUID | None) -> OpsReadinessDashboardResponse:
        generated_at = datetime.now(timezone.utc)
        provider_readiness = await self._build_provider_readiness(tenant_id)
        capability_readiness = await self._build_capability_readiness(tenant_id)
        capability_commissioning = await self._build_capability_commissioning(tenant_id)
        critical_failures = await self._build_latest_critical_failures(tenant_id)

        return OpsReadinessDashboardResponse(
            generated_at=generated_at,
            tenant_id=tenant_id,
            health=HealthResponse(status="healthy", version="1.0.0").model_dump(),
            provider_readiness=provider_readiness,
            capability_readiness=capability_readiness,
            capability_commissioning=capability_commissioning,
            quota=await self._build_quota(tenant_id),
            metrics=await self._build_metrics(tenant_id),
            alerts=await self._build_alerts(tenant_id),
            deployment=self._build_deployment_evidence(),
            latest_smoke=self._build_smoke_evidence(),
            gitnexus=self._build_gitnexus_evidence(),
            agent_run_health=await self._build_agent_run_health(tenant_id),
            latest_critical_failures=critical_failures,
            evidence_export={
                "format": "json",
                "sanitized": True,
                "generated_at": generated_at.isoformat(),
                "included_sections": [
                    "health",
                    "provider_readiness",
                    "capability_readiness",
                    "capability_commissioning",
                    "quota",
                    "metrics",
                    "alerts",
                    "deployment",
                    "latest_smoke",
                    "gitnexus",
                    "agent_run_health",
                    "latest_critical_failures",
                ],
            },
        )

    async def _build_provider_readiness(self, tenant_id: UUID | None) -> ProviderReadinessSummary:
        registry = ProviderRegistry(self.db)
        providers, _ = await registry.list_providers(
            tenant_id=tenant_id,
            skip=0,
            limit=100,
        )
        return build_provider_readiness_summary(
            tenant_id=tenant_id,
            providers=providers,
        )

    async def _build_capability_readiness(self, tenant_id: UUID | None) -> CapabilityReadinessResponse:
        return await CapabilityReadinessService(self.db).build(tenant_id)

    async def _build_capability_commissioning(self, tenant_id: UUID | None) -> CapabilityCommissioningResponse:
        return await CapabilityCommissioningService(self.db).build(tenant_id)

    async def _build_quota(self, tenant_id: UUID | None) -> dict[str, object]:
        if tenant_id is None:
            return {
                "status": "not_scoped",
                "used": 0,
                "limit": 0,
                "remaining": 0,
                "usage_percent": 0.0,
                "reset_at": None,
            }

        quota = await QuotaService(self.db).get_quota_usage(tenant_id, QuotaType.API_CALLS)
        if quota is None:
            return {
                "status": "not_recorded",
                "used": 0,
                "limit": 0,
                "remaining": 0,
                "usage_percent": 0.0,
                "reset_at": None,
            }

        used = int(quota.used_amount)
        limit = int(quota.limit_amount)
        remaining = max(limit - used, 0)
        usage_percent = round((used / limit * 100), 2) if limit > 0 else 0.0
        status = "blocked" if limit > 0 and remaining <= 0 else "attention" if usage_percent >= 80 else "healthy"
        return {
            "status": status,
            "used": used,
            "limit": limit,
            "remaining": remaining,
            "usage_percent": usage_percent,
            "reset_at": quota.reset_at,
        }

    async def _build_metrics(self, tenant_id: UUID | None) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=24)
        tenant_filter = [MetricEvent.tenant_id == tenant_id] if tenant_id else []

        total_result = await self.db.execute(
            select(func.count(MetricEvent.id)).where(
                and_(MetricEvent.recorded_at >= since, *tenant_filter)
            )
        )
        error_result = await self.db.execute(
            select(func.count(MetricEvent.id)).where(
                and_(MetricEvent.recorded_at >= since, MetricEvent.metric_type == "error", *tenant_filter)
            )
        )
        latency_result = await self.db.execute(
            select(func.avg(MetricEvent.value)).where(
                and_(
                    MetricEvent.recorded_at >= since,
                    MetricEvent.metric_name.in_(["latency_ms", "api_latency_ms"]),
                    *tenant_filter,
                )
            )
        )
        total = int(total_result.scalar_one() or 0)
        errors = int(error_result.scalar_one() or 0)
        avg_latency = float(latency_result.scalar_one() or 0)
        return {
            "window": "24h",
            "total_events": total,
            "error_events": errors,
            "error_rate_percent": round((errors / total * 100), 2) if total else 0.0,
            "avg_latency_ms": round(avg_latency, 2),
        }

    async def _build_alerts(self, tenant_id: UUID | None) -> dict[str, object]:
        tenant_filter = [AlertRule.tenant_id == tenant_id] if tenant_id else []
        notification_filter = [NotificationEvent.tenant_id == tenant_id] if tenant_id else []

        rules_result = await self.db.execute(
            select(func.count(AlertRule.id)).where(and_(AlertRule.is_active.is_(True), *tenant_filter))
        )
        failed_result = await self.db.execute(
            select(func.count(NotificationEvent.id)).where(
                and_(NotificationEvent.status == "failed", *notification_filter)
            )
        )
        pending_result = await self.db.execute(
            select(func.count(NotificationEvent.id)).where(
                and_(NotificationEvent.status.in_(["pending", "retrying"]), *notification_filter)
            )
        )
        return {
            "active_rules": int(rules_result.scalar_one() or 0),
            "failed_notifications": int(failed_result.scalar_one() or 0),
            "pending_notifications": int(pending_result.scalar_one() or 0),
        }

    def _build_deployment_evidence(self) -> dict[str, object]:
        ref = os.getenv("AMX_DEPLOYED_REF") or os.getenv("DEPLOYED_REF")
        sha = os.getenv("AMX_DEPLOYED_SHA") or os.getenv("DEPLOYED_SHA") or os.getenv("GIT_COMMIT")
        deployed_at = os.getenv("AMX_DEPLOYED_AT")
        return {
            "status": "recorded" if ref or sha else "not_recorded",
            "ref": ref,
            "sha": sha,
            "deployed_at": deployed_at,
            "source": "runtime_environment",
        }

    def _build_smoke_evidence(self) -> dict[str, object]:
        status = os.getenv("AMX_LAST_AUTHENTICATED_SMOKE_STATUS")
        run_url = os.getenv("AMX_LAST_AUTHENTICATED_SMOKE_RUN_URL")
        checked_at = os.getenv("AMX_LAST_AUTHENTICATED_SMOKE_AT")
        return {
            "status": status or "not_recorded",
            "run_url": run_url,
            "checked_at": checked_at,
            "source": "runtime_environment",
        }

    def _build_gitnexus_evidence(self) -> dict[str, object]:
        refresh_status = os.getenv("AMX_GITNEXUS_REFRESH_STATUS")
        indexed_sha = os.getenv("AMX_GITNEXUS_INDEXED_SHA")
        checked_at = os.getenv("AMX_GITNEXUS_REFRESH_AT")
        return {
            "refresh_status": refresh_status or "not_recorded",
            "indexed_sha": indexed_sha,
            "checked_at": checked_at,
            "source": "runtime_environment",
        }

    async def _build_agent_run_health(self, tenant_id: UUID | None) -> dict[str, object]:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        tenant_filter = [AgentRun.tenant_id == tenant_id] if tenant_id else []

        async def count_for(statuses: list[str], *, recent: bool = False) -> int:
            filters = [AgentRun.status.in_(statuses), *tenant_filter]
            if recent:
                filters.append(AgentRun.created_at >= since)
            result = await self.db.execute(select(func.count(AgentRun.id)).where(and_(*filters)))
            return int(result.scalar_one() or 0)

        running = await count_for([AgentRunStatus.RUNNING.value, AgentRunStatus.PENDING.value])
        failed_24h = await count_for([AgentRunStatus.FAILED.value], recent=True)
        completed_24h = await count_for([AgentRunStatus.COMPLETED.value], recent=True)
        status = "attention" if failed_24h else "healthy"
        return {
            "status": status,
            "running": running,
            "failed_24h": failed_24h,
            "completed_24h": completed_24h,
        }

    async def _build_latest_critical_failures(self, tenant_id: UUID | None) -> list[OpsReadinessCriticalFailure]:
        failures: list[OpsReadinessCriticalFailure] = []
        tenant_filter = [MetricEvent.tenant_id == tenant_id] if tenant_id else []
        metric_result = await self.db.execute(
            select(MetricEvent)
            .where(
                and_(
                    or_(
                        MetricEvent.metric_type.in_(["error", "failure", "critical"]),
                        MetricEvent.metric_name.ilike("%error%"),
                        MetricEvent.metric_name.ilike("%failure%"),
                    ),
                    *tenant_filter,
                )
            )
            .order_by(MetricEvent.recorded_at.desc())
            .limit(5)
        )
        for metric in metric_result.scalars().all():
            failures.append(
                OpsReadinessCriticalFailure(
                    source="metric",
                    severity="critical" if metric.metric_type == "critical" else "high",
                    summary=f"{metric.metric_type}:{metric.metric_name}",
                    occurred_at=metric.recorded_at,
                    status="recorded",
                    action_href="/system-health",
                )
            )

        notification_filter = [NotificationEvent.tenant_id == tenant_id] if tenant_id else []
        notification_result = await self.db.execute(
            select(NotificationEvent)
            .where(and_(NotificationEvent.status == "failed", *notification_filter))
            .order_by(NotificationEvent.created_at.desc())
            .limit(max(0, 5 - len(failures)))
        )
        for notification in notification_result.scalars().all():
            failures.append(
                OpsReadinessCriticalFailure(
                    source="notification",
                    severity="high",
                    summary=notification.title,
                    occurred_at=notification.created_at,
                    status=notification.status,
                    action_href="/notifications",
                )
            )

        return failures[:5]
