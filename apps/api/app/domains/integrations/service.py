"""Integration Domain Services

Business logic for third-party integrations, webhooks, and outbox events.
"""

import asyncio
import hashlib
import hmac
import inspect
import json
import logfire
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.integrations.models import (
    IntegrationProvider,
    WebhookSubscription,
    IntegrationInboundEvent,
    WebhookDeliveryEvent,
    OutboxEvent,
    OutboxEventStatus,
    ProviderType,
    IntegrationProjectBinding,
    IntegrationSyncRun,
    IntegrationSyncedAsset,
)
from app.domains.integrations.schemas import (
    IntegrationProviderCreate,
    IntegrationProviderUpdate,
    IntegrationOperationsEvidence,
    IntegrationOperationsIncident,
    IntegrationOperationsIncidentQueue,
    IntegrationOperationsSummary,
    IntegrationProductionCommandCenter,
    IntegrationProductionPriorityAction,
    IntegrationProductionReleaseGate,
    IntegrationProductionRiskItem,
    WebhookSubscriptionCreate,
    OutboxEventCreate,
)


# Exponential backoff delays for queued webhook retry delivery.
WEBHOOK_DELAYS = [5, 30, 120]
MAX_DELIVERY_ATTEMPTS = 3


async def enqueue_webhook_retry_job(delivery_id: UUID, *, defer_by: int) -> None:
    """Enqueue one failed webhook delivery for background retry."""
    from arq import create_pool
    from app.workers.redis_config import arq_redis_settings

    redis = await create_pool(arq_redis_settings())
    try:
        await redis.enqueue_job(
            "retry_webhook_delivery",
            str(delivery_id),
            _defer_by=defer_by,
        )
    finally:
        close = getattr(redis, "aclose", None) or getattr(redis, "close", None)
        if close is not None:
            close_result = close()
            if inspect.isawaitable(close_result):
                await close_result


