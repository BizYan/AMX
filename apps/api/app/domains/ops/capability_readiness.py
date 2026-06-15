"""Core product capability readiness service."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.agent.models import (
    AgentProfile,
    AgentProfileStatus,
    AgentSkill,
    SkillStatus,
    WorkflowDefinition,
    WorkflowVersion,
)
from app.domains.documents.models import Document, DocumentGenerationSession
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
from app.domains.ops.models import AlertRule, MetricEvent, NotificationEvent, QuotaUsage
from app.domains.ops.schemas import (
    CapabilityReadinessItem,
    CapabilityReadinessResponse,
)
from app.domains.projects.models import SourceFile
from app.domains.providers.capability import (
    is_live_configured,
    is_sandbox_provider,
)
from app.domains.providers.models import Provider, ProviderStatus, ProviderType
from app.domains.templates.models import Template, TemplateSection, TemplateVersion
from app.models.identity import Role, User


class CapabilityReadinessService:
    """Build a tenant-level view of whether core AMX capabilities are usable."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build(self, tenant_id: UUID | None) -> CapabilityReadinessResponse:
        """Return a production-readiness summary for the current tenant."""
        provider_evidence = await self._provider_evidence(tenant_id)
        capabilities = [
            self._provider_capability(provider_evidence),
            await self._document_capability(tenant_id, provider_evidence),
            await self._orchestration_capability(tenant_id),
            await self._knowledge_capability(tenant_id),
            await self._integration_capability(tenant_id),
            await self._integration_sync_capability(tenant_id),
            await self._collaboration_capability(tenant_id),
            await self._notification_capability(tenant_id),
            await self._export_capability(tenant_id),
            await self._team_capability(tenant_id),
            await self._ops_capability(tenant_id),
        ]

        overall_score = round(
            sum(capability.score for capability in capabilities) / len(capabilities)
        )
        has_blocker = any(capability.status == "blocked" for capability in capabilities)
        production_ready = (
            not has_blocker
            and provider_evidence["live_llm_count"] > 0
            and all(capability.status in {"ready", "degraded"} for capability in capabilities)
        )
        if production_ready and overall_score >= 80:
            overall_status = "ready"
        elif has_blocker:
            overall_status = "blocked"
        else:
            overall_status = "degraded"

        return CapabilityReadinessResponse(
            generated_at=datetime.now(timezone.utc),
            tenant_id=tenant_id,
            overall_status=overall_status,
            overall_score=overall_score,
            production_ready=production_ready,
            capabilities=capabilities,
        )

    async def _count(self, model: Any, tenant_id: UUID | None, *conditions: Any) -> int:
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

    async def _provider_evidence(self, tenant_id: UUID | None) -> dict[str, int]:
        stmt = select(Provider).where(Provider.deleted_at.is_(None))
        if tenant_id is not None:
            stmt = stmt.where(Provider.tenant_id == tenant_id)
        result = await self.db.execute(stmt)
        providers = list(result.scalars().all())

        active = [provider for provider in providers if provider.status == ProviderStatus.ACTIVE.value]
        live = [provider for provider in active if is_live_configured(provider)]
        sandbox = [provider for provider in active if is_sandbox_provider(provider)]
        live_llm = [provider for provider in live if provider.provider_type == ProviderType.LLM.value]

        return {
            "provider_count": len(providers),
            "active_provider_count": len(active),
            "live_provider_count": len(live),
            "sandbox_provider_count": len(sandbox),
            "live_llm_count": len(live_llm),
            "live_graph_provider_count": len(
                [provider for provider in live if provider.provider_type == ProviderType.GRAPHIFY.value]
            ),
            "live_gitnexus_provider_count": len(
                [provider for provider in live if provider.provider_type == ProviderType.GITNEXUS.value]
            ),
        }

    def _provider_capability(self, evidence: dict[str, int]) -> CapabilityReadinessItem:
        if evidence["live_llm_count"] > 0:
            return self._item(
                "provider_llm",
                "Provider 与 LLM 生成",
                "ready",
                100,
                "至少一个真实 LLM Provider 已激活，可作为文档生成和 Agent 执行的生产能力。",
                evidence,
            )
        if evidence["sandbox_provider_count"] > 0 or evidence["active_provider_count"] > 0:
            return self._item(
                "provider_llm",
                "Provider 与 LLM 生成",
                "degraded",
                55,
                "存在 Provider 配置，但没有可作为生产证据的真实 LLM 凭据。",
                evidence,
                blockers=["LLM 生成能力不能只依赖 sandbox/mock 配置。"],
                recommended_actions=["配置真实 LLM API key 或 service token，并运行 Provider 测试。"],
            )
        return self._item(
            "provider_llm",
            "Provider 与 LLM 生成",
            "blocked",
            20,
            "没有可用 Provider，文档生成、Agent 执行和知识抽取无法证明生产可用。",
            evidence,
            blockers=["缺少真实 LLM Provider。"],
            recommended_actions=["在供应商能力页新增 LLM Provider，并完成连通性测试。"],
        )

    async def _document_capability(
        self,
        tenant_id: UUID | None,
        provider_evidence: dict[str, int],
    ) -> CapabilityReadinessItem:
        document_count = await self._count(Document, tenant_id)
        session_count = await self._count(DocumentGenerationSession, tenant_id)
        template_count = await self._count(Template, tenant_id)
        template_version_count = await self._count(TemplateVersion, tenant_id)
        section_count = await self._count(TemplateSection, tenant_id)
        evidence = {
            "document_count": document_count,
            "generation_session_count": session_count,
            "template_count": template_count,
            "template_version_count": template_version_count,
            "template_section_count": section_count,
            "live_llm_count": provider_evidence["live_llm_count"],
        }

        if section_count > 0 and provider_evidence["live_llm_count"] > 0:
            return self._item(
                "document_delivery",
                "项目文档交付闭环",
                "ready",
                95,
                "模板章节、对话式生成和真实 LLM 基础能力已具备。",
                evidence,
            )
        if section_count > 0 or template_count > 0 or session_count > 0:
            return self._item(
                "document_delivery",
                "项目文档交付闭环",
                "degraded",
                65,
                "文档工作台结构已具备，但真实 LLM 或完整章节配置仍未满足生产闭环。",
                evidence,
                blockers=["缺少真实生成能力或完整章节模板证据。"],
                recommended_actions=["完成 LLM Provider 配置，并确认 URS/BRD/PRD/设计/测试模板章节均已发布。"],
            )
        return self._item(
            "document_delivery",
            "项目文档交付闭环",
            "blocked",
            25,
            "项目文档闭环缺少可执行模板、章节或生成会话证据。",
            evidence,
            blockers=["缺少文档交付基础数据。"],
            recommended_actions=["初始化核心文档模板章节，并创建一次对话式生成会话。"],
        )

    async def _orchestration_capability(self, tenant_id: UUID | None) -> CapabilityReadinessItem:
        published_skills = await self._count(
            AgentSkill,
            tenant_id,
            AgentSkill.status == SkillStatus.PUBLISHED.value,
        )
        active_agents = await self._count(
            AgentProfile,
            tenant_id,
            AgentProfile.status == AgentProfileStatus.ACTIVE.value,
        )
        active_workflows = await self._count(
            WorkflowDefinition,
            tenant_id,
            WorkflowDefinition.is_active == 1,
        )
        active_workflow_versions = await self._active_workflow_version_count(tenant_id)
        evidence = {
            "published_skill_count": published_skills,
            "active_agent_count": active_agents,
            "active_workflow_count": active_workflows,
            "active_workflow_version_count": active_workflow_versions,
        }
        if published_skills > 0 and active_agents > 0 and active_workflow_versions > 0:
            return self._item(
                "agent_orchestration",
                "Agent/Skill/Workflow 编排",
                "ready",
                95,
                "已存在发布 Skill、启用 Agent 和可执行 Workflow 版本。",
                evidence,
            )
        if published_skills > 0 or active_agents > 0 or active_workflows > 0:
            return self._item(
                "agent_orchestration",
                "Agent/Skill/Workflow 编排",
                "degraded",
                60,
                "编排资产存在，但 Skill、Agent、Workflow 尚未形成完整可执行组合。",
                evidence,
                blockers=["缺少发布 Skill、启用 Agent 或激活 Workflow 版本中的至少一项。"],
                recommended_actions=["在智能编排中绑定 Skill、Agent 和 Workflow 后执行一次运行验证。"],
            )
        return self._item(
            "agent_orchestration",
            "Agent/Skill/Workflow 编排",
            "blocked",
            25,
            "没有可用编排资产，无法证明智能编排核心流程可执行。",
            evidence,
            blockers=["缺少 Skill、Agent 和 Workflow。"],
            recommended_actions=["初始化平台级 Skill、常用 Agent 和核心文档工作流。"],
        )

    async def _knowledge_capability(self, tenant_id: UUID | None) -> CapabilityReadinessItem:
        source_files = await self._count(SourceFile, tenant_id)
        entries = await self._count(KnowledgeEntry, tenant_id)
        links = await self._count(KnowledgeLink, tenant_id)
        evidence = {
            "source_file_count": source_files,
            "knowledge_entry_count": entries,
            "knowledge_link_count": links,
        }
        if source_files > 0 and entries > 0 and links > 0:
            return self._item(
                "knowledge_graph",
                "知识图谱与来源追溯",
                "ready",
                90,
                "来源资料、知识条目和关系边已存在，可支持项目知识检索与图谱追溯。",
                evidence,
            )
        if entries > 0 or source_files > 0:
            blockers = []
            if source_files <= 0:
                blockers.append("缺少项目来源文件，知识条目无法证明来源追溯。")
            if entries <= 0:
                blockers.append("缺少知识条目，无法支持生成、检索和图谱追溯。")
            if links <= 0:
                blockers.append("缺少知识关系边或完整来源追溯。")
            return self._item(
                "knowledge_graph",
                "知识图谱与来源追溯",
                "degraded",
                60,
                "已有来源或知识条目，但关系边不足，图谱推理和影响追溯有限。",
                evidence,
                blockers=blockers,
                recommended_actions=["从项目文件重新抽取知识，并补齐条目之间的引用/依赖关系。"],
            )
        return self._item(
            "knowledge_graph",
            "知识图谱与来源追溯",
            "blocked",
            25,
            "缺少项目来源文件和知识条目，知识图谱核心能力不可用。",
            evidence,
            blockers=["没有可检索知识。"],
            recommended_actions=["上传项目资料并运行来源摄取到知识图谱流程。"],
        )

    async def _integration_capability(self, tenant_id: UUID | None) -> CapabilityReadinessItem:
        stmt = select(IntegrationProvider).where(IntegrationProvider.deleted_at.is_(None))
        if tenant_id is not None:
            stmt = stmt.where(IntegrationProvider.tenant_id == tenant_id)
        result = await self.db.execute(stmt)
        providers = list(result.scalars().all())
        enabled = [provider for provider in providers if provider.is_enabled]
        configured = [
            provider
            for provider in enabled
            if self._has_integration_endpoint(provider.config_json or {})
        ]
        evidence = {
            "integration_provider_count": len(providers),
            "enabled_integration_count": len(enabled),
            "configured_integration_count": len(configured),
        }
        if configured:
            return self._item(
                "external_integrations",
                "外部系统集成",
                "ready",
                85,
                "已有启用且具备端点配置的外部集成，可执行连接测试和同步。",
                evidence,
            )
        if enabled:
            return self._item(
                "external_integrations",
                "外部系统集成",
                "degraded",
                55,
                "存在启用集成，但缺少 endpoint/base_url/url 等真实连接配置。",
                evidence,
                blockers=["启用集成尚未配置真实连接端点。"],
                recommended_actions=["补齐集成端点和认证配置，并运行连接测试。"],
            )
        return self._item(
            "external_integrations",
            "外部系统集成",
            "blocked",
            30,
            "没有启用的外部集成，暂不能形成跨系统同步闭环。",
            evidence,
            blockers=["缺少启用集成。"],
            recommended_actions=["新增 Jira/Confluence/禅道或自定义集成并完成一次同步验证。"],
        )

    async def _integration_sync_capability(self, tenant_id: UUID | None) -> CapabilityReadinessItem:
        enabled_bindings = await self._count(
            IntegrationProjectBinding,
            tenant_id,
            IntegrationProjectBinding.is_enabled.is_(True),
        )
        completed_sync_runs = await self._count(
            IntegrationSyncRun,
            tenant_id,
            IntegrationSyncRun.status == "completed",
        )
        synced_assets = await self._count(IntegrationSyncedAsset, tenant_id)
        evidence = {
            "enabled_binding_count": enabled_bindings,
            "completed_sync_run_count": completed_sync_runs,
            "synced_asset_count": synced_assets,
        }
        if enabled_bindings > 0 and completed_sync_runs > 0 and synced_assets > 0:
            return self._item(
                "external_integration_sync",
                "外部同步与项目知识写入",
                "ready",
                90,
                "外部系统已经绑定到项目，并形成完成同步运行与同步资产证据。",
                evidence,
            )
        if enabled_bindings > 0 or completed_sync_runs > 0 or synced_assets > 0:
            return self._item(
                "external_integration_sync",
                "外部同步与项目知识写入",
                "degraded",
                60,
                "外部同步已有局部证据，但尚未形成绑定、运行、资产三段闭环。",
                evidence,
                blockers=["缺少项目绑定、完成同步运行或同步资产证据。"],
                recommended_actions=["为项目绑定一个外部范围，执行同步并确认写入来源文件和知识条目。"],
            )
        return self._item(
            "external_integration_sync",
            "外部同步与项目知识写入",
            "blocked",
            25,
            "没有外部项目绑定和同步资产证据，跨系统资料进入项目知识库的闭环不可验证。",
            evidence,
            blockers=["缺少外部项目绑定。", "缺少已完成同步运行。", "缺少同步资产映射。"],
            recommended_actions=["在集成配置中绑定项目范围，并完成一次可审计的同步。"],
        )

    async def _collaboration_capability(self, tenant_id: UUID | None) -> CapabilityReadinessItem:
        now = datetime.now(timezone.utc)
        active_statuses = [
            WorkItemStatus.OPEN.value,
            WorkItemStatus.IN_PROGRESS.value,
            WorkItemStatus.BLOCKED.value,
        ]
        work_items = await self._count(CollaborationWorkItem, tenant_id)
        done_items = await self._count(
            CollaborationWorkItem,
            tenant_id,
            CollaborationWorkItem.status == WorkItemStatus.DONE.value,
        )
        active_items = await self._count(
            CollaborationWorkItem,
            tenant_id,
            CollaborationWorkItem.status.in_(active_statuses),
        )
        blocked_items = await self._count(
            CollaborationWorkItem,
            tenant_id,
            CollaborationWorkItem.status == WorkItemStatus.BLOCKED.value,
        )
        overdue_items = await self._count(
            CollaborationWorkItem,
            tenant_id,
            CollaborationWorkItem.status.in_(active_statuses),
            CollaborationWorkItem.due_at.is_not(None),
            CollaborationWorkItem.due_at < now,
        )
        evidence = {
            "work_item_count": work_items,
            "done_work_item_count": done_items,
            "active_work_item_count": active_items,
            "blocked_work_item_count": blocked_items,
            "overdue_work_item_count": overdue_items,
        }
        if work_items > 0 and done_items > 0 and blocked_items == 0 and overdue_items == 0:
            return self._item(
                "collaboration_execution",
                "协同责任与评审执行",
                "ready",
                95,
                "协同工作项已创建并完成过交付，且没有阻塞或逾期责任项。",
                evidence,
            )
        if work_items > 0 and blocked_items == 0:
            return self._item(
                "collaboration_execution",
                "协同责任与评审执行",
                "degraded",
                65,
                "协同工作项已存在，但完成证据或时效闭环仍不足。",
                evidence,
                blockers=["缺少已完成责任项，或仍存在逾期工作项。"],
                recommended_actions=["在团队协同中完成至少一个评审/跟进工作项，并清理逾期项。"],
            )
        return self._item(
            "collaboration_execution",
            "协同责任与评审执行",
            "blocked",
            25,
            "没有可审计的责任项执行证据，或仍存在阻塞责任项。",
            evidence,
            blockers=[
                *([] if work_items else ["缺少协同责任项。"]),
                *([] if blocked_items == 0 else ["存在阻塞责任项。"]),
                *([] if overdue_items == 0 else ["存在逾期责任项。"]),
            ],
            recommended_actions=["创建项目评审/跟进工作项，完成一次责任流转并保留审计证据。"],
        )

    async def _notification_capability(self, tenant_id: UUID | None) -> CapabilityReadinessItem:
        preferences = await self._count(NotificationPreference, tenant_id)
        unacknowledged_required = await self._count(
            UserNotification,
            tenant_id,
            UserNotification.ack_required.is_(True),
            UserNotification.acknowledged_at.is_(None),
            UserNotification.archived_at.is_(None),
        )
        escalated = await self._count(
            UserNotification,
            tenant_id,
            UserNotification.escalation_level > 0,
            UserNotification.acknowledged_at.is_(None),
            UserNotification.archived_at.is_(None),
        )
        notification_events = await self._count(NotificationEvent, tenant_id)
        sent_events = await self._count(NotificationEvent, tenant_id, NotificationEvent.status == "sent")
        failed_events = await self._count(NotificationEvent, tenant_id, NotificationEvent.status == "failed")
        evidence = {
            "preference_count": preferences,
            "unacknowledged_required_notification_count": unacknowledged_required,
            "escalated_notification_count": escalated,
            "notification_event_count": notification_events,
            "sent_notification_event_count": sent_events,
            "failed_notification_event_count": failed_events,
        }
        if preferences > 0 and sent_events > 0 and unacknowledged_required == 0 and escalated == 0 and failed_events == 0:
            return self._item(
                "notification_alert_handling",
                "通知确认与告警投递",
                "ready",
                95,
                "通知偏好、投递记录和确认闭环均存在，且没有失败或升级未处理通知。",
                evidence,
            )
        if escalated > 0 or failed_events > 0:
            return self._item(
                "notification_alert_handling",
                "通知确认与告警投递",
                "blocked",
                25,
                "存在投递失败或升级未处理通知，生产告警闭环不可视为可用。",
                evidence,
                blockers=[
                    *([] if escalated == 0 else ["存在升级未处理通知。"]),
                    *([] if failed_events == 0 else ["存在失败通知投递。"]),
                ],
                recommended_actions=["处理升级通知并重试失败投递，确认通知链路恢复正常。"],
            )
        if preferences > 0 or notification_events > 0 or unacknowledged_required > 0:
            return self._item(
                "notification_alert_handling",
                "通知确认与告警投递",
                "degraded",
                65,
                "通知链路已有部分证据，但偏好、成功投递或确认闭环尚不完整。",
                evidence,
                blockers=["缺少通知偏好、成功投递记录或待确认通知尚未清零。"],
                recommended_actions=["补齐通知偏好，发送一次系统通知并完成需要确认的通知。"],
            )
        return self._item(
            "notification_alert_handling",
            "通知确认与告警投递",
            "blocked",
            25,
            "没有通知偏好、成功投递或确认证据，告警触达和处理闭环不可验证。",
            evidence,
            blockers=["缺少通知偏好。", "缺少成功通知投递记录。"],
            recommended_actions=["初始化通知偏好并产生一次已发送、已确认的系统通知。"],
        )

    async def _export_capability(self, tenant_id: UUID | None) -> CapabilityReadinessItem:
        export_jobs = await self._count(ExportJob, tenant_id)
        completed_exports = await self._count(
            ExportJob,
            tenant_id,
            ExportJob.status == ExportStatus.COMPLETED.value,
        )
        documents = await self._count(Document, tenant_id)
        evidence = {
            "export_job_count": export_jobs,
            "completed_export_count": completed_exports,
            "document_count": documents,
        }
        if completed_exports > 0:
            return self._item(
                "export_release",
                "导出与交付发布",
                "ready",
                90,
                "已有成功导出记录，可证明交付物发布链路可运行。",
                evidence,
            )
        if documents > 0:
            return self._item(
                "export_release",
                "导出与交付发布",
                "degraded",
                65,
                "已有文档资产，但尚无成功导出证据。",
                evidence,
                blockers=["缺少成功导出记录。"],
                recommended_actions=["选择一份非 placeholder 文档执行 Word/Markdown/PPTX 导出验证。"],
            )
        return self._item(
            "export_release",
            "导出与交付发布",
            "blocked",
            30,
            "缺少可导出的文档资产，交付发布链路不可验证。",
            evidence,
            blockers=["缺少文档资产。"],
            recommended_actions=["先完成一份项目文档，再执行导出验证。"],
        )

    async def _team_capability(self, tenant_id: UUID | None) -> CapabilityReadinessItem:
        active_users = await self._count(User, tenant_id, User.is_active.is_(True))
        roles = await self._count(Role, tenant_id)
        audit_logs = await self._count(AuditLog, tenant_id)
        policies = await self._count(Policy, tenant_id)
        field_permissions = await self._count(FieldPermission, tenant_id)
        evidence = {
            "active_user_count": active_users,
            "role_count": roles,
            "audit_log_count": audit_logs,
            "policy_count": policies,
            "field_permission_count": field_permissions,
        }
        has_access_model = active_users > 0 and roles > 0 and policies > 0 and field_permissions > 0
        if has_access_model and audit_logs > 0:
            return self._item(
                "team_access",
                "团队权限与审计",
                "ready",
                95,
                "团队用户、角色和审计证据均已存在，可支撑租户级权限治理。",
                evidence,
            )
        if has_access_model:
            return self._item(
                "team_access",
                "团队权限与审计",
                "degraded",
                70,
                "团队和角色已配置，但审计证据不足，权限操作闭环仍需验证。",
                evidence,
                blockers=["缺少权限或关键操作审计记录。"],
                recommended_actions=["在团队权限中心完成一次成员、角色或 API Key 操作，并检查审计日志。"],
            )
        return self._item(
            "team_access",
            "团队权限与审计",
            "blocked",
            30,
            "团队权限缺少活跃用户或角色配置，无法证明多用户协作可用。",
            evidence,
            blockers=[
                *([] if active_users else ["缺少活跃用户。"]),
                *([] if roles else ["缺少角色权限配置。"]),
            ],
            recommended_actions=["进入团队权限中心补齐用户、角色和审计验证。"],
        )

    async def _ops_capability(self, tenant_id: UUID | None) -> CapabilityReadinessItem:
        metric_events = await self._count(MetricEvent, tenant_id)
        quota_usages = await self._count(QuotaUsage, tenant_id)
        alert_rules = await self._count(AlertRule, tenant_id, AlertRule.is_active.is_(True))
        evidence = {
            "metric_event_count": metric_events,
            "quota_usage_count": quota_usages,
            "active_alert_rule_count": alert_rules,
        }
        if metric_events > 0 and quota_usages > 0 and alert_rules > 0:
            return self._item(
                "ops_observability",
                "运维监控与配额",
                "ready",
                95,
                "指标、配额和告警规则均已存在，可支撑生产运行监控。",
                evidence,
            )
        if metric_events > 0 or quota_usages > 0:
            return self._item(
                "ops_observability",
                "运维监控与配额",
                "degraded",
                65,
                "已有部分运行指标或配额数据，但告警/监控闭环尚未完整。",
                evidence,
                blockers=["缺少完整指标、配额或告警规则证据。"],
                recommended_actions=["在运维监控中确认健康、配额和告警规则，并执行一次运行巡检。"],
            )
        return self._item(
            "ops_observability",
            "运维监控与配额",
            "blocked",
            25,
            "缺少运行指标和配额证据，无法判断生产系统是否可持续运行。",
            evidence,
            blockers=["缺少运行指标。", "缺少配额使用记录。"],
            recommended_actions=["进入运维监控生成指标、配置配额并建立告警规则。"],
        )

    def _item(
        self,
        key: str,
        label: str,
        status: str,
        score: int,
        summary: str,
        evidence: dict[str, Any],
        blockers: list[str] | None = None,
        recommended_actions: list[str] | None = None,
    ) -> CapabilityReadinessItem:
        return CapabilityReadinessItem(
            key=key,
            label=label,
            status=status,
            score=score,
            summary=summary,
            evidence=evidence,
            blockers=blockers or [],
            recommended_actions=recommended_actions or [],
        )

    def _has_integration_endpoint(self, config: dict[str, Any]) -> bool:
        for key in ("endpoint", "base_url", "url", "server_url", "api_url", "runtime_ref", "managed_runtime_ref"):
            value = config.get(key)
            if isinstance(value, str) and value.strip():
                return True
        return False

    async def _active_workflow_version_count(self, tenant_id: UUID | None) -> int:
        stmt = (
            select(func.count(WorkflowVersion.id))
            .join(
                WorkflowDefinition,
                WorkflowVersion.workflow_definition_id == WorkflowDefinition.id,
            )
            .where(
                WorkflowVersion.is_active == 1,
                WorkflowDefinition.is_active == 1,
                WorkflowDefinition.deleted_at.is_(None),
            )
        )
        if tenant_id is not None:
            stmt = stmt.where(WorkflowDefinition.tenant_id == tenant_id)
        result = await self.db.execute(stmt)
        return int(result.scalar_one_or_none() or 0)
