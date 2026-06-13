"""Backend-authoritative quota production operations command center."""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.ops.models import MetricEvent
from app.domains.ops.schemas import (
    QuotaCommandCenterAction,
    QuotaCommandCenterGate,
    QuotaCommandCenterRateLimitRisk,
    QuotaCommandCenterResponse,
    QuotaCommandCenterRiskItem,
    QuotaCommandCenterSummary,
)
from app.domains.providers.models import Provider, ProviderStatus
from app.services.circuit_breaker import get_provider_circuit_breaker
from app.services.quota_service import QuotaService, QuotaType


ENDPOINT_LIMITS = (
    ("/api/documents", 1000),
    ("/api/knowledge", 500),
    ("/api/agent", 100),
    ("/api/providers", 200),
    ("/api/projects", 300),
)


class QuotaCommandCenterService:
    """Build the authoritative quota operating gate and response actions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build(self, tenant_id: UUID) -> QuotaCommandCenterResponse:
        return self.build_from_evidence(await self._collect_evidence(tenant_id))

    async def _collect_evidence(self, tenant_id: UUID) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        quota = await QuotaService(self.db).get_quota_usage(tenant_id, QuotaType.API_CALLS)
        period_start = self.resolve_period_start(quota.reset_at if quota else None, now)

        async def scalar(query) -> float:
            result = await self.db.execute(query)
            return float(result.scalar_one_or_none() or 0)

        total_requests = await scalar(
            select(func.count(MetricEvent.id)).where(
                and_(
                    MetricEvent.tenant_id == tenant_id,
                    MetricEvent.metric_type == "api_call",
                    MetricEvent.recorded_at >= period_start,
                )
            )
        )
        successful_requests = await scalar(
            select(func.count(MetricEvent.id)).where(
                and_(
                    MetricEvent.tenant_id == tenant_id,
                    MetricEvent.metric_type == "api_call",
                    MetricEvent.metric_name.notlike("%error%"),
                    MetricEvent.recorded_at >= period_start,
                )
            )
        )
        failed_requests = await scalar(
            select(func.count(MetricEvent.id)).where(
                and_(
                    MetricEvent.tenant_id == tenant_id,
                    MetricEvent.metric_type == "error",
                    MetricEvent.recorded_at >= period_start,
                )
            )
        )
        average_latency_ms = await scalar(
            select(func.avg(MetricEvent.value)).where(
                and_(
                    MetricEvent.tenant_id == tenant_id,
                    MetricEvent.metric_type == "api_call",
                    MetricEvent.metric_name == "latency_ms",
                    MetricEvent.recorded_at >= period_start,
                )
            )
        )

        window_start = now - timedelta(hours=1)
        reset_at = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        rate_limits = []
        for endpoint, limit in ENDPOINT_LIMITS:
            used = await scalar(
                select(func.count(MetricEvent.id)).where(
                    and_(
                        MetricEvent.tenant_id == tenant_id,
                        MetricEvent.metric_type == "api_call",
                        MetricEvent.dimensions["endpoint"].astext == endpoint,
                        MetricEvent.recorded_at >= window_start,
                    )
                )
            )
            rate_limits.append(
                {
                    "endpoint": endpoint,
                    "limit": limit,
                    "remaining": max(limit - int(used), 0),
                    "reset_at": reset_at,
                }
            )

        provider_result = await self.db.execute(
            select(Provider).where(
                Provider.tenant_id == tenant_id,
                Provider.deleted_at.is_(None),
            )
        )
        provider_risks = []
        for provider in provider_result.scalars().all():
            ops_profile = (provider.config_json or {}).get("ops_profile", {})
            health = ops_profile.get("health", "healthy")
            if provider.status != ProviderStatus.ACTIVE.value or health != "healthy":
                provider_risks.append(
                    {
                        "name": provider.name,
                        "status": health if health != "healthy" else provider.status,
                        "detail": ops_profile.get("quota_impact", "Provider health may amplify quota consumption."),
                    }
                )

        breaker_states = get_provider_circuit_breaker().get_all_states()
        open_breakers = [name for name, state in breaker_states.items() if state.get("state") == "open"]

        return {
            "tenant_id": tenant_id,
            "generated_at": now,
            "api_used": quota.used_amount if quota else total_requests,
            "api_limit": quota.limit_amount if quota else 10000,
            "api_reset_at": quota.reset_at if quota else None,
            "total_requests": total_requests,
            "successful_requests": successful_requests,
            "failed_requests": failed_requests,
            "average_latency_ms": average_latency_ms,
            "rate_limits": rate_limits,
            "provider_risks": provider_risks,
            "open_breakers": open_breakers,
        }

    @staticmethod
    def resolve_period_start(reset_at: datetime | None, now: datetime) -> datetime:
        """Use a historical reset boundary, never a future next-reset timestamp."""
        if reset_at and reset_at <= now:
            return reset_at
        return now - timedelta(days=30)

    @classmethod
    def build_from_evidence(cls, evidence: dict[str, Any]) -> QuotaCommandCenterResponse:
        api_used = int(evidence.get("api_used") or 0)
        api_limit = int(evidence.get("api_limit") or 0)
        api_remaining = max(api_limit - api_used, 0)
        api_usage_percent = round((api_used / api_limit) * 100, 1) if api_limit else 0.0
        total_requests = int(evidence.get("total_requests") or 0)
        successful_requests = int(evidence.get("successful_requests") or 0)
        failed_requests = int(evidence.get("failed_requests") or 0)
        failure_rate = round((failed_requests / total_requests) * 100, 1) if total_requests else 0.0
        daily_burn = max(round(total_requests / 30), 1) if total_requests else 0
        projected_days_remaining = api_remaining // daily_burn if daily_burn else None
        provider_risks = evidence.get("provider_risks") or []
        open_breakers = evidence.get("open_breakers") or []

        rate_limit_risks = [
            QuotaCommandCenterRateLimitRisk(
                endpoint=item["endpoint"],
                limit=int(item["limit"]),
                remaining=int(item["remaining"]),
                used_percentage=round(((item["limit"] - item["remaining"]) / item["limit"]) * 100, 1)
                if item["limit"]
                else 0.0,
                reset_at=item["reset_at"],
            )
            for item in evidence.get("rate_limits") or []
            if item["limit"] and item["remaining"] / item["limit"] <= 0.1
        ]

        risks: list[QuotaCommandCenterRiskItem] = []
        actions: list[QuotaCommandCenterAction] = []

        def add_risk(code: str, severity: str, title: str, detail: str, count: int, href: str) -> None:
            risks.append(
                QuotaCommandCenterRiskItem(
                    code=code,
                    severity=severity,
                    title=title,
                    detail=detail,
                    count=count,
                    href=href,
                )
            )
            actions.append(
                QuotaCommandCenterAction(
                    code=code,
                    title=f"处理{title}",
                    description=detail,
                    href=href,
                    priority=severity,
                )
            )

        if api_usage_percent >= 95:
            add_risk("api_quota_blocked", "critical", "API 配额临界", f"API 配额已使用 {api_usage_percent}%。", 1, "/quotas")
        elif api_usage_percent >= 80:
            add_risk("api_quota_attention", "high", "API 配额偏高", f"API 配额已使用 {api_usage_percent}%。", 1, "/quotas")
        if failure_rate >= 5:
            add_risk("failure_rate_attention", "high", "请求失败率偏高", f"近期请求失败率为 {failure_rate}%。", failed_requests, "/system-health")
        if rate_limit_risks:
            add_risk("rate_limit_attention", "high", "端点限流风险", "部分端点剩余限额低于或等于 10%。", len(rate_limit_risks), "/quotas")
        if provider_risks:
            add_risk("provider_health_attention", "high", "Provider 健康风险", "异常 Provider 可能放大重试与配额消耗。", len(provider_risks), "/providers")
        if open_breakers:
            add_risk("open_circuit_breaker", "critical", "熔断器已打开", "Provider 熔断器打开，生产调用已受阻。", len(open_breakers), "/providers")

        blockers = [item.detail for item in risks if item.severity == "critical"]
        warnings = [item.detail for item in risks if item.severity != "critical"]
        if blockers:
            gate = QuotaCommandCenterGate(
                status="blocked",
                can_operate=False,
                label="生产操作受阻",
                summary="存在必须立即处置的配额或 Provider 阻断。",
                blockers=blockers,
                warnings=warnings,
            )
        elif warnings:
            gate = QuotaCommandCenterGate(
                status="attention",
                can_operate=True,
                label="需要关注",
                summary="当前仍可运行，但应在继续放量前处置高风险项。",
                warnings=warnings,
            )
        else:
            gate = QuotaCommandCenterGate(
                status="passed",
                can_operate=True,
                label="运行正常",
                summary="配额、限流、Provider 与熔断器均在安全范围内。",
            )

        severity_rank = {"critical": 0, "high": 1, "medium": 2}
        risks.sort(key=lambda item: (severity_rank.get(item.severity, 9), item.code))
        actions.sort(key=lambda item: (severity_rank.get(item.priority, 9), item.code))

        return QuotaCommandCenterResponse(
            generated_at=evidence["generated_at"],
            tenant_id=evidence["tenant_id"],
            release_gate=gate,
            summary=QuotaCommandCenterSummary(
                api_used=api_used,
                api_limit=api_limit,
                api_remaining=api_remaining,
                api_usage_percent=api_usage_percent,
                total_requests=total_requests,
                successful_requests=successful_requests,
                failed_requests=failed_requests,
                failure_rate_percent=failure_rate,
                average_latency_ms=round(float(evidence.get("average_latency_ms") or 0), 2),
                daily_burn=daily_burn,
                projected_days_remaining=projected_days_remaining,
                risky_endpoint_count=len(rate_limit_risks),
                provider_risk_count=len(provider_risks),
                open_breaker_count=len(open_breakers),
            ),
            risk_items=risks,
            priority_actions=actions,
            rate_limit_risks=rate_limit_risks,
        )
