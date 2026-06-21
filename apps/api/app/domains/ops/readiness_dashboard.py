"""Ops readiness dashboard and sanitized release evidence aggregation."""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
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
    OpsReleaseEvidence,
    OpsReleaseEvidenceBlocker,
    OpsReleaseEvidenceExportResponse,
)
from app.domains.providers.readiness import build_provider_readiness_summary
from app.domains.providers.registry import ProviderRegistry
from app.domains.providers.schemas import ProviderReadinessSummary
from app.services.quota_service import QuotaService, QuotaType


class OpsReadinessDashboardService:
    """Build a dashboard-ready, sanitized ops evidence snapshot."""

    _MAX_MANIFEST_BYTES = 64 * 1024
    _SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
    _SAFE_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
    _TAG_PATTERN = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$")
    _RUN_PATH_PATTERN = re.compile(r"^/BizYan/AMX/actions/runs/[0-9]+/?$")
    _STATUS_VALUES = {
        "attention",
        "blocked",
        "degraded",
        "failed",
        "healthy",
        "not_recorded",
        "passed",
        "ready",
    }
    _MANIFEST_KEYS = {
        "environment",
        "deployed_ref",
        "deployed_sha",
        "expected_sha",
        "release_tag",
        "candidate_verification_run_url",
        "production_deployment_run_url",
        "authenticated_smoke_run_url",
        "smoke_status",
        "provenance_status",
        "gitnexus_status",
        "gitnexus_indexed_sha",
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build(self, tenant_id: UUID | None) -> OpsReadinessDashboardResponse:
        generated_at = datetime.now(timezone.utc)
        provider_readiness = await self._build_provider_readiness(tenant_id)
        capability_readiness = await self._build_capability_readiness(tenant_id)
        capability_commissioning = await self._build_capability_commissioning(tenant_id)
        quota = await self._build_quota(tenant_id)
        agent_run_health = await self._build_agent_run_health(tenant_id)
        critical_failures = await self._build_latest_critical_failures(tenant_id)
        release_evidence = self._build_release_evidence(
            provider_production_ready=provider_readiness.production_ready,
            capability_production_ready=capability_readiness.production_ready,
            quota_status=str(quota.get("status") or "not_recorded"),
            agent_health_status=str(agent_run_health.get("status") or "not_recorded"),
            critical_failures=critical_failures,
            generated_at=generated_at,
        )

        return OpsReadinessDashboardResponse(
            generated_at=generated_at,
            tenant_id=tenant_id,
            health=HealthResponse(status="healthy", version="1.0.0").model_dump(),
            provider_readiness=provider_readiness,
            capability_readiness=capability_readiness,
            capability_commissioning=capability_commissioning,
            quota=quota,
            metrics=await self._build_metrics(tenant_id),
            alerts=await self._build_alerts(tenant_id),
            deployment=self._build_deployment_evidence(),
            latest_smoke=self._build_smoke_evidence(),
            gitnexus=self._build_gitnexus_evidence(),
            agent_run_health=agent_run_health,
            latest_critical_failures=critical_failures,
            release_evidence=release_evidence,
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
                    "release_evidence",
                ],
            },
        )

    async def build_export(self, tenant_id: UUID | None) -> OpsReleaseEvidenceExportResponse:
        """Build the canonical, sanitized release evidence JSON payload."""
        dashboard = await self.build(tenant_id)
        return OpsReleaseEvidenceExportResponse(
            generated_at=dashboard.generated_at,
            status=dashboard.release_evidence.status,
            release_evidence=dashboard.release_evidence,
            health=dashboard.health,
            provider_readiness=dashboard.provider_readiness,
            capability_readiness=dashboard.capability_readiness,
            capability_commissioning=dashboard.capability_commissioning,
            quota=dashboard.quota,
            latest_smoke=dashboard.latest_smoke,
            gitnexus=dashboard.gitnexus,
            agent_run_health=dashboard.agent_run_health,
            latest_critical_failures=dashboard.latest_critical_failures,
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

    def _build_release_evidence(
        self,
        *,
        provider_production_ready: bool,
        capability_production_ready: bool,
        quota_status: str,
        critical_failures: list[OpsReadinessCriticalFailure],
        generated_at: datetime,
        agent_health_status: str = "healthy",
    ) -> OpsReleaseEvidence:
        manifest = self._read_release_manifest()

        def pick(key: str, env_name: str) -> object | None:
            value = manifest.get(key)
            return value if value is not None else os.getenv(env_name)

        environment = self._safe_label(pick("environment", "AMX_ENVIRONMENT_LABEL"))
        if environment is None:
            environment = self._safe_label(os.getenv("ENVIRONMENT"))
        deployed_ref = self._safe_label(pick("deployed_ref", "AMX_DEPLOYED_REF"))
        if deployed_ref is None:
            deployed_ref = self._safe_label(os.getenv("DEPLOYED_REF"))
        deployed_sha = self._safe_sha(pick("deployed_sha", "AMX_DEPLOYED_SHA"))
        if deployed_sha is None:
            deployed_sha = self._safe_sha(os.getenv("DEPLOYED_SHA") or os.getenv("GIT_COMMIT"))
        expected_sha = self._safe_sha(pick("expected_sha", "AMX_EXPECTED_SHA"))
        if expected_sha is None:
            expected_sha = self._safe_sha(os.getenv("EXPECTED_SHA"))
        release_tag = self._safe_label(pick("release_tag", "AMX_RELEASE_TAG"))
        if release_tag is None and deployed_ref and self._TAG_PATTERN.fullmatch(deployed_ref):
            release_tag = deployed_ref
        candidate_url = self._safe_run_url(
            pick("candidate_verification_run_url", "AMX_CANDIDATE_VERIFICATION_RUN_URL")
        )
        deployment_url = self._safe_run_url(
            pick("production_deployment_run_url", "AMX_PRODUCTION_DEPLOYMENT_RUN_URL")
        )
        smoke_url = self._safe_run_url(
            pick("authenticated_smoke_run_url", "AMX_LAST_AUTHENTICATED_SMOKE_RUN_URL")
        )
        smoke_status = self._safe_status(
            pick("smoke_status", "AMX_LAST_AUTHENTICATED_SMOKE_STATUS")
        )
        provenance_status = self._safe_status(
            pick("provenance_status", "AMX_DEPLOYMENT_PROVENANCE_STATUS")
        )
        gitnexus_status = self._safe_status(
            pick("gitnexus_status", "AMX_GITNEXUS_REFRESH_STATUS")
        )
        indexed_sha = self._safe_sha(
            pick("gitnexus_indexed_sha", "AMX_GITNEXUS_INDEXED_SHA")
        )
        sha_matches = (
            deployed_sha == expected_sha
            if deployed_sha is not None and expected_sha is not None
            else None
        )
        recorded_values = (
            deployed_ref,
            deployed_sha,
            expected_sha,
            release_tag,
            candidate_url,
            deployment_url,
            smoke_url,
            None if smoke_status == "not_recorded" else smoke_status,
            None if provenance_status == "not_recorded" else provenance_status,
            None if gitnexus_status == "not_recorded" else gitnexus_status,
            indexed_sha,
        )
        source = "sanitized_manifest" if manifest else "runtime_environment"
        if not any(recorded_values):
            return OpsReleaseEvidence(
                status="not_recorded",
                environment=environment,
                source="not_recorded",
                smoke_status="not_recorded",
                provenance_status="not_recorded",
                gitnexus_status="not_recorded",
                latest_evidence_export_at=generated_at,
            )

        blockers: list[OpsReleaseEvidenceBlocker] = []

        def add(code: str, severity: str, summary: str) -> None:
            blockers.append(OpsReleaseEvidenceBlocker(code=code, severity=severity, summary=summary))

        if sha_matches is False:
            add("sha_mismatch", "critical", "Runtime SHA does not match the approved release SHA.")
        if smoke_status in {"failed", "blocked"}:
            add("authenticated_smoke_failed", "critical", "Authenticated runtime smoke did not pass.")
        if provenance_status in {"failed", "blocked"}:
            add("provenance_failed", "critical", "Deployment provenance verification did not pass.")
        if gitnexus_status in {"failed", "blocked"}:
            add("gitnexus_refresh_failed", "high", "GitNexus refresh did not pass.")
        if deployed_sha and indexed_sha and deployed_sha != indexed_sha:
            add("gitnexus_sha_mismatch", "high", "GitNexus indexed SHA does not match the runtime SHA.")
        if not provider_production_ready:
            add("provider_not_ready", "high", "Provider readiness is not production-ready.")
        if not capability_production_ready:
            add("capability_not_ready", "high", "Capability readiness is not production-ready.")
        if quota_status == "blocked":
            add("quota_blocked", "high", "Runtime quota is exhausted or blocked.")
        if critical_failures:
            add("critical_runtime_failure", "high", "Critical runtime failures require review.")

        required = {
            "environment": environment,
            "deployed_ref": deployed_ref,
            "deployed_sha": deployed_sha,
            "expected_sha": expected_sha,
            "release_tag": release_tag,
            "candidate_verification_run_url": candidate_url,
            "production_deployment_run_url": deployment_url,
            "authenticated_smoke_run_url": smoke_url,
            "gitnexus_indexed_sha": indexed_sha,
        }
        for key, value in required.items():
            if value is None:
                add(f"{key}_not_recorded", "medium", f"{key.replace('_', ' ').capitalize()} is not recorded.")
        for key, value in {
            "authenticated_smoke": smoke_status,
            "provenance": provenance_status,
            "gitnexus": gitnexus_status,
        }.items():
            if value != "passed":
                add(f"{key}_not_verified", "medium", f"{key.replace('_', ' ').capitalize()} is not verified.")
        if quota_status == "attention":
            add("quota_attention", "medium", "Runtime quota requires attention.")
        elif quota_status not in {"healthy", "passed", "ready"} and quota_status != "blocked":
            add("quota_not_verified", "medium", "Runtime quota evidence is not verified.")
        if agent_health_status == "attention":
            add("agent_health_attention", "medium", "Recent agent workflow failures require attention.")
        elif agent_health_status not in {"healthy", "passed", "ready"}:
            add("agent_health_not_verified", "medium", "Agent workflow health is not verified.")

        if any(blocker.severity in {"critical", "high"} for blocker in blockers):
            status = "blocked"
        elif blockers:
            status = "attention"
        else:
            status = "ready"

        return OpsReleaseEvidence(
            status=status,
            environment=environment,
            source=source,
            deployed_ref=deployed_ref,
            deployed_sha=deployed_sha,
            expected_sha=expected_sha,
            sha_matches=sha_matches,
            release_tag=release_tag,
            candidate_verification_run_url=candidate_url,
            production_deployment_run_url=deployment_url,
            authenticated_smoke_run_url=smoke_url,
            smoke_status=smoke_status,
            provenance_status=provenance_status,
            gitnexus_status=gitnexus_status,
            gitnexus_indexed_sha=indexed_sha,
            latest_evidence_export_at=generated_at,
            blockers=blockers,
        )

    def _read_release_manifest(self) -> dict[str, object]:
        manifest_file = os.getenv("AMX_RELEASE_EVIDENCE_FILE")
        if not manifest_file:
            return {}
        path = Path(manifest_file)
        if path.name.lower().startswith(".env"):
            return {}
        try:
            if not path.is_file() or path.stat().st_size > self._MAX_MANIFEST_BYTES:
                return {}
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {key: payload[key] for key in self._MANIFEST_KEYS if key in payload}

    @classmethod
    def _safe_sha(cls, value: object | None) -> str | None:
        if not isinstance(value, str) or not cls._SHA_PATTERN.fullmatch(value.strip()):
            return None
        return value.strip().lower()

    @classmethod
    def _safe_label(cls, value: object | None) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if (
            not cls._SAFE_LABEL_PATTERN.fullmatch(normalized)
            or normalized.startswith("/")
            or ".." in normalized
            or "//" in normalized
        ):
            return None
        return normalized

    @classmethod
    def _safe_status(cls, value: object | None) -> str:
        if not isinstance(value, str):
            return "not_recorded"
        status = value.strip().lower()
        return status if status in cls._STATUS_VALUES else "not_recorded"

    @classmethod
    def _safe_run_url(cls, value: object | None) -> str | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = urlsplit(value.strip())
            port = parsed.port
        except ValueError:
            return None
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
            or not cls._RUN_PATH_PATTERN.fullmatch(parsed.path)
        ):
            return None
        return value.strip()

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
                    summary="Operational metric failure recorded",
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
                    summary="Notification delivery failure recorded",
                    occurred_at=notification.created_at,
                    status=notification.status,
                    action_href="/notifications",
                )
            )

        return failures[:5]
