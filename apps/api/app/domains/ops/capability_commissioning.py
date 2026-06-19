"""Core production commissioning service."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.domains.ops.capability_readiness import CapabilityReadinessService
from app.domains.ops.models import AlertRule, MetricEvent, NotificationEvent, QuotaUsage
from app.domains.ops.schemas import (
    CapabilityCommissioningAction,
    CapabilityCommissioningCheck,
    CapabilityCommissioningResponse,
    CapabilityCommissioningRunRequest,
    CapabilityReadinessResponse,
)
from app.domains.projects.models import SourceFile
from app.domains.providers.capability import is_live_configured
from app.domains.providers.models import Provider, ProviderStatus, ProviderType
from app.models.identity import Role, User


class CapabilityCommissioningService:
    """Verify whether core capabilities have enough production evidence."""

    CRITICAL_CHECKS = {
        "live_llm_provider",
        "knowledge_graph_evidence",
        "external_integration_connectivity",
        "external_integration_project_sync",
        "collaboration_execution_evidence",
        "notification_alert_handling_evidence",
        "export_validation",
        "team_permission_audit",
        "ops_observability_evidence",
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build(self, tenant_id: UUID | None) -> CapabilityCommissioningResponse:
        """Build the current production commissioning checklist without marking checks as run."""
        readiness = await CapabilityReadinessService(self.db).build(tenant_id)
        evidence = await self._collect_evidence(tenant_id)
        checks = self._build_checks(readiness, evidence)
        return self._response(
            tenant_id=tenant_id,
            readiness=readiness,
            checks=checks,
            executed=False,
        )

    async def run(
        self,
        tenant_id: UUID | None,
        request: CapabilityCommissioningRunRequest,
    ) -> CapabilityCommissioningResponse:
        """Run selected commissioning checks against current evidence."""
        readiness = await CapabilityReadinessService(self.db).build(tenant_id)
        evidence = await self._collect_evidence(tenant_id)
        checks = self._build_checks(readiness, evidence)
        selected = set(request.checks or [check.key for check in checks if check.can_run])

        for check in checks:
            if check.key not in selected:
                check.run_status = "skipped"
                continue
            check.run_status = "passed" if check.status == "passed" else "failed"
            check.run_result = {
                "status": check.status,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
                "blocker_count": len(check.blockers),
            }

        return self._response(
            tenant_id=tenant_id,
            readiness=readiness,
            checks=checks,
            executed=True,
        )

    async def _collect_evidence(self, tenant_id: UUID | None) -> dict[str, Any]:
        source_file_count = await self._count(SourceFile, tenant_id)
        knowledge_entry_count = await self._count(KnowledgeEntry, tenant_id)
        knowledge_link_count = await self._count(KnowledgeLink, tenant_id)
        configured_integrations = await self._configured_integrations(tenant_id)
        validated_integrations = [
            provider
            for provider in configured_integrations
            if self._integration_has_validation_evidence(provider)
        ]
        enabled_binding_count = await self._count(
            IntegrationProjectBinding,
            tenant_id,
            IntegrationProjectBinding.is_enabled.is_(True),
        )
        completed_sync_run_count = await self._count(
            IntegrationSyncRun,
            tenant_id,
            IntegrationSyncRun.status == "completed",
        )
        synced_asset_count = await self._count(IntegrationSyncedAsset, tenant_id)
        completed_export_count = await self._count(
            ExportJob,
            tenant_id,
            ExportJob.status == ExportStatus.COMPLETED.value,
        )
        exportable_document_count = await self._exportable_document_count(tenant_id)
        live_providers = await self._live_llm_providers(tenant_id)
        active_user_count = await self._count(User, tenant_id, User.is_active.is_(True))
        role_count = await self._count(Role, tenant_id)
        audit_log_count = await self._count(AuditLog, tenant_id)
        policy_count = await self._count(Policy, tenant_id)
        field_permission_count = await self._count(FieldPermission, tenant_id)
        metric_event_count = await self._count(MetricEvent, tenant_id)
        quota_usage_count = await self._count(QuotaUsage, tenant_id)
        active_alert_rule_count = await self._count(AlertRule, tenant_id, AlertRule.is_active.is_(True))
        active_work_statuses = [
            WorkItemStatus.OPEN.value,
            WorkItemStatus.IN_PROGRESS.value,
            WorkItemStatus.BLOCKED.value,
        ]
        work_item_count = await self._count(CollaborationWorkItem, tenant_id)
        done_work_item_count = await self._count(
            CollaborationWorkItem,
            tenant_id,
            CollaborationWorkItem.status == WorkItemStatus.DONE.value,
        )
        active_work_item_count = await self._count(
            CollaborationWorkItem,
            tenant_id,
            CollaborationWorkItem.status.in_(active_work_statuses),
        )
        blocked_work_item_count = await self._count(
            CollaborationWorkItem,
            tenant_id,
            CollaborationWorkItem.status == WorkItemStatus.BLOCKED.value,
        )
        overdue_work_item_count = await self._count(
            CollaborationWorkItem,
            tenant_id,
            CollaborationWorkItem.status.in_(active_work_statuses),
            CollaborationWorkItem.due_at.is_not(None),
            CollaborationWorkItem.due_at < datetime.now(timezone.utc),
        )
        preference_count = await self._count(NotificationPreference, tenant_id)
        unacknowledged_required_notification_count = await self._count(
            UserNotification,
            tenant_id,
            UserNotification.ack_required.is_(True),
            UserNotification.acknowledged_at.is_(None),
            UserNotification.archived_at.is_(None),
        )
        escalated_notification_count = await self._count(
            UserNotification,
            tenant_id,
            UserNotification.escalation_level > 0,
            UserNotification.acknowledged_at.is_(None),
            UserNotification.archived_at.is_(None),
        )
        notification_event_count = await self._count(NotificationEvent, tenant_id)
        sent_notification_event_count = await self._count(
            NotificationEvent,
            tenant_id,
            NotificationEvent.status == "sent",
        )
        failed_notification_event_count = await self._count(
            NotificationEvent,
            tenant_id,
            NotificationEvent.status == "failed",
        )

        return {
            "source_file_count": source_file_count,
            "knowledge_entry_count": knowledge_entry_count,
            "knowledge_link_count": knowledge_link_count,
            "configured_integration_count": len(configured_integrations),
            "validated_integration_count": len(validated_integrations),
            "enabled_binding_count": enabled_binding_count,
            "completed_sync_run_count": completed_sync_run_count,
            "synced_asset_count": synced_asset_count,
            "completed_export_count": completed_export_count,
            "exportable_document_count": exportable_document_count,
            "live_llm_provider_count": len(live_providers),
            "active_user_count": active_user_count,
            "role_count": role_count,
            "audit_log_count": audit_log_count,
            "policy_count": policy_count,
            "field_permission_count": field_permission_count,
            "metric_event_count": metric_event_count,
            "quota_usage_count": quota_usage_count,
            "active_alert_rule_count": active_alert_rule_count,
            "work_item_count": work_item_count,
            "done_work_item_count": done_work_item_count,
            "active_work_item_count": active_work_item_count,
            "blocked_work_item_count": blocked_work_item_count,
            "overdue_work_item_count": overdue_work_item_count,
            "preference_count": preference_count,
            "unacknowledged_required_notification_count": unacknowledged_required_notification_count,
            "escalated_notification_count": escalated_notification_count,
            "notification_event_count": notification_event_count,
            "sent_notification_event_count": sent_notification_event_count,
            "failed_notification_event_count": failed_notification_event_count,
        }

    async def _count(
        self,
        model: Any,
        tenant_id: UUID | None,
        *conditions: Any,
    ) -> int:
        stmt = select(func.count(model.id))
        filters = list(conditions)
        tenant_column = getattr(model, "tenant_id", None)
        deleted_column = getattr(model, "deleted_at", None)
        if tenant_id is not None and tenant_column is not None:
            filters.append(tenant_column == tenant_id)
        if deleted_column is not None:
            filters.append(deleted_column.is_(None))
        if filters:
            stmt = stmt.where(*filters)
        result = await self.db.execute(stmt)
        return int(result.scalar_one_or_none() or 0)

    async def _configured_integrations(self, tenant_id: UUID | None) -> list[Any]:
        stmt = select(IntegrationProvider).where(
            IntegrationProvider.deleted_at.is_(None),
            IntegrationProvider.is_enabled.is_(True),
        )
        if tenant_id is not None:
            stmt = stmt.where(IntegrationProvider.tenant_id == tenant_id)
        result = await self.db.execute(stmt)
        providers = list(result.scalars().all())
        return [
            provider
            for provider in providers
            if self._integration_has_endpoint(provider)
        ]

    async def _exportable_document_count(self, tenant_id: UUID | None) -> int:
        placeholder_status = Document.metadata_json["generation_status"].astext
        stmt = select(func.count(Document.id)).where(
            Document.deleted_at.is_(None),
            (Document.metadata_json.is_(None))
            | (placeholder_status.is_(None))
            | (placeholder_status != "placeholder"),
        )
        if tenant_id is not None:
            stmt = stmt.where(Document.tenant_id == tenant_id)
        result = await self.db.execute(stmt)
        return int(result.scalar_one_or_none() or 0)

    async def _live_llm_providers(self, tenant_id: UUID | None) -> list[Any]:
        stmt = select(Provider).where(
            Provider.deleted_at.is_(None),
            Provider.status == ProviderStatus.ACTIVE.value,
            Provider.provider_type == ProviderType.LLM.value,
        )
        if tenant_id is not None:
            stmt = stmt.where(Provider.tenant_id == tenant_id)
        result = await self.db.execute(stmt)
        providers = list(result.scalars().all())
        return [provider for provider in providers if self._provider_is_live(provider)]

    def _provider_is_live(self, provider: Any) -> bool:
        try:
            return bool(is_live_configured(provider))
        except AttributeError:
            return True

    def _integration_has_endpoint(self, provider: Any) -> bool:
        try:
            config = provider.config_json or {}
        except AttributeError:
            return True
        for key in ("endpoint", "base_url", "url", "server_url", "api_url", "runtime_ref", "managed_runtime_ref"):
            value = config.get(key)
            if isinstance(value, str) and value.strip():
                return True
        return False

    def _integration_has_validation_evidence(self, provider: Any) -> bool:
        try:
            last_sync_at = provider.last_sync_at
        except AttributeError:
            return True
        if last_sync_at is not None:
            return True
        try:
            config = provider.config_json or {}
        except AttributeError:
            return True
        validation = config.get("validation") or config.get("last_validation") or {}
        if isinstance(validation, dict):
            return validation.get("status") in {"connected", "synced", "passed"}
        return False

    def _build_checks(
        self,
        readiness: CapabilityReadinessResponse,
        evidence: dict[str, Any],
    ) -> list[CapabilityCommissioningCheck]:
        return [
            self._live_provider_check(readiness, evidence),
            self._knowledge_graph_check(evidence),
            self._integration_check(evidence),
            self._integration_sync_check(evidence),
            self._collaboration_execution_check(evidence),
            self._notification_alert_check(evidence),
            self._export_validation_check(evidence),
            self._team_permission_check(evidence),
            self._ops_observability_check(evidence),
        ]

    def _live_provider_check(
        self,
        readiness: CapabilityReadinessResponse,
        evidence: dict[str, Any],
    ) -> CapabilityCommissioningCheck:
        count = max(
            self._capability_evidence_int(readiness, "provider_llm", "live_llm_count"),
            int(evidence.get("live_llm_provider_count") or 0),
        )
        return self._check(
            key="live_llm_provider",
            capability_key="provider_llm",
            label="真实 LLM Provider 校准",
            passed=count > 0,
            severity="critical",
            summary=(
                "至少一个真实 LLM Provider 可作为文档生成和 Agent 执行的生产证据。"
                if count > 0
                else "尚未发现可作为生产证据的真实 LLM Provider。"
            ),
            evidence={"live_llm_provider_count": count},
            blockers=[] if count > 0 else ["配置真实 LLM API key 或 service token，并运行 Provider 连通性测试。"],
            action=CapabilityCommissioningAction(
                label="配置 Provider",
                href="/providers",
                api_endpoint="/api/v1/providers/{provider_id}/test",
                method="POST",
                description="进入 Provider 页面补齐真实凭据并执行连通性测试。",
            ),
            can_run=count > 0,
            configuration_requirements={
                "required_fields": ["credential_ref/secret_ref", "base_url", "model"],
                "forbidden_values": ["mock", "sandbox", "test_api_key", "placeholder"],
                "secret_policy": (
                    "Store real credentials only in controlled runtime secrets. "
                    "Provider config and version config may contain non-secret references only."
                ),
                "candidate_spend_cap": "Stop at the first of USD 5 total spend, 50 generation calls, or 100k tokens.",
            },
            validation_steps=[
                "Create or update an active LLM Provider with credential_ref/secret_ref only.",
                "/api/v1/providers/{provider_id}/test",
                "Confirm success=true, mode=live, production_ready=true, sandbox_fallback=false.",
            ],
            evidence_requirements=[
                "successful_live_provider_test",
                "secret_managed_non_sandbox_credential_ref",
                "active_provider_status",
                "spend_cap_or_usage_limit",
            ],
        )

    def _knowledge_graph_check(self, evidence: dict[str, Any]) -> CapabilityCommissioningCheck:
        source_count = int(evidence.get("source_file_count") or 0)
        entry_count = int(evidence.get("knowledge_entry_count") or 0)
        link_count = int(evidence.get("knowledge_link_count") or 0)
        passed = source_count > 0 and entry_count > 0 and link_count > 0
        blockers: list[str] = []
        if source_count <= 0:
            blockers.append("缺少项目来源文件。")
        if entry_count <= 0:
            blockers.append("缺少知识条目。")
        if link_count <= 0:
            blockers.append("缺少知识关系边，无法证明图谱追溯可用。")
        return self._check(
            key="knowledge_graph_evidence",
            capability_key="knowledge_graph",
            label="来源知识图谱校准",
            passed=passed,
            severity="critical",
            summary=(
                "项目资料、知识条目和关系边均已存在，可支持生成、检索和追溯。"
                if passed
                else "知识图谱还缺少来源、条目或关系证据。"
            ),
            evidence={
                "source_file_count": source_count,
                "knowledge_entry_count": entry_count,
                "knowledge_link_count": link_count,
            },
            blockers=blockers,
            action=CapabilityCommissioningAction(
                label="补齐项目资料",
                href="/projects",
                api_endpoint="/api/v1/projects/{project_id}/files",
                method="POST",
                description="进入项目上传真实资料，并运行知识抽取形成条目和关系。",
            ),
            can_run=source_count > 0,
        )

    def _integration_check(self, evidence: dict[str, Any]) -> CapabilityCommissioningCheck:
        count = int(evidence.get("configured_integration_count") or 0)
        validated_count = int(evidence.get("validated_integration_count") or 0)
        passed = count > 0 and validated_count > 0
        return self._check(
            key="external_integration_connectivity",
            capability_key="external_integrations",
            label="外部系统集成校准",
            passed=passed,
            severity="critical",
            summary=(
                "至少一个外部系统集成已启用、具备真实连接端点，并已有连接或同步验证证据。"
                if passed
                else "外部集成尚未同时满足 endpoint 配置和连接/同步验证证据。"
            ),
            evidence={
                "configured_integration_count": count,
                "validated_integration_count": validated_count,
            },
            blockers=[] if passed else [
                "配置 Jira、Confluence、禅道或自定义集成的真实端点和认证信息。",
                "完成一次连接测试或同步，生成 last_sync_at 或 integration.sync.completed 证据。",
            ],
            action=CapabilityCommissioningAction(
                label="配置集成",
                href="/settings",
                api_endpoint="/api/v1/integrations/providers",
                method="POST",
                description="进入设置页补齐外部系统连接配置并执行同步验证。",
            ),
            can_run=count > 0,
            configuration_requirements={
                "required_fields": ["base_url", "api_key", "health_path", "sync_path"],
                "supported_providers": ["jira", "confluence", "zentao", "feishu", "custom"],
                "secret_policy": "Use runtime-managed credentials. Do not store production tokens in source-controlled files.",
            },
            validation_steps=[
                "/api/v1/integrations/providers/{integration_id}/test",
                "/api/v1/integrations/providers/{integration_id}/sync",
                "Confirm status=connected or status=synced and review masked response details.",
            ],
            evidence_requirements=[
                "integration.sync.completed event or last_sync_at",
                "configured endpoint/base_url/url",
                "non-empty authentication setting",
            ],
        )

    def _integration_sync_check(self, evidence: dict[str, Any]) -> CapabilityCommissioningCheck:
        bindings = int(evidence.get("enabled_binding_count") or 0)
        runs = int(evidence.get("completed_sync_run_count") or 0)
        assets = int(evidence.get("synced_asset_count") or 0)
        passed = bindings > 0 and runs > 0 and assets > 0
        blockers: list[str] = []
        if bindings <= 0:
            blockers.append("缺少外部集成项目绑定。")
        if runs <= 0:
            blockers.append("缺少已完成外部同步运行。")
        if assets <= 0:
            blockers.append("缺少同步资产到来源文件/知识条目的映射。")
        return self._check(
            key="external_integration_project_sync",
            capability_key="external_integration_sync",
            label="外部同步项目写入校准",
            passed=passed,
            severity="critical",
            summary=(
                "外部系统已经完成项目绑定、同步运行和资产写入，跨系统资料闭环可验证。"
                if passed
                else "外部集成尚未形成项目绑定、同步运行、同步资产三段证据。"
            ),
            evidence={
                "enabled_binding_count": bindings,
                "completed_sync_run_count": runs,
                "synced_asset_count": assets,
            },
            blockers=blockers,
            action=CapabilityCommissioningAction(
                label="校准外部同步",
                href="/settings",
                api_endpoint="/api/v1/integrations/bindings/{binding_id}/sync",
                method="POST",
                description="进入集成配置，为项目绑定外部范围并执行一次同步，确认来源文件和知识条目被写入。",
            ),
            can_run=bindings > 0,
            configuration_requirements={
                "required_fields": ["integration_provider_id", "project_id", "scope_json", "field_mapping_json"],
                "evidence_chain": ["project binding", "completed sync run", "synced source file", "knowledge entry"],
            },
            validation_steps=[
                "/api/v1/integrations/project-bindings",
                "/api/v1/integrations/bindings/{binding_id}/sync",
                "Confirm completed sync run and at least one synced asset.",
            ],
            evidence_requirements=[
                "enabled project binding",
                "completed integration sync run",
                "integration synced asset linked to source file and knowledge entry",
            ],
        )

    def _collaboration_execution_check(self, evidence: dict[str, Any]) -> CapabilityCommissioningCheck:
        total = int(evidence.get("work_item_count") or 0)
        done = int(evidence.get("done_work_item_count") or 0)
        active = int(evidence.get("active_work_item_count") or 0)
        blocked = int(evidence.get("blocked_work_item_count") or 0)
        overdue = int(evidence.get("overdue_work_item_count") or 0)
        passed = total > 0 and done > 0 and blocked == 0 and overdue == 0
        blockers: list[str] = []
        if total <= 0:
            blockers.append("缺少协同责任项。")
        if done <= 0:
            blockers.append("缺少已完成责任项。")
        if blocked > 0:
            blockers.append("存在阻塞责任项。")
        if overdue > 0:
            blockers.append("存在逾期责任项。")
        return self._check(
            key="collaboration_execution_evidence",
            capability_key="collaboration_execution",
            label="协同责任执行校准",
            passed=passed,
            severity="critical",
            summary=(
                "协同责任项已经形成创建、执行、完成证据，且没有阻塞或逾期项。"
                if passed
                else "协同执行尚未形成完整责任流转证据，或存在阻塞/逾期项。"
            ),
            evidence={
                "work_item_count": total,
                "done_work_item_count": done,
                "active_work_item_count": active,
                "blocked_work_item_count": blocked,
                "overdue_work_item_count": overdue,
            },
            blockers=blockers,
            action=CapabilityCommissioningAction(
                label="校准协同责任",
                href="/team",
                api_endpoint="/api/v1/collaboration/work-items",
                method="POST",
                description="进入团队协同或文档评审流程，创建并完成至少一个责任项，清理阻塞和逾期项。",
            ),
            can_run=total > 0,
            validation_steps=[
                "/api/v1/collaboration/work-items",
                "Create or complete a review/follow-up work item.",
                "Confirm no blocked or overdue production-critical work items remain.",
            ],
            evidence_requirements=[
                "at least one completed collaboration work item",
                "no blocked work item",
                "no overdue active work item",
            ],
        )

    def _notification_alert_check(self, evidence: dict[str, Any]) -> CapabilityCommissioningCheck:
        preferences = int(evidence.get("preference_count") or 0)
        unacknowledged = int(evidence.get("unacknowledged_required_notification_count") or 0)
        escalated = int(evidence.get("escalated_notification_count") or 0)
        events = int(evidence.get("notification_event_count") or 0)
        sent = int(evidence.get("sent_notification_event_count") or 0)
        failed = int(evidence.get("failed_notification_event_count") or 0)
        passed = preferences > 0 and sent > 0 and unacknowledged == 0 and escalated == 0 and failed == 0
        blockers: list[str] = []
        if preferences <= 0:
            blockers.append("缺少通知偏好。")
        if sent <= 0:
            blockers.append("缺少成功通知投递事件。")
        if unacknowledged > 0:
            blockers.append("存在未确认的 required 通知。")
        if escalated > 0:
            blockers.append("存在升级未处理通知。")
        if failed > 0:
            blockers.append("存在失败通知投递。")
        return self._check(
            key="notification_alert_handling_evidence",
            capability_key="notification_alert_handling",
            label="通知确认与告警投递校准",
            passed=passed,
            severity="critical",
            summary=(
                "通知偏好、成功投递和确认处理均已形成证据，告警触达闭环可验证。"
                if passed
                else "通知告警尚未形成偏好、成功投递、确认清零的完整证据。"
            ),
            evidence={
                "preference_count": preferences,
                "unacknowledged_required_notification_count": unacknowledged,
                "escalated_notification_count": escalated,
                "notification_event_count": events,
                "sent_notification_event_count": sent,
                "failed_notification_event_count": failed,
            },
            blockers=blockers,
            action=CapabilityCommissioningAction(
                label="校准通知告警",
                href="/health",
                api_endpoint="/api/v1/ops/notification-deliveries",
                method="GET",
                description="检查通知偏好、投递记录和需要确认的通知，处理失败投递或升级通知。",
            ),
            can_run=preferences > 0 or events > 0,
            validation_steps=[
                "/api/v1/notifications/preferences",
                "/api/v1/ops/notification-deliveries",
                "Confirm sent delivery exists and required notifications are acknowledged.",
            ],
            evidence_requirements=[
                "notification preference",
                "sent notification delivery event",
                "zero failed deliveries",
                "zero unacknowledged required notifications",
            ],
        )

    def _export_validation_check(self, evidence: dict[str, Any]) -> CapabilityCommissioningCheck:
        completed_count = int(evidence.get("completed_export_count") or 0)
        exportable_count = int(evidence.get("exportable_document_count") or 0)
        passed = completed_count > 0
        blockers = []
        if exportable_count <= 0:
            blockers.append("缺少非 placeholder 的可导出文档。")
        if completed_count <= 0:
            blockers.append("缺少成功导出记录。")
        return self._check(
            key="export_validation",
            capability_key="export_release",
            label="交付导出校准",
            passed=passed,
            severity="critical",
            summary=(
                "已有成功导出记录，可证明交付发布链路可运行。"
                if passed
                else "导出链路尚未形成成功运行证据。"
            ),
            evidence={
                "completed_export_count": completed_count,
                "exportable_document_count": exportable_count,
            },
            blockers=blockers,
            action=CapabilityCommissioningAction(
                label="运行导出验证",
                href="/exports",
                api_endpoint="/api/v1/exports/project-package",
                method="POST",
                description="进入导出中心选择非 placeholder 文档，生成并确认交付包。",
            ),
            can_run=exportable_count > 0,
        )

    def _team_permission_check(self, evidence: dict[str, Any]) -> CapabilityCommissioningCheck:
        active_users = int(evidence.get("active_user_count") or 0)
        roles = int(evidence.get("role_count") or 0)
        audit_logs = int(evidence.get("audit_log_count") or 0)
        policies = int(evidence.get("policy_count") or 0)
        field_permissions = int(evidence.get("field_permission_count") or 0)
        passed = active_users > 0 and roles > 0 and audit_logs > 0 and policies > 0 and field_permissions > 0
        blockers: list[str] = []
        if policies <= 0:
            blockers.append("Missing ABAC policy configuration.")
        if field_permissions <= 0:
            blockers.append("Missing field-level permission configuration.")
        if active_users <= 0:
            blockers.append("缺少活跃团队成员。")
        if roles <= 0:
            blockers.append("缺少角色权限配置。")
        if audit_logs <= 0:
            blockers.append("缺少权限或关键操作审计记录。")
        return self._check(
            key="team_permission_audit",
            capability_key="team_access",
            label="团队权限与审计校准",
            passed=passed,
            severity="critical",
            summary=(
                "团队成员、角色权限和审计记录均已存在，可支撑租户级权限治理。"
                if passed
                else "团队权限闭环尚未形成完整成员、角色和审计证据。"
            ),
            evidence={
                "active_user_count": active_users,
                "role_count": roles,
                "audit_log_count": audit_logs,
                "policy_count": policies,
                "field_permission_count": field_permissions,
            },
            blockers=blockers,
            action=CapabilityCommissioningAction(
                label="管理团队权限",
                href="/team",
                api_endpoint="/api/v1/identity/roles",
                method="POST",
                description="进入团队权限中心补齐成员、角色和审计证据。",
            ),
            can_run=active_users > 0,
        )

    def _ops_observability_check(self, evidence: dict[str, Any]) -> CapabilityCommissioningCheck:
        metrics = int(evidence.get("metric_event_count") or 0)
        quotas = int(evidence.get("quota_usage_count") or 0)
        alerts = int(evidence.get("active_alert_rule_count") or 0)
        passed = metrics > 0 and quotas > 0 and alerts > 0
        blockers: list[str] = []
        if metrics <= 0:
            blockers.append("缺少运行指标事件。")
        if quotas <= 0:
            blockers.append("缺少配额使用记录。")
        if alerts <= 0:
            blockers.append("缺少启用的告警规则。")
        return self._check(
            key="ops_observability_evidence",
            capability_key="ops_observability",
            label="运维监控与配额校准",
            passed=passed,
            severity="critical",
            summary=(
                "运行指标、配额使用和告警规则均已存在，可支撑生产运行观测。"
                if passed
                else "运维监控闭环尚未形成完整指标、配额和告警证据。"
            ),
            evidence={
                "metric_event_count": metrics,
                "quota_usage_count": quotas,
                "active_alert_rule_count": alerts,
            },
            blockers=blockers,
            action=CapabilityCommissioningAction(
                label="查看运维监控",
                href="/health",
                api_endpoint="/api/v1/ops/metrics",
                method="GET",
                description="进入运维监控页确认指标、配额和告警规则。",
            ),
            can_run=metrics > 0 or quotas > 0 or alerts > 0,
        )

    def _check(
        self,
        *,
        key: str,
        capability_key: str,
        label: str,
        passed: bool,
        severity: str,
        summary: str,
        evidence: dict[str, Any],
        blockers: list[str],
        action: CapabilityCommissioningAction,
        can_run: bool,
        configuration_requirements: dict[str, Any] | None = None,
        validation_steps: list[str] | None = None,
        evidence_requirements: list[str] | None = None,
    ) -> CapabilityCommissioningCheck:
        return CapabilityCommissioningCheck(
            key=key,
            capability_key=capability_key,
            label=label,
            status="passed" if passed else "failed",
            severity=severity,
            summary=summary,
            evidence=evidence,
            blockers=blockers,
            action=action,
            can_run=can_run,
            configuration_requirements=configuration_requirements or {},
            validation_steps=validation_steps or [],
            evidence_requirements=evidence_requirements or [],
        )

    def _response(
        self,
        *,
        tenant_id: UUID | None,
        readiness: CapabilityReadinessResponse,
        checks: list[CapabilityCommissioningCheck],
        executed: bool,
    ) -> CapabilityCommissioningResponse:
        critical_checks = [
            check for check in checks if check.key in self.CRITICAL_CHECKS
        ]
        passed_critical_count = len(
            [check for check in critical_checks if check.status == "passed"]
        )
        overall_score = round((passed_critical_count / len(critical_checks)) * 100) if critical_checks else 0
        production_usable = (
            readiness.production_ready
            and all(check.status == "passed" for check in critical_checks)
        )
        if production_usable:
            overall_status = "ready"
        elif passed_critical_count > 0:
            overall_status = "degraded"
        else:
            overall_status = "blocked"
        next_steps = [
            blocker
            for check in checks
            for blocker in check.blockers
        ][:6]
        return CapabilityCommissioningResponse(
            generated_at=datetime.now(timezone.utc),
            tenant_id=tenant_id,
            production_usable=production_usable,
            executed=executed,
            overall_status=overall_status,
            overall_score=overall_score,
            readiness=readiness,
            checks=checks,
            summary={
                "critical_check_count": len(critical_checks),
                "passed_critical_count": passed_critical_count,
                "failed_check_count": len([check for check in checks if check.status == "failed"]),
                "runnable_check_count": len([check for check in checks if check.can_run]),
            },
            next_steps=next_steps,
        )

    def _capability_evidence_int(
        self,
        readiness: CapabilityReadinessResponse,
        capability_key: str,
        evidence_key: str,
    ) -> int:
        for capability in readiness.capabilities:
            if capability.key != capability_key:
                continue
            value = (capability.evidence or {}).get(evidence_key)
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int | float):
                return int(value)
        return 0