class IntegrationService:
    """Service for third-party integration management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_integration(
        self,
        tenant_id: UUID,
        provider_type: str,
        name: str,
        config: dict[str, Any],
    ) -> IntegrationProvider:
        """Create a new integration provider.

        Args:
            tenant_id: Tenant UUID
            provider_type: Provider type (zentao/jira/confluence/...)
            name: Integration name
            config: Configuration dictionary

        Returns:
            Created IntegrationProvider
        """
        integration = IntegrationProvider(
            tenant_id=tenant_id,
            provider_type=provider_type,
            name=name,
            config_json=config,
            is_enabled=True,
        )
        self.db.add(integration)
        await self.db.flush()
        await self.db.refresh(integration)
        return integration

    async def get_integration(
        self,
        integration_id: UUID,
        tenant_id: UUID | None = None,
    ) -> IntegrationProvider | None:
        """Get integration by ID with optional tenant filter.

        Args:
            integration_id: Integration UUID
            tenant_id: Optional tenant filter

        Returns:
            IntegrationProvider if found, None otherwise
        """
        query = select(IntegrationProvider).where(
            IntegrationProvider.id == integration_id,
            IntegrationProvider.deleted_at.is_(None),
        )
        if tenant_id is not None:
            query = query.where(IntegrationProvider.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_integrations(
        self,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[IntegrationProvider], int]:
        """List integrations for a tenant.

        Args:
            tenant_id: Tenant UUID
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of IntegrationProviders, total count)
        """
        # Count total
        count_result = await self.db.execute(
            select(func.count(IntegrationProvider.id)).where(
                IntegrationProvider.tenant_id == tenant_id,
                IntegrationProvider.deleted_at.is_(None),
            )
        )
        total = count_result.scalar()

        # Get paginated results
        result = await self.db.execute(
            select(IntegrationProvider)
            .where(
                IntegrationProvider.tenant_id == tenant_id,
                IntegrationProvider.deleted_at.is_(None),
            )
            .offset(skip)
            .limit(limit)
            .order_by(IntegrationProvider.created_at.desc())
        )
        integrations = list(result.scalars().all())

        return integrations, total

    async def update_integration(
        self,
        integration_id: UUID,
        tenant_id: UUID | None,
        updates: IntegrationProviderUpdate,
    ) -> IntegrationProvider | None:
        """Update an integration.

        Args:
            integration_id: Integration UUID
            tenant_id: Optional tenant filter
            updates: Update data

        Returns:
            Updated IntegrationProvider if found, None otherwise
        """
        integration = await self.get_integration(integration_id, tenant_id)
        if not integration:
            return None

        if updates.name is not None:
            integration.name = updates.name
        if updates.config_json is not None:
            integration.config_json = updates.config_json
        if updates.is_enabled is not None:
            integration.is_enabled = updates.is_enabled

        await self.db.flush()
        await self.db.refresh(integration)
        return integration

    async def delete_integration(
        self,
        integration_id: UUID,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Soft delete an integration.

        Args:
            integration_id: Integration UUID
            tenant_id: Optional tenant filter

        Returns:
            True if deleted, False if not found
        """
        integration = await self.get_integration(integration_id, tenant_id)
        if not integration:
            return False

        integration.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    async def test_connection(
        self,
        integration_id: UUID,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Test if an integration is properly configured.

        Args:
            integration_id: Integration UUID
            tenant_id: Optional tenant filter

        Returns:
            Dict with status and message
        """
        integration = await self.get_integration(integration_id, tenant_id)
        if not integration:
            return {
                "status": "not_found",
                "message": "Integration not found",
            }

        config = integration.config_json or {}

        if not integration.is_enabled:
            return {
                "status": "disabled",
                "message": "Integration is disabled",
                "details": {"provider_type": integration.provider_type},
            }

        required_fields = ["base_url", "api_key"]
        missing_fields = [field for field in required_fields if not config.get(field)]

        if missing_fields:
            return {
                "status": "unconfigured",
                "message": f"Integration not configured. Missing fields: {', '.join(missing_fields)}",
            }

        endpoint = self._build_endpoint(config, path_key="health_path", fallback_path="/health")
        method = str(config.get("health_method") or config.get("test_method") or "GET").upper()
        checked_at = datetime.now(timezone.utc)

        try:
            response = await self._call_provider(
                endpoint=endpoint,
                method=method,
                config=config,
            )
        except Exception as exc:
            return {
                "status": "unreachable",
                "message": f"Connection failed: {exc}",
                "details": {
                    "provider_type": integration.provider_type,
                    "endpoint": endpoint,
                    "checked_at": checked_at.isoformat(),
                },
            }

        status_code = int(response.status_code)
        details = {
            "provider_type": integration.provider_type,
            "endpoint": endpoint,
            "status_code": status_code,
            "checked_at": checked_at.isoformat(),
            "response_preview": self._safe_response_preview(response),
        }
        if 200 <= status_code < 400:
            return {
                "status": "connected",
                "message": "Connection successful",
                "details": details,
            }
        if status_code in {401, 403}:
            return {
                "status": "authentication_failed",
                "message": f"Connection rejected by provider: HTTP {status_code}",
                "details": details,
            }
        return {
            "status": "unavailable",
            "message": f"Provider returned HTTP {status_code}",
            "details": details,
        }

    async def sync_integration(
        self,
        integration_id: UUID,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Trigger a sync for an integration.

        Args:
            integration_id: Integration UUID
            tenant_id: Optional tenant filter

        Returns:
            Dict with sync result
        """
        integration = await self.get_integration(integration_id, tenant_id)
        if not integration:
            return {
                "success": False,
                "message": "Integration not found",
            }

        config = integration.config_json or {}

        if not config.get("base_url") or not config.get("api_key"):
            return {
                "success": False,
                "status": "unconfigured",
                "message": "Integration not configured",
            }

        connection = await self.test_connection(integration_id, tenant_id)
        if connection.get("status") != "connected":
            return {
                "success": False,
                "status": connection.get("status", "connection_failed"),
                "message": connection.get("message", "Connection test failed"),
                "details": connection.get("details"),
            }

        sync_path = config.get("sync_path")
        sync_method = str(config.get("sync_method") or "GET").upper()
        endpoint = self._build_endpoint(config, path_key="sync_path", fallback_path="/health")
        status_code: int | None = None
        external_response: Any = None

        if sync_path:
            try:
                response = await self._call_provider(
                    endpoint=endpoint,
                    method=sync_method,
                    config=config,
                    json_payload=config.get("sync_payload") or {"integration_id": str(integration.id)},
                )
                status_code = int(response.status_code)
                external_response = self._safe_response_body(response)
                if status_code >= 400:
                    return {
                        "success": False,
                        "status": "sync_failed",
                        "message": f"Provider sync endpoint returned HTTP {status_code}",
                        "details": {"endpoint": endpoint, "status_code": status_code},
                    }
            except Exception as exc:
                return {
                    "success": False,
                    "status": "sync_failed",
                    "message": f"Provider sync failed: {exc}",
                    "details": {"endpoint": endpoint},
                }
        else:
            endpoint = connection.get("details", {}).get("endpoint", endpoint)
            status_code = connection.get("details", {}).get("status_code")
            external_response = connection.get("details", {}).get("response_preview")

        synced_at = datetime.now(timezone.utc)
        integration.last_sync_at = synced_at
        self.db.add(
            IntegrationInboundEvent(
                tenant_id=integration.tenant_id,
                integration_provider_id=integration.id,
                event_type="integration.sync.completed",
                payload={
                    "provider_type": integration.provider_type,
                    "endpoint": endpoint,
                    "method": sync_method if sync_path else "CONNECTIVITY_SNAPSHOT",
                    "status_code": status_code,
                    "external_response": external_response,
                    "connection": connection,
                    "synced_at": synced_at.isoformat(),
                },
                processed=True,
                processed_at=synced_at,
            )
        )
        await self.db.flush()

        return {
            "success": True,
            "status": "synced",
            "message": "Integration sync completed",
            "last_sync_at": integration.last_sync_at.isoformat(),
            "details": {
                "endpoint": endpoint,
                "status_code": status_code,
                "event_type": "integration.sync.completed",
            },
        }

    async def build_operations_summary(self, tenant_id: UUID) -> IntegrationOperationsSummary:
        """Build production operations evidence for integrations and webhooks."""
        integrations = (
            await self.db.execute(
                select(IntegrationProvider).where(
                    IntegrationProvider.tenant_id == tenant_id,
                    IntegrationProvider.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        webhooks = (
            await self.db.execute(
                select(WebhookSubscription).where(
                    WebhookSubscription.tenant_id == tenant_id,
                    WebhookSubscription.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        deliveries = (
            await self.db.execute(
                select(WebhookDeliveryEvent).where(
                    WebhookDeliveryEvent.tenant_id == tenant_id,
                    WebhookDeliveryEvent.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        outbox_events = (
            await self.db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.tenant_id == tenant_id,
                    OutboxEvent.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        project_bindings = (
            await self.db.execute(
                select(IntegrationProjectBinding).where(
                    IntegrationProjectBinding.tenant_id == tenant_id,
                    IntegrationProjectBinding.deleted_at.is_(None),
                    IntegrationProjectBinding.is_enabled.is_(True),
                )
            )
        ).scalars().all()
        completed_project_syncs = (
            await self.db.execute(
                select(IntegrationSyncRun).where(
                    IntegrationSyncRun.tenant_id == tenant_id,
                    IntegrationSyncRun.status == "completed",
                )
            )
        ).scalars().all()
        synced_assets = (
            await self.db.execute(
                select(IntegrationSyncedAsset).where(
                    IntegrationSyncedAsset.tenant_id == tenant_id,
                )
            )
        ).scalars().all()

        enabled = [item for item in integrations if item.is_enabled]
        configured = [
            item for item in enabled
            if self._integration_has_endpoint(item.config_json or {}) and self._integration_has_auth(item.config_json or {})
        ]
        synced = [item for item in configured if item.last_sync_at is not None]
        active_webhooks = [item for item in webhooks if item.is_active]
        successful_deliveries = [
            item for item in deliveries
            if item.response_status is not None and 200 <= int(item.response_status) < 400 and not item.error_message
        ]
        failed_deliveries = [
            item for item in deliveries
            if item.error_message or (item.response_status is not None and int(item.response_status) >= 400)
        ]
        pending_outbox = [
            item for item in outbox_events
            if not item.published or item.status == OutboxEventStatus.PENDING.value
        ]
        failed_outbox = [item for item in outbox_events if item.status == OutboxEventStatus.FAILED.value]

        evidence = IntegrationOperationsEvidence(
            integration_count=len(integrations),
            enabled_integration_count=len(enabled),
            configured_integration_count=len(configured),
            synced_integration_count=len(synced),
            webhook_count=len(webhooks),
            active_webhook_count=len(active_webhooks),
            successful_delivery_count=len(successful_deliveries),
            failed_delivery_count=len(failed_deliveries),
            pending_outbox_count=len(pending_outbox),
            failed_outbox_count=len(failed_outbox),
            project_binding_count=len(project_bindings),
            completed_project_sync_count=len(completed_project_syncs),
            synced_asset_count=len(synced_assets),
        )

        blockers: list[str] = []
        recommended_actions: list[str] = []
        if not integrations:
            blockers.append("缺少外部集成配置。")
            recommended_actions.append("在系统设置中创建 Jira、Confluence、禅道或自定义集成。")
        if integrations and not configured:
            blockers.append("没有同时具备 endpoint 和认证字段的集成配置。")
            recommended_actions.append("补齐 base_url 与 api_key/service token 后运行连接测试。")
        if configured and not synced:
            blockers.append("缺少成功同步证据。")
            recommended_actions.append("对已配置集成执行连接测试和同步。")
        if configured and not project_bindings:
            blockers.append("外部集成尚未绑定项目，无法形成业务知识资产。")
            recommended_actions.append("在项目同步中创建绑定并预览外部内容。")
        if project_bindings and not completed_project_syncs:
            blockers.append("项目绑定尚无成功同步运行证据。")
            recommended_actions.append("执行项目知识同步并处理失败项。")
        if completed_project_syncs and not synced_assets:
            blockers.append("同步运行尚未沉淀项目资料和知识资产。")
            recommended_actions.append("检查字段映射与外部响应内容后重新同步。")
        if failed_deliveries:
            blockers.append(f"Webhook 投递失败 {len(failed_deliveries)} 次，需要处理失败目标或重试。")
            recommended_actions.append("检查 Webhook 投递历史并重试失败事件。")
        if pending_outbox:
            blockers.append(f"Outbox 仍有 {len(pending_outbox)} 条待发布事件。")
            recommended_actions.append("发布或排查 Outbox 积压事件。")
        if failed_outbox:
            blockers.append(f"Outbox 有 {len(failed_outbox)} 条失败事件。")
            recommended_actions.append("修复失败原因后重新发布 Outbox 事件。")

        score = 0
        if integrations:
            score += 30
        if configured:
            score += 20
        if synced:
            score += 20
        if active_webhooks:
            score += 10
        if outbox_events:
            score += 10
        if not failed_deliveries:
            score += 10
        else:
            score -= 10
        if pending_outbox:
            score -= 8
        if failed_outbox:
            score -= 12
        score = max(0, min(100, score))

        status = "ready" if score >= 85 and not blockers else "degraded" if score >= 50 else "blocked"
        summary = (
            "外部集成、Webhook 和 Outbox 已具备生产投产证据。"
            if status == "ready"
            else "外部集成已配置，但仍存在需要处理的投产证据缺口。"
            if status == "degraded"
            else "外部集成缺少可证明生产可用的配置或运行证据。"
        )
        return IntegrationOperationsSummary(
            status=status,
            score=score,
            summary=summary,
            evidence=evidence,
            blockers=blockers,
            recommended_actions=recommended_actions,
        )

    async def build_production_command_center(self, tenant_id: UUID) -> IntegrationProductionCommandCenter:
        """Build a release gate over integration operations evidence."""
        operations_summary = await self.build_operations_summary(tenant_id)
        evidence = operations_summary.evidence
        summary = {
            "score": operations_summary.score,
            "integration_count": evidence.integration_count,
            "enabled_integration_count": evidence.enabled_integration_count,
            "configured_integration_count": evidence.configured_integration_count,
            "synced_integration_count": evidence.synced_integration_count,
            "active_webhook_count": evidence.active_webhook_count,
            "successful_delivery_count": evidence.successful_delivery_count,
            "failed_delivery_count": evidence.failed_delivery_count,
            "pending_outbox_count": evidence.pending_outbox_count,
            "failed_outbox_count": evidence.failed_outbox_count,
            "project_binding_count": evidence.project_binding_count,
            "completed_project_sync_count": evidence.completed_project_sync_count,
            "synced_asset_count": evidence.synced_asset_count,
            "blocker_count": len(operations_summary.blockers),
        }
        risk_items = self._integration_production_risks(summary)
        return IntegrationProductionCommandCenter(
            release_gate=self._integration_release_gate(operations_summary, risk_items),
            summary=summary,
            risk_items=risk_items,
            priority_actions=self._integration_priority_actions(summary, operations_summary),
            operations_summary=operations_summary,
        )

    async def build_incident_queue(
        self, tenant_id: UUID, limit: int = 50
    ) -> IntegrationOperationsIncidentQueue:
        """Build one actionable queue across sync, webhook, and outbox failures."""
        failed_syncs = list(
            (
                await self.db.scalars(
                    select(IntegrationSyncRun)
                    .where(
                        IntegrationSyncRun.tenant_id == tenant_id,
                        IntegrationSyncRun.status == "failed",
                    )
                    .order_by(IntegrationSyncRun.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        failed_deliveries = list(
            (
                await self.db.scalars(
                    select(WebhookDeliveryEvent)
                    .where(
                        WebhookDeliveryEvent.tenant_id == tenant_id,
                        WebhookDeliveryEvent.deleted_at.is_(None),
                        WebhookDeliveryEvent.delivered_at.is_(None),
                        (
                            WebhookDeliveryEvent.error_message.is_not(None)
                            | (WebhookDeliveryEvent.response_status >= 400)
                        ),
                    )
                    .order_by(WebhookDeliveryEvent.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        failed_outbox = list(
            (
                await self.db.scalars(
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.tenant_id == tenant_id,
                        OutboxEvent.deleted_at.is_(None),
                        OutboxEvent.status == OutboxEventStatus.FAILED.value,
                    )
                    .order_by(OutboxEvent.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        items = [
            IntegrationOperationsIncident(
                id=run.id,
                category="project_sync",
                severity="high",
                title="项目同步失败",
                detail=run.error_message or "项目绑定同步未完成",
                status=run.status,
                attempts=1,
                occurred_at=run.created_at,
                action_type="retry_sync",
                action_href=f"/integrations?retrySyncRun={run.id}",
            )
            for run in failed_syncs
        ]
        items.extend(
            IntegrationOperationsIncident(
                id=delivery.id,
                category="webhook",
                severity="critical" if delivery.attempts >= MAX_DELIVERY_ATTEMPTS else "high",
                title="Webhook 投递失败",
                detail=delivery.error_message or f"目标返回 HTTP {delivery.response_status}",
                status="failed",
                attempts=delivery.attempts,
                occurred_at=delivery.created_at,
                action_type="retry_webhook",
                action_href=f"/integrations?retryWebhook={delivery.id}",
            )
            for delivery in failed_deliveries
        )
        items.extend(
            IntegrationOperationsIncident(
                id=event.id,
                category="outbox",
                severity="critical",
                title="Outbox 事件失败",
                detail=event.last_error or f"{event.event_type} 发布失败",
                status=event.status,
                attempts=event.attempts,
                occurred_at=event.created_at,
                action_type="retry_outbox",
                action_href=f"/integrations?retryOutbox={event.id}",
            )
            for event in failed_outbox
        )
        items.sort(key=lambda item: item.occurred_at, reverse=True)
        items = items[:limit]
        return IntegrationOperationsIncidentQueue(
            total=len(items),
            critical_count=sum(item.severity == "critical" for item in items),
            retryable_count=sum(item.action_type.startswith("retry_") for item in items),
            items=items,
        )

    def _integration_production_risks(self, summary: dict[str, int]) -> list[IntegrationProductionRiskItem]:
        risks: list[IntegrationProductionRiskItem] = []
        if summary["integration_count"] == 0:
            risks.append(IntegrationProductionRiskItem(
                code="missing_integrations",
                severity="critical",
                title="缺少外部集成配置",
                detail="没有外部系统接入，项目资料、知识同步和交付证据无法形成闭环。",
                count=1,
                href="/integrations",
            ))
        if summary["integration_count"] and summary["configured_integration_count"] == 0:
            risks.append(IntegrationProductionRiskItem(
                code="unconfigured_integrations",
                severity="critical",
                title="集成缺少生产连接配置",
                detail="已创建集成但缺少 endpoint 或认证字段，不能证明真实外部系统可达。",
                count=summary["integration_count"],
                href="/integrations",
            ))
        if summary["configured_integration_count"] and summary["synced_integration_count"] == 0:
            risks.append(IntegrationProductionRiskItem(
                code="missing_sync_evidence",
                severity="high",
                title="缺少成功同步证据",
                detail="已配置集成尚未产生成功同步记录，不能进入生产联调验收。",
                count=summary["configured_integration_count"],
                href="/integrations",
            ))
        if summary["failed_delivery_count"]:
            risks.append(IntegrationProductionRiskItem(
                code="failed_webhook_deliveries",
                severity="high",
                title="Webhook 投递失败",
                detail="存在失败投递，需要重试或修复目标端后再进入发布。",
                count=summary["failed_delivery_count"],
                href="/integrations",
            ))
        if summary["pending_outbox_count"]:
            risks.append(IntegrationProductionRiskItem(
                code="pending_outbox",
                severity="high",
                title="Outbox 事件待发布",
                detail="仍有事件没有发布，外部系统可能没有收到最新业务状态。",
                count=summary["pending_outbox_count"],
                href="/integrations",
            ))
        if summary["failed_outbox_count"]:
            risks.append(IntegrationProductionRiskItem(
                code="failed_outbox",
                severity="critical",
                title="Outbox 发布失败",
                detail="存在失败事件，需要修复失败原因并重新发布。",
                count=summary["failed_outbox_count"],
                href="/integrations",
            ))
        if summary["configured_integration_count"] and summary["project_binding_count"] == 0:
            risks.append(IntegrationProductionRiskItem(
                code="missing_project_bindings",
                severity="high",
                title="集成未绑定项目",
                detail="外部系统没有绑定到项目，无法沉淀项目资料和知识资产。",
                count=summary["configured_integration_count"],
                href="/integrations",
            ))
        if summary["project_binding_count"] and summary["completed_project_sync_count"] == 0:
            risks.append(IntegrationProductionRiskItem(
                code="missing_project_sync_runs",
                severity="medium",
                title="项目同步未完成",
                detail="已有项目绑定但没有成功同步运行，需要执行项目知识同步。",
                count=summary["project_binding_count"],
                href="/integrations",
            ))
        if summary["completed_project_sync_count"] and summary["synced_asset_count"] == 0:
            risks.append(IntegrationProductionRiskItem(
                code="missing_synced_assets",
                severity="medium",
                title="同步资产未沉淀",
                detail="同步运行没有生成资料或知识资产，需要检查字段映射和外部响应。",
                count=summary["completed_project_sync_count"],
                href="/integrations",
            ))
        return risks

    def _integration_release_gate(
        self,
        operations_summary: IntegrationOperationsSummary,
        risk_items: list[IntegrationProductionRiskItem],
    ) -> IntegrationProductionReleaseGate:
        blockers = [item.title for item in risk_items if item.severity in {"critical", "high"}]
        warnings = [item.title for item in risk_items if item.severity == "medium"]
        if blockers or operations_summary.status == "blocked":
            return IntegrationProductionReleaseGate(
                status="blocked",
                label="联调阻断",
                summary="外部集成仍存在生产联调阻断，发布前必须完成处置。",
                blockers=blockers or operations_summary.blockers[:5],
                warnings=warnings,
            )
        if warnings or operations_summary.status == "degraded":
            return IntegrationProductionReleaseGate(
                status="attention",
                label="需要复核",
                summary="外部集成具备部分运行证据，但仍需发布前确认剩余风险。",
                blockers=[],
                warnings=warnings or operations_summary.blockers[:5],
            )
        return IntegrationProductionReleaseGate(
            status="passed",
            label="联调可验收",
            summary="集成连接、同步、Webhook 与 Outbox 证据满足发布验收要求。",
            blockers=[],
            warnings=[],
        )

    def _integration_priority_actions(
        self,
        summary: dict[str, int],
        operations_summary: IntegrationOperationsSummary,
    ) -> list[IntegrationProductionPriorityAction]:
        actions: list[IntegrationProductionPriorityAction] = []
        if summary["integration_count"] == 0 or summary["configured_integration_count"] == 0:
            actions.append(IntegrationProductionPriorityAction(
                code="configure_integrations",
                title="补齐生产集成配置",
                description="创建真实外部系统集成，并配置 endpoint 与认证字段。",
                href="/integrations",
                priority="critical",
            ))
        if summary["synced_integration_count"] == 0 and summary["configured_integration_count"]:
            actions.append(IntegrationProductionPriorityAction(
                code="run_sync",
                title="执行连接测试与同步",
                description="对已配置集成执行测试和同步，生成生产联调证据。",
                href="/integrations",
                priority="high",
            ))
        if summary["failed_delivery_count"] or summary["pending_outbox_count"] or summary["failed_outbox_count"]:
            actions.append(IntegrationProductionPriorityAction(
                code="clear_events",
                title="清理 Webhook 与 Outbox 阻断",
                description="重试失败投递，发布积压事件，并保留处理结果。",
                href="/integrations",
                priority="high",
            ))
        if summary["project_binding_count"] == 0 and summary["configured_integration_count"]:
            actions.append(IntegrationProductionPriorityAction(
                code="bind_projects",
                title="绑定项目并同步资产",
                description="将外部集成绑定到项目，预览并执行项目资料同步。",
                href="/integrations",
                priority="high",
            ))
        if not actions:
            actions.extend(
                IntegrationProductionPriorityAction(
                    code=f"recommended_{index}",
                    title=action,
                    description=operations_summary.summary,
                    href="/integrations",
                    priority="medium",
                )
                for index, action in enumerate(operations_summary.recommended_actions[:3], start=1)
            )
        if not actions:
            actions.append(IntegrationProductionPriorityAction(
                code="preserve_integration_evidence",
                title="保留联调验收证据",
                description="保留连接测试、同步运行、Webhook 投递和 Outbox 发布记录。",
                href="/integrations",
                priority="medium",
            ))
        return actions

    def _build_endpoint(self, config: dict[str, Any], *, path_key: str, fallback_path: str) -> str:
        base_url = str(config.get("base_url") or "").strip()
        path = str(config.get(path_key) or config.get("test_path") or fallback_path).strip()
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))

    def _integration_has_endpoint(self, config: dict[str, Any]) -> bool:
        return bool(
            config.get("base_url")
            or config.get("endpoint")
            or config.get("url")
            or config.get("server_url")
            or config.get("api_url")
            or config.get("runtime_ref")
            or config.get("managed_runtime_ref")
        )

    def _integration_has_auth(self, config: dict[str, Any]) -> bool:
        return bool(
            config.get("api_key")
            or config.get("token")
            or config.get("access_token")
            or config.get("secret")
            or config.get("service_key")
            or config.get("credential_ref")
        )

    def _build_headers(self, config: dict[str, Any]) -> dict[str, str]:
        headers = {
            str(key): str(value)
            for key, value in (config.get("headers") or {}).items()
            if value is not None
        }
        api_key = str(config.get("api_key") or "")
        auth_header = str(config.get("auth_header") or "Authorization")
        auth_scheme = str(config.get("auth_scheme") or "Bearer")
        if api_key:
            headers[auth_header] = api_key if auth_scheme.lower() == "raw" else f"{auth_scheme} {api_key}"
        headers.setdefault("Accept", "application/json")
        return headers

    async def _call_provider(
        self,
        *,
        endpoint: str,
        method: str,
        config: dict[str, Any],
        json_payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        timeout = float(config.get("timeout_seconds") or 15)
        headers = self._build_headers(config)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            if method == "POST":
                return await client.post(endpoint, headers=headers, json=json_payload)
            if method == "PUT":
                return await client.put(endpoint, headers=headers, json=json_payload)
            return await client.get(endpoint, headers=headers)

    def _safe_response_body(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except Exception:
            return (response.text or "")[:500]

    def _safe_response_preview(self, response: httpx.Response) -> Any:
        body = self._safe_response_body(response)
        if isinstance(body, dict):
            return {
                key: value
                for key, value in body.items()
                if "token" not in str(key).lower() and "secret" not in str(key).lower() and "key" not in str(key).lower()
            }
        return body


class WebhookService:
    """Service for webhook subscription management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def retry_delivery(
        self, delivery_id: UUID, tenant_id: UUID
    ) -> WebhookDeliveryEvent:
        """Retry one failed delivery in place so the incident can close."""
        delivery = await self.db.scalar(
            select(WebhookDeliveryEvent).where(
                WebhookDeliveryEvent.id == delivery_id,
                WebhookDeliveryEvent.tenant_id == tenant_id,
                WebhookDeliveryEvent.deleted_at.is_(None),
            )
        )
        if not delivery:
            raise ValueError("Webhook delivery not found")
        subscription = await self.db.scalar(
            select(WebhookSubscription).where(
                WebhookSubscription.id == delivery.webhook_subscription_id,
                WebhookSubscription.tenant_id == tenant_id,
                WebhookSubscription.deleted_at.is_(None),
            )
        )
        if not subscription:
            raise ValueError("Webhook subscription not found")
        delivery.attempts += 1
        delivered = await self._attempt_delivery(subscription, delivery.request_body, delivery)
        delivery.delivered_at = datetime.now(timezone.utc) if delivered else None
        await self.db.flush()
        await self.db.refresh(delivery)
        return delivery

    async def create_subscription(
        self,
        tenant_id: UUID,
        integration_id: UUID,
        url: str,
        events: list[str],
        secret: str | None = None,
    ) -> WebhookSubscription:
        """Create a webhook subscription.

        Args:
            tenant_id: Tenant UUID
            integration_id: Integration provider UUID
            url: Callback URL
            events: List of event types to receive
            secret: Optional webhook secret for signature verification

        Returns:
            Created WebhookSubscription
        """
        subscription = WebhookSubscription(
            tenant_id=tenant_id,
            integration_provider_id=integration_id,
            url=url,
            events=events,
            secret=secret,
            is_active=True,
        )
        self.db.add(subscription)
        await self.db.flush()
        await self.db.refresh(subscription)
        return subscription

    async def get_subscription(
        self,
        subscription_id: UUID,
        tenant_id: UUID | None = None,
    ) -> WebhookSubscription | None:
        """Get webhook subscription by ID.

        Args:
            subscription_id: Subscription UUID
            tenant_id: Optional tenant filter

        Returns:
            WebhookSubscription if found, None otherwise
        """
        query = select(WebhookSubscription).where(
            WebhookSubscription.id == subscription_id,
            WebhookSubscription.deleted_at.is_(None),
        )
        if tenant_id is not None:
            query = query.where(WebhookSubscription.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_subscriptions(
        self,
        tenant_id: UUID,
        integration_id: UUID | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[WebhookSubscription], int]:
        """List webhook subscriptions.

        Args:
            tenant_id: Tenant UUID
            integration_id: Optional integration filter
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of WebhookSubscriptions, total count)
        """
        conditions = [
            WebhookSubscription.tenant_id == tenant_id,
            WebhookSubscription.deleted_at.is_(None),
        ]
        if integration_id:
            conditions.append(WebhookSubscription.integration_provider_id == integration_id)

        # Count total
        count_result = await self.db.execute(
            select(func.count(WebhookSubscription.id)).where(*conditions)
        )
        total = count_result.scalar()

        # Get paginated results
        result = await self.db.execute(
            select(WebhookSubscription)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(WebhookSubscription.created_at.desc())
        )
        subscriptions = list(result.scalars().all())

        return subscriptions, total

    async def delete_subscription(
        self,
        subscription_id: UUID,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Delete a webhook subscription.

        Args:
            subscription_id: Subscription UUID
            tenant_id: Optional tenant filter

        Returns:
            True if deleted, False if not found
        """
        subscription = await self.get_subscription(subscription_id, tenant_id)
        if not subscription:
            return False

        subscription.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    async def handle_inbound_webhook(
        self,
        tenant_id: UUID,
        integration_id: UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> IntegrationInboundEvent:
        """Process an incoming webhook event.

        Args:
            tenant_id: Tenant UUID
            integration_id: Integration provider UUID
            event_type: Type of event
            payload: Event payload

        Returns:
            Created IntegrationInboundEvent
        """
        event = IntegrationInboundEvent(
            tenant_id=tenant_id,
            integration_provider_id=integration_id,
            event_type=event_type,
            payload=payload,
            processed=False,
        )
        self.db.add(event)
        await self.db.flush()
        await self.db.refresh(event)
        return event

    async def mark_event_processed(
        self,
        event_id: UUID,
    ) -> bool:
        """Mark an inbound event as processed.

        Args:
            event_id: Event UUID

        Returns:
            True if updated, False otherwise
        """
        result = await self.db.execute(
            select(IntegrationInboundEvent).where(IntegrationInboundEvent.id == event_id)
        )
        event = result.scalar_one_or_none()
        if not event:
            return False

        event.processed = True
        event.processed_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    async def deliver_webhook(
        self,
        subscription_id: UUID,
        event_payload: dict[str, Any],
    ) -> WebhookDeliveryEvent:
        """Deliver a webhook to a subscription URL with retry logic.

        Args:
            subscription_id: Subscription UUID
            event_payload: Event payload to deliver

        Returns:
            WebhookDeliveryEvent with delivery result
        """
        result = await self.db.execute(
            select(WebhookSubscription).where(WebhookSubscription.id == subscription_id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            raise ValueError(f"Subscription not found: {subscription_id}")

        delivery = WebhookDeliveryEvent(
            tenant_id=subscription.tenant_id,
            webhook_subscription_id=subscription_id,
            event_id=event_payload.get("event_id") or str(uuid4()),
            url=subscription.url,
            request_headers={"Content-Type": "application/json"},
            request_body=event_payload,
            attempts=1,
        )
        self.db.add(delivery)
        await self.db.flush()

        # Attempt delivery
        success = await self._attempt_delivery(subscription, event_payload, delivery)

        if success:
            delivery.response_status = 200
            delivery.delivered_at = datetime.now(timezone.utc)
        else:
            # Schedule retry
            await self._schedule_retry(subscription, event_payload, delivery)

        await self.db.flush()
        await self.db.refresh(delivery)
        return delivery

    async def _attempt_delivery(
        self,
        subscription: WebhookSubscription,
        payload: dict[str, Any],
        delivery: WebhookDeliveryEvent,
    ) -> bool:
        """Attempt to deliver webhook with signature.

        Args:
            subscription: WebhookSubscription
            payload: Event payload
            delivery: WebhookDeliveryEvent to update

        Returns:
            True if delivery succeeded, False otherwise
        """
        # Create signature if secret is configured
        headers = {"Content-Type": "application/json"}
        if subscription.secret:
            body_json = json.dumps(payload, separators=(",", ":"))
            signature = hmac.new(
                subscription.secret.encode(),
                body_json.encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    subscription.url,
                    json=payload,
                    headers=headers,
                )

            delivery.response_status = response.status_code
            delivery.response_body = response.text[:5000] if response.text else None
            delivery.error_message = None

            return 200 <= response.status_code < 300

        except Exception as e:
            delivery.error_message = str(e)
            delivery.response_status = None
            return False

    async def _schedule_retry(
        self,
        subscription: WebhookSubscription,
        payload: dict[str, Any],
        delivery: WebhookDeliveryEvent,
    ) -> None:
        """Schedule a webhook retry with exponential backoff.

        Args:
            subscription: WebhookSubscription
            payload: Event payload
            delivery: WebhookDeliveryEvent to track retry
        """
        delay = WEBHOOK_DELAYS[min(delivery.attempts - 1, len(WEBHOOK_DELAYS) - 1)]
        try:
            await enqueue_webhook_retry_job(delivery.id, defer_by=delay)
        except Exception as exc:
            logfire.error(
                f"Failed to enqueue webhook retry: {delivery.id}",
                error=str(exc),
            )
            delivery.error_message = (
                f"{delivery.error_message}; retry scheduling failed: {exc}"
                if delivery.error_message
                else f"Retry scheduling failed: {exc}"
            )


class OutboxService:
    """Service for outbox event management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def retry_event(self, event_id: UUID, tenant_id: UUID) -> OutboxEvent:
        """Move one failed outbox event back to the publish queue."""
        event = await self.db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.id == event_id,
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.deleted_at.is_(None),
            )
        )
        if not event:
            raise ValueError("Outbox event not found")
        event.status = OutboxEventStatus.PENDING.value
        event.published = False
        event.published_at = None
        event.last_error = None
        await self.db.flush()
        await self.db.refresh(event)
        return event

    async def create_event(
        self,
        tenant_id: UUID,
        aggregate_type: str,
        aggregate_id: UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> OutboxEvent:
        """Create an outbox event.

        Args:
            tenant_id: Tenant UUID
            aggregate_type: Type of aggregate
            aggregate_id: ID of the aggregate
            event_type: Event type
            payload: Event payload

        Returns:
            Created OutboxEvent
        """
        event = OutboxEvent(
            tenant_id=tenant_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=payload,
            published=False,
        )
        self.db.add(event)
        await self.db.flush()
        await self.db.refresh(event)
        return event

    async def get_pending_events(
        self,
        tenant_id: UUID | None = None,
        limit: int = 100,
    ) -> list[OutboxEvent]:
        """Get pending (unpublished) outbox events.

        Args:
            tenant_id: Optional tenant filter
            limit: Maximum number of events to return

        Returns:
            List of pending OutboxEvents
        """
        conditions = [
            OutboxEvent.published == False,
            OutboxEvent.deleted_at.is_(None),
        ]
        if tenant_id is not None:
            conditions.append(OutboxEvent.tenant_id == tenant_id)

        result = await self.db.execute(
            select(OutboxEvent)
            .where(*conditions)
            .limit(limit)
            .order_by(OutboxEvent.created_at.asc())
        )
        return list(result.scalars().all())

    async def mark_published(
        self,
        event_id: UUID,
    ) -> bool:
        """Mark an outbox event as published.

        Args:
            event_id: Event UUID

        Returns:
            True if updated, False otherwise
        """
        result = await self.db.execute(
            select(OutboxEvent).where(OutboxEvent.id == event_id)
        )
        event = result.scalar_one_or_none()
        if not event:
            return False

        event.published = True
        event.published_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    def _provider_id_for_event(self, event: OutboxEvent) -> UUID | None:
        if event.aggregate_type in {"integration", "integration_provider"}:
            return event.aggregate_id

        payload = event.payload if isinstance(event.payload, dict) else {}
        raw_provider_id = payload.get("integration_provider_id") or payload.get("provider_id")
        if raw_provider_id is None:
            return None
        try:
            return raw_provider_id if isinstance(raw_provider_id, UUID) else UUID(str(raw_provider_id))
        except (TypeError, ValueError):
            return None

    def _subscription_accepts_event(self, subscription: WebhookSubscription, event_type: str) -> bool:
        events = subscription.events or []
        return not events or event_type in events

    async def _subscriptions_for_event(self, event: OutboxEvent) -> list[WebhookSubscription]:
        conditions = [
            WebhookSubscription.tenant_id == event.tenant_id,
            WebhookSubscription.deleted_at.is_(None),
            WebhookSubscription.is_active == True,
        ]
        provider_id = self._provider_id_for_event(event)
        if provider_id is not None:
            conditions.append(WebhookSubscription.integration_provider_id == provider_id)

        subscriptions_result = await self.db.execute(
            select(WebhookSubscription).where(*conditions)
        )
        return [
            subscription
            for subscription in subscriptions_result.scalars().all()
            if self._subscription_accepts_event(subscription, event.event_type)
        ]

    async def publish_pending_events(
        self,
        batch_size: int = 100,
    ) -> dict[str, Any]:
        """Publish pending outbox events.

        For each pending event, deliver to the appropriate webhook
        subscriptions registered for that integration.

        NOTE: Events are only marked as published AFTER successful delivery,
        not after enqueueing. This ensures no data loss if delivery fails.

        Args:
            batch_size: Maximum number of events to process

        Returns:
            Dict with publishing results
        """
        pending_events = await self.get_pending_events(limit=batch_size)

        published_count = 0
        failed_count = 0

        for event in pending_events:
            try:
                subscriptions = await self._subscriptions_for_event(event)

                # If no subscriptions, mark as published (nothing to deliver)
                if not subscriptions:
                    await self.mark_published(event.id)
                    published_count += 1
                    continue

                # Track delivery success
                all_delivered = True
                delivery_error = None

                # Deliver to all matching subscriptions
                for sub in subscriptions:
                    webhook_service = WebhookService(self.db)
                    delivery = await webhook_service.deliver_webhook(
                        subscription_id=sub.id,
                        event_payload={
                            "event_id": str(event.id),
                            "event_type": event.event_type,
                            "aggregate_type": event.aggregate_type,
                            "aggregate_id": str(event.aggregate_id),
                            "payload": event.payload,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    )

                    # Check if delivery was successful
                    if not delivery.delivered_at:
                        all_delivered = False
                        delivery_error = delivery.error_message

                # Only mark as published AFTER all deliveries confirmed
                # If any delivery failed, keep event as pending for retry
                if all_delivered:
                    await self.mark_published(event.id)
                    published_count += 1
                else:
                    # Log failure but don't mark as published
                    logfire.warning(
                        f"Outbox event delivery partially failed: {event.id}",
                        error=delivery_error,
                    )
                    failed_count += 1

            except Exception as e:
                logfire.error(f"Failed to publish outbox event: {event.id}", error=str(e))
                failed_count += 1

        return {
            "processed": len(pending_events),
            "published": published_count,
            "failed": failed_count,
        }
