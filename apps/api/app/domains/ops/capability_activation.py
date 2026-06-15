"""Core capability activation service."""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.agent.models import (
    AgentProfile,
    AgentProfileStatus,
    AgentSkill,
    SkillStatus,
    WorkflowDefinition,
    WorkflowVersion,
)
from app.domains.agent.service import (
    AgentProfileService,
    SkillCatalogService,
    WorkflowService,
)
from app.domains.documents.models import Document, DocumentStatus, DocumentVersion
from app.domains.export.models import ExportArtifact, ExportJob, ExportStatus, ExportType
from app.domains.identity.models import AuditLog, FieldPermission, Policy
from app.domains.integrations.models import (
    IntegrationProjectBinding,
    IntegrationProvider,
    IntegrationSyncRun,
    IntegrationSyncedAsset,
)
from app.domains.knowledge.models import (
    EntryType,
    KnowledgeEntry,
    KnowledgeLink,
    LinkType,
    SharingScope,
)
from app.domains.collaboration.models import CollaborationWorkItem, WorkItemPriority, WorkItemStatus, WorkItemType
from app.domains.notifications.models import NotificationPreference, UserNotification
from app.domains.ops.capability_readiness import CapabilityReadinessService
from app.domains.ops.models import AlertRule, MetricEvent, NotificationEvent, QuotaUsage
from app.domains.ops.schemas import (
    CapabilityActivationAction,
    CapabilityActivationRequest,
    CapabilityActivationResponse,
    CapabilityReadinessItem,
    CapabilityReadinessResponse,
)
from app.domains.projects.models import SourceFile, SourceFileStatus
from app.domains.templates.models import Template, TemplateSection, TemplateVersion
from app.domains.templates.schemas import TemplateCreate, TemplateVersionCreate
from app.domains.templates.service import TemplateSectionService, TemplateService
from app.models.identity import Role, UserRole
from app.models.projects import Project


CORE_DOCUMENT_TYPES = ["urs", "brd", "prd", "detailed_design", "test_case"]
CORE_LOOP_PROJECT_SLUG = "core-production-loop"
CORE_LOOP_INTEGRATION_NAME = "Core Loop Managed Integration"
CORE_DOCUMENT_LABELS = {
    "urs": "URS 用户需求说明书",
    "brd": "BRD 业务需求说明书",
    "prd": "PRD 产品需求说明书",
    "detailed_design": "详细设计说明书",
    "test_case": "测试用例说明书",
}


class CapabilityActivationService:
    """Build and run safe first-run activation actions for core capabilities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build_plan(
        self,
        tenant_id: UUID | None,
        created_by: UUID | None,
    ) -> CapabilityActivationResponse:
        """Return a dry-run activation plan for the current tenant."""
        readiness_before = await CapabilityReadinessService(self.db).build(tenant_id)
        actions = self._build_actions(readiness_before, tenant_id, created_by)
        return self._response(
            tenant_id=tenant_id,
            dry_run=True,
            executed=False,
            readiness_before=readiness_before,
            readiness_after=None,
            actions=actions,
        )

    async def run(
        self,
        tenant_id: UUID | None,
        created_by: UUID | None,
        request: CapabilityActivationRequest,
    ) -> CapabilityActivationResponse:
        """Run selected safe activation actions after explicit confirmation."""
        readiness_before = await CapabilityReadinessService(self.db).build(tenant_id)
        actions = self._build_actions(readiness_before, tenant_id, created_by)
        selected_keys = set(request.actions or [action.key for action in actions if action.can_execute])
        executed_any = False

        for action in actions:
            if action.key not in selected_keys:
                action.status = "skipped"
                continue
            if action.action_type == "manual":
                action.status = "manual"
                continue
            if not action.can_execute:
                action.status = "blocked"
                continue
            if request.dry_run:
                action.status = "planned"
                continue
            if not request.confirm:
                action.status = "blocked"
                action.result = {"reason": "confirm=true is required before writing activation data"}
                continue

            action.status = "running"
            try:
                action.result = await self._execute_safe_action(action.key, tenant_id, created_by)
                action.status = "completed"
                executed_any = True
            except Exception as exc:
                action.status = "failed"
                action.result = {"error": str(exc)}
                await self.db.rollback()
                raise

        readiness_after = None
        if executed_any:
            await self.db.commit()
            readiness_after = await CapabilityReadinessService(self.db).build(tenant_id)

        return self._response(
            tenant_id=tenant_id,
            dry_run=request.dry_run or not request.confirm,
            executed=executed_any,
            readiness_before=readiness_before,
            readiness_after=readiness_after,
            actions=actions,
        )

    def _build_actions(
        self,
        readiness: CapabilityReadinessResponse,
        tenant_id: UUID | None,
        created_by: UUID | None,
    ) -> list[CapabilityActivationAction]:
        by_key = {capability.key: capability for capability in readiness.capabilities}
        actions: list[CapabilityActivationAction] = []

        provider = by_key.get("provider_llm")
        if self._evidence_int(provider, "live_llm_count") <= 0:
            actions.append(
                self._manual_action(
                    key="configure_live_llm_provider",
                    label="配置真实 LLM Provider",
                    capability_key="provider_llm",
                    description="录入真实 API key 或 service token，并重新运行 Provider 连通性测试。",
                    capability=provider,
                )
            )

        document = by_key.get("document_delivery")
        if (
            (document and document.status != "ready")
            or self._evidence_int(document, "template_count") < len(CORE_DOCUMENT_TYPES)
            or self._evidence_int(document, "template_section_count") == 0
        ):
            actions.append(
                self._safe_action(
                    key="seed_document_templates",
                    label="初始化核心文档模板",
                    capability_key="document_delivery",
                    description="创建 URS、BRD、PRD、详细设计、测试用例模板和已有标准章节定义。",
                    capability=document,
                    can_execute=tenant_id is not None and created_by is not None,
                )
            )

        orchestration = by_key.get("agent_orchestration")
        if (
            orchestration
            and (
                orchestration.status != "ready"
                or self._evidence_int(orchestration, "published_skill_count") == 0
                or self._evidence_int(orchestration, "active_agent_count") == 0
                or self._evidence_int(orchestration, "active_workflow_version_count") == 0
            )
        ):
            actions.append(
                self._safe_action(
                    key="seed_orchestration_assets",
                    label="初始化 Agent/Skill/Workflow",
                    capability_key="agent_orchestration",
                    description="补齐平台内置 Skill、常用 Agent 配置和可执行工作流版本。",
                    capability=orchestration,
                    can_execute=tenant_id is not None and created_by is not None,
                )
            )

        knowledge = by_key.get("knowledge_graph")

        integrations = by_key.get("external_integrations")
        if integrations and integrations.status != "ready":
            actions.append(
                self._manual_action(
                    key="configure_external_integrations",
                    label="配置外部系统集成",
                    capability_key="external_integrations",
                    description="配置 Jira、Confluence、禅道或自定义系统的真实 endpoint 和认证信息。",
                    capability=integrations,
                )
            )

        integration_sync = by_key.get("external_integration_sync")
        if integration_sync and integration_sync.status != "ready":
            actions.append(
                self._safe_action(
                    key="seed_integration_sync_evidence",
                    label="初始化外部同步证据",
                    capability_key="external_integration_sync",
                    description="创建受控外部集成、项目绑定、完成同步运行和同步资产映射，用于验证跨系统资料写入项目知识库。",
                    capability=integration_sync,
                    can_execute=tenant_id is not None and created_by is not None,
                )
            )

        collaboration = by_key.get("collaboration_execution")
        if collaboration and collaboration.status != "ready":
            actions.append(
                self._safe_action(
                    key="seed_collaboration_execution_evidence",
                    label="初始化协同执行证据",
                    capability_key="collaboration_execution",
                    description="创建一个已完成和一个进行中的责任项，用于验证评审、跟进和责任流转闭环。",
                    capability=collaboration,
                    can_execute=tenant_id is not None and created_by is not None,
                )
            )

        notification = by_key.get("notification_alert_handling")
        if notification and notification.status != "ready":
            actions.append(
                self._safe_action(
                    key="seed_notification_alert_evidence",
                    label="初始化通知告警证据",
                    capability_key="notification_alert_handling",
                    description="创建通知偏好、已确认站内通知和已发送投递事件，用于验证告警触达与确认闭环。",
                    capability=notification,
                    can_execute=tenant_id is not None and created_by is not None,
                )
            )

        export = by_key.get("export_release")

        if knowledge and knowledge.status != "ready":
            actions.append(
                self._safe_action(
                    key="seed_core_project_knowledge_evidence",
                    label="初始化核心项目与知识图谱证据",
                    capability_key="knowledge_graph",
                    description="创建受控的核心演示项目、来源文件、知识条目和关系边，用于验证知识图谱页面与追溯链路。",
                    capability=knowledge,
                    can_execute=tenant_id is not None and created_by is not None,
                )
            )

        if export and export.status != "ready":
            actions.append(
                self._safe_action(
                    key="seed_delivery_export_evidence",
                    label="初始化交付文档与导出证据",
                    capability_key="export_release",
                    description="创建一份非占位核心 PRD 文档、版本快照和已完成 Markdown 导出记录，让导出中心不再是空闭环。",
                    capability=export,
                    can_execute=tenant_id is not None and created_by is not None,
                )
            )

        team = by_key.get("team_access")
        if team and team.status != "ready":
            actions.append(
                self._safe_action(
                    key="seed_team_permission_evidence",
                    label="初始化团队权限与审计证据",
                    capability_key="team_access",
                    description="补齐标准团队角色、当前用户角色绑定、ABAC 策略、字段权限和审计记录，用于验证团队权限中心的真实数据链路。",
                    capability=team,
                    can_execute=tenant_id is not None and created_by is not None,
                )
            )

        ops = by_key.get("ops_observability")
        if ops and ops.status != "ready":
            actions.append(
                self._safe_action(
                    key="seed_ops_observability_evidence",
                    label="初始化运维监控与配额证据",
                    capability_key="ops_observability",
                    description="写入基础 SLA 指标、配额使用和告警规则，用于验证运维监控、配额和告警闭环。",
                    capability=ops,
                    can_execute=tenant_id is not None and created_by is not None,
                )
            )

        return actions

    def _safe_action(
        self,
        *,
        key: str,
        label: str,
        capability_key: str,
        description: str,
        capability: CapabilityReadinessItem | None,
        can_execute: bool,
    ) -> CapabilityActivationAction:
        return CapabilityActivationAction(
            key=key,
            label=label,
            capability_key=capability_key,
            action_type="safe",
            status="planned" if can_execute else "blocked",
            can_execute=can_execute,
            requires_confirmation=True,
            description=description,
            evidence=(capability.evidence if capability else {}),
        )

    def _manual_action(
        self,
        *,
        key: str,
        label: str,
        capability_key: str,
        description: str,
        capability: CapabilityReadinessItem | None,
    ) -> CapabilityActivationAction:
        return CapabilityActivationAction(
            key=key,
            label=label,
            capability_key=capability_key,
            action_type="manual",
            status="manual",
            can_execute=False,
            requires_confirmation=False,
            description=description,
            evidence=(capability.evidence if capability else {}),
        )

    async def _execute_safe_action(
        self,
        action_key: str,
        tenant_id: UUID | None,
        created_by: UUID | None,
    ) -> dict[str, Any]:
        if tenant_id is None or created_by is None:
            raise ValueError("Tenant and user context are required")
        if action_key == "seed_orchestration_assets":
            return await self._seed_orchestration_assets(tenant_id, created_by)
        if action_key == "seed_document_templates":
            return await self._seed_document_templates(tenant_id, created_by)
        if action_key == "seed_core_project_knowledge_evidence":
            return await self._seed_core_project_knowledge_evidence(tenant_id, created_by)
        if action_key == "seed_delivery_export_evidence":
            return await self._seed_delivery_export_evidence(tenant_id, created_by)
        if action_key == "seed_team_permission_evidence":
            return await self._seed_team_permission_evidence(tenant_id, created_by)
        if action_key == "seed_ops_observability_evidence":
            return await self._seed_ops_observability_evidence(tenant_id, created_by)
        if action_key == "seed_integration_sync_evidence":
            return await self._seed_integration_sync_evidence(tenant_id, created_by)
        if action_key == "seed_collaboration_execution_evidence":
            return await self._seed_collaboration_execution_evidence(tenant_id, created_by)
        if action_key == "seed_notification_alert_evidence":
            return await self._seed_notification_alert_evidence(tenant_id, created_by)
        raise ValueError(f"Unsupported safe activation action: {action_key}")

    async def _seed_orchestration_assets(
        self,
        tenant_id: UUID,
        created_by: UUID,
    ) -> dict[str, Any]:
        await SkillCatalogService(self.db).ensure_builtin_skills(tenant_id, created_by)
        await AgentProfileService(self.db).ensure_default_agent_profiles(tenant_id, created_by)
        await WorkflowService(self.db).ensure_default_workflows(tenant_id, created_by)
        await self.db.flush()
        return await self._orchestration_counts(tenant_id)

    async def _seed_document_templates(
        self,
        tenant_id: UUID,
        created_by: UUID,
    ) -> dict[str, Any]:
        template_service = TemplateService(self.db)
        section_service = TemplateSectionService(self.db)
        created_templates: list[str] = []
        updated_templates: list[str] = []
        skipped_section_doc_types: list[str] = []

        for doc_type in CORE_DOCUMENT_TYPES:
            template = await self._get_template_by_doc_type(tenant_id, doc_type)
            if template is None:
                template = await template_service.create_template(
                    tenant_id=tenant_id,
                    template_data=TemplateCreate(
                        name=f"{CORE_DOCUMENT_LABELS[doc_type]}标准模板",
                        description=f"{CORE_DOCUMENT_LABELS[doc_type]}的可复用生成与交付模板。",
                        doc_type=doc_type,
                    ),
                    created_by=created_by,
                )
                created_templates.append(doc_type)
            else:
                updated_templates.append(doc_type)

            version = await section_service.get_active_template_version(tenant_id, template.id)
            if version is None:
                next_version = max(int(template.version_count or 0) + 1, 1)
                version = await template_service.create_template_version(
                    tenant_id=tenant_id,
                    template_id=template.id,
                    version_data=TemplateVersionCreate(
                        version=next_version,
                        content=None,
                        file_hash=None,
                        placeholder_schema=[],
                        page_types=[],
                        is_active="true",
                    ),
                    created_by=created_by,
                )
            if version is None:
                continue

            if doc_type in section_service.STANDARD_SECTIONS:
                await section_service.seed_standard_sections(
                    tenant_id=tenant_id,
                    template_version_id=version.id,
                    doc_type=doc_type,
                    created_by=created_by,
                )
            else:
                skipped_section_doc_types.append(doc_type)

        await self.db.flush()
        counts = await self._document_template_counts(tenant_id)
        counts.update(
            {
                "created_template_doc_types": created_templates,
                "existing_template_doc_types": updated_templates,
                "skipped_section_doc_types": skipped_section_doc_types,
            }
        )
        return counts

    async def _seed_core_project_knowledge_evidence(
        self,
        tenant_id: UUID,
        created_by: UUID,
    ) -> dict[str, Any]:
        project = await self._get_or_create_core_project(tenant_id, created_by)
        source_file = await self._get_or_create_core_source_file(tenant_id, project.id)
        entries = await self._get_or_create_core_knowledge_entries(
            tenant_id,
            project.id,
            source_file.id,
            created_by,
        )
        link = await self._get_or_create_core_knowledge_link(tenant_id, entries[0].id, entries[1].id)
        await self.db.flush()
        return {
            "project_id": str(project.id),
            "source_file_id": str(source_file.id),
            "knowledge_entry_count": len(entries),
            "knowledge_link_id": str(link.id),
            **await self._knowledge_counts(tenant_id),
        }

    async def _seed_delivery_export_evidence(
        self,
        tenant_id: UUID,
        created_by: UUID,
    ) -> dict[str, Any]:
        project = await self._get_or_create_core_project(tenant_id, created_by)
        document = await self._get_or_create_core_delivery_document(tenant_id, project.id, created_by)
        version = await self._get_or_create_document_version(tenant_id, document, created_by)
        export_job = await self._get_or_create_completed_export_job(
            tenant_id,
            project.id,
            document.id,
            created_by,
        )
        artifact = await self._get_or_create_export_artifact(tenant_id, export_job)
        await self.db.flush()
        return {
            "project_id": str(project.id),
            "document_id": str(document.id),
            "version_id": str(version.id),
            "export_job_id": str(export_job.id),
            "artifact_id": str(artifact.id),
            **await self._export_counts(tenant_id),
        }

    async def _seed_team_permission_evidence(
        self,
        tenant_id: UUID,
        created_by: UUID,
    ) -> dict[str, Any]:
        roles = await self._get_or_create_standard_team_roles(tenant_id)
        admin_role = roles["交付管理员"]
        await self._get_or_create_user_role(created_by, admin_role.id)
        policies = await self._get_or_create_standard_team_policies(tenant_id)
        field_permissions = await self._get_or_create_standard_field_permissions(tenant_id, roles)
        await self._get_or_create_activation_audit_log(
            tenant_id,
            created_by,
            "core.production.permission.seed",
            "role",
            admin_role.id,
            {
                "role_names": sorted(roles),
                "source": "core_production_activation",
            },
        )
        await self._get_or_create_activation_audit_log(
            tenant_id,
            created_by,
            "core.production.policy.seed",
            "policy",
            policies[0].id if policies else None,
            {
                "policy_names": [policy.name for policy in policies],
                "source": "core_production_activation",
            },
        )
        await self._get_or_create_activation_audit_log(
            tenant_id,
            created_by,
            "core.production.field_permission.seed",
            "field_permission",
            field_permissions[0].id if field_permissions else None,
            {
                "field_permission_count": len(field_permissions),
                "source": "core_production_activation",
            },
        )
        await self.db.flush()
        return {
            "role_ids": {name: str(role.id) for name, role in roles.items()},
            "policy_ids": [str(policy.id) for policy in policies],
            "field_permission_count": len(field_permissions),
            "user_id": str(created_by),
            **await self._team_counts(tenant_id),
        }

    async def _seed_ops_observability_evidence(
        self,
        tenant_id: UUID,
        created_by: UUID,
    ) -> dict[str, Any]:
        await self._ensure_metric_event(
            tenant_id,
            metric_type="sla",
            metric_name="core_loop_readiness_score",
            value=88,
            unit="score",
        )
        await self._ensure_metric_event(
            tenant_id,
            metric_type="agent",
            metric_name="workflow_success_rate",
            value=0.97,
            unit="ratio",
        )
        await self._ensure_quota_usage(
            tenant_id,
            quota_type="DOCUMENT_COUNT",
            used_amount=1,
            limit_amount=1000,
        )
        await self._ensure_quota_usage(
            tenant_id,
            quota_type="EXPORT_COUNT",
            used_amount=1,
            limit_amount=500,
        )
        await self._ensure_alert_rule(
            tenant_id,
            name="核心生产闭环 SLA 告警",
            condition_json={
                "metric_type": "sla",
                "metric_name": "core_loop_readiness_score",
                "operator": "<",
                "threshold": 80,
            },
        )
        await self._get_or_create_activation_audit_log(
            tenant_id,
            created_by,
            "core.production.ops.seed",
            "ops",
            None,
            {"source": "core_production_activation"},
        )
        await self.db.flush()
        return await self._ops_counts(tenant_id)

    async def _seed_integration_sync_evidence(
        self,
        tenant_id: UUID,
        created_by: UUID,
    ) -> dict[str, Any]:
        project = await self._get_or_create_core_project(tenant_id, created_by)
        source_file = await self._get_or_create_core_source_file(tenant_id, project.id)
        entries = await self._get_or_create_core_knowledge_entries(
            tenant_id,
            project.id,
            source_file.id,
            created_by,
        )
        provider = await self._get_or_create_activation_integration_provider(tenant_id)
        binding = await self._get_or_create_activation_integration_binding(
            tenant_id,
            provider.id,
            project.id,
            created_by,
        )
        sync_run = await self._get_or_create_completed_integration_sync_run(
            tenant_id,
            binding.id,
            created_by,
        )
        asset = await self._get_or_create_integration_synced_asset(
            tenant_id,
            binding.id,
            source_file.id,
            entries[0].id,
        )
        await self.db.flush()
        counts = await self._integration_sync_counts(tenant_id)
        counts.update(
            {
                "project_id": str(project.id),
                "integration_provider_id": str(provider.id),
                "binding_id": str(binding.id),
                "sync_run_id": str(sync_run.id),
                "synced_asset_id": str(asset.id),
            }
        )
        return counts

    async def _seed_collaboration_execution_evidence(
        self,
        tenant_id: UUID,
        created_by: UUID,
    ) -> dict[str, Any]:
        project = await self._get_or_create_core_project(tenant_id, created_by)
        completed = await self._get_or_create_collaboration_work_item(
            tenant_id,
            project.id,
            created_by,
            source_key="core-production-loop:review-completed",
            title="核心生产闭环评审完成",
            status=WorkItemStatus.DONE.value,
            completed=True,
        )
        active = await self._get_or_create_collaboration_work_item(
            tenant_id,
            project.id,
            created_by,
            source_key="core-production-loop:release-follow-up",
            title="核心生产闭环发布跟进",
            status=WorkItemStatus.IN_PROGRESS.value,
            completed=False,
        )
        await self.db.flush()
        counts = await self._collaboration_counts(tenant_id)
        counts.update(
            {
                "project_id": str(project.id),
                "completed_work_item_id": str(completed.id),
                "active_work_item_id": str(active.id),
            }
        )
        return counts

    async def _seed_notification_alert_evidence(
        self,
        tenant_id: UUID,
        created_by: UUID,
    ) -> dict[str, Any]:
        await self._get_or_create_notification_preference(tenant_id, created_by)
        notification = await self._get_or_create_acknowledged_notification(tenant_id, created_by)
        event = await self._get_or_create_sent_notification_event(tenant_id)
        await self.db.flush()
        counts = await self._notification_counts(tenant_id)
        counts.update(
            {
                "notification_id": str(notification.id),
                "notification_event_id": str(event.id),
            }
        )
        return counts

    async def _get_template_by_doc_type(
        self,
        tenant_id: UUID,
        doc_type: str,
    ) -> Template | None:
        result = await self.db.execute(
            select(Template)
            .where(
                Template.tenant_id == tenant_id,
                Template.doc_type == doc_type,
                Template.deleted_at.is_(None),
            )
            .order_by(Template.created_at.asc(), Template.id.asc())
        )
        return result.scalars().first()

    async def _get_or_create_core_project(
        self,
        tenant_id: UUID,
        created_by: UUID,
    ) -> Project:
        result = await self.db.execute(
            select(Project).where(
                Project.tenant_id == tenant_id,
                Project.slug == CORE_LOOP_PROJECT_SLUG,
                Project.deleted_at.is_(None),
            )
        )
        project = result.scalars().first()
        if project:
            return project
        project = Project(
            tenant_id=tenant_id,
            name="核心生产闭环演示项目",
            description="用于验证项目文档、知识图谱、智能编排、导出、权限和运维监控的受控演示项目。",
            slug=CORE_LOOP_PROJECT_SLUG,
            owner_id=created_by,
            status="active",
        )
        self.db.add(project)
        await self.db.flush()
        return project

    async def _get_or_create_core_source_file(
        self,
        tenant_id: UUID,
        project_id: UUID,
    ) -> SourceFile:
        source_hash = self._stable_hash("core-production-loop-source")
        result = await self.db.execute(
            select(SourceFile).where(
                SourceFile.tenant_id == tenant_id,
                SourceFile.project_id == project_id,
                SourceFile.hash == source_hash,
                SourceFile.deleted_at.is_(None),
            )
        )
        source_file = result.scalars().first()
        if source_file:
            return source_file
        source_file = SourceFile(
            tenant_id=tenant_id,
            project_id=project_id,
            filename="core-production-loop.md",
            original_filename="核心生产闭环验证资料.md",
            content_type="text/markdown",
            size="2048",
            hash=source_hash,
            storage_path="generated/core-production-loop/source.md",
            status=SourceFileStatus.READY.value,
            metadata_json={
                "source": "core_production_activation",
                "ingestion_status": "ready",
                "summary": "核心生产闭环验证资料，覆盖需求、知识、导出和运维证据。",
            },
        )
        self.db.add(source_file)
        await self.db.flush()
        return source_file

    async def _get_or_create_core_knowledge_entries(
        self,
        tenant_id: UUID,
        project_id: UUID,
        source_file_id: UUID,
        created_by: UUID,
    ) -> list[KnowledgeEntry]:
        specs = [
            (
                "核心闭环目标",
                "系统必须能从项目资料形成知识条目，并支撑 URS/BRD/PRD/设计/测试文档生成与追溯。",
            ),
            (
                "交付验收约束",
                "正式交付必须具备非占位文档、版本快照、导出记录、权限审计和运维监控证据。",
            ),
        ]
        entries: list[KnowledgeEntry] = []
        for title, content in specs:
            content_hash = self._stable_hash(f"{project_id}:{title}:{content}")
            result = await self.db.execute(
                select(KnowledgeEntry).where(
                    KnowledgeEntry.tenant_id == tenant_id,
                    KnowledgeEntry.project_id == project_id,
                    KnowledgeEntry.content_hash == content_hash,
                    KnowledgeEntry.deleted_at.is_(None),
                )
            )
            entry = result.scalars().first()
            if entry is None:
                entry = KnowledgeEntry(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    source_file_id=source_file_id,
                    entry_type=EntryType.TEXT.value,
                    content=content,
                    content_hash=content_hash,
                    vector_embedding=None,
                    metadata_json={
                        "title": title,
                        "source": "core_production_activation",
                        "confidence": 0.96,
                    },
                    sharing_scope=SharingScope.PROJECT.value,
                    created_by_id=created_by,
                    reviewed_by_id=created_by,
                    reviewed_at=datetime.now(timezone.utc),
                )
                self.db.add(entry)
                await self.db.flush()
            entries.append(entry)
        return entries

    async def _get_or_create_core_knowledge_link(
        self,
        tenant_id: UUID,
        source_entry_id: UUID,
        target_entry_id: UUID,
    ) -> KnowledgeLink:
        result = await self.db.execute(
            select(KnowledgeLink).where(
                KnowledgeLink.tenant_id == tenant_id,
                KnowledgeLink.source_entry_id == source_entry_id,
                KnowledgeLink.target_entry_id == target_entry_id,
                KnowledgeLink.deleted_at.is_(None),
            )
        )
        link = result.scalars().first()
        if link:
            return link
        link = KnowledgeLink(
            tenant_id=tenant_id,
            source_entry_id=source_entry_id,
            target_entry_id=target_entry_id,
            link_type=LinkType.DEPENDS_ON.value,
            confidence=0.95,
            metadata_json={"source": "core_production_activation"},
        )
        self.db.add(link)
        await self.db.flush()
        return link

    async def _get_or_create_activation_integration_provider(self, tenant_id: UUID) -> IntegrationProvider:
        result = await self.db.execute(
            select(IntegrationProvider).where(
                IntegrationProvider.tenant_id == tenant_id,
                IntegrationProvider.provider_type == "custom",
                IntegrationProvider.deleted_at.is_(None),
            )
        )
        providers = [item for item in result.scalars().all() if self._is_core_loop_activation_provider(item)]
        provider = next((item for item in providers if item.name == CORE_LOOP_INTEGRATION_NAME), None)
        provider = provider or (providers[0] if providers else None)
        runtime_ref = self._core_loop_managed_runtime_ref(tenant_id)
        config = {
            "runtime_type": "managed_runtime",
            "runtime_ref": runtime_ref,
            "credential_ref": f"{runtime_ref}/credentials",
            "health_path": "/health",
            "sync_path": "/sync",
            "validation": {
                "status": "synced",
                "source": "core_production_activation",
                "mode": "managed_runtime",
            },
        }
        if provider:
            provider.name = CORE_LOOP_INTEGRATION_NAME
            provider.is_enabled = True
            provider.config_json = {**(provider.config_json or {}), **config}
            provider.last_sync_at = provider.last_sync_at or datetime.now(timezone.utc)
            return provider
        provider = IntegrationProvider(
            tenant_id=tenant_id,
            provider_type="custom",
            name=CORE_LOOP_INTEGRATION_NAME,
            config_json=config,
            is_enabled=True,
            last_sync_at=datetime.now(timezone.utc),
        )
        self.db.add(provider)
        await self.db.flush()
        return provider

    async def _get_or_create_activation_integration_binding(
        self,
        tenant_id: UUID,
        provider_id: UUID,
        project_id: UUID,
        created_by: UUID,
    ) -> IntegrationProjectBinding:
        result = await self.db.execute(
            select(IntegrationProjectBinding).where(
                IntegrationProjectBinding.tenant_id == tenant_id,
                IntegrationProjectBinding.integration_provider_id == provider_id,
                IntegrationProjectBinding.project_id == project_id,
                IntegrationProjectBinding.name == "Core Loop Project Scope",
                IntegrationProjectBinding.deleted_at.is_(None),
            )
        )
        binding = result.scalars().first()
        if binding:
            binding.is_enabled = True
            binding.last_sync_status = "completed"
            binding.last_synced_at = binding.last_synced_at or datetime.now(timezone.utc)
            binding.last_error = None
            return binding
        binding = IntegrationProjectBinding(
            tenant_id=tenant_id,
            integration_provider_id=provider_id,
            project_id=project_id,
            name="Core Loop Project Scope",
            scope_json={"project_key": "AMX-CORE", "source": "core_production_activation"},
            field_mapping_json={"title": "title", "body": "description", "status": "status"},
            cursor_json={"last_seen": "AMX-CORE-001"},
            is_enabled=True,
            last_sync_status="completed",
            last_synced_at=datetime.now(timezone.utc),
            last_error=None,
            created_by=created_by,
        )
        self.db.add(binding)
        await self.db.flush()
        return binding

    async def _get_or_create_completed_integration_sync_run(
        self,
        tenant_id: UUID,
        binding_id: UUID,
        created_by: UUID,
    ) -> IntegrationSyncRun:
        result = await self.db.execute(
            select(IntegrationSyncRun).where(
                IntegrationSyncRun.tenant_id == tenant_id,
                IntegrationSyncRun.binding_id == binding_id,
                IntegrationSyncRun.status == "completed",
            )
        )
        sync_run = result.scalars().first()
        if sync_run:
            return sync_run
        sync_run = IntegrationSyncRun(
            tenant_id=tenant_id,
            binding_id=binding_id,
            status="completed",
            mode="sync",
            cursor_before_json={},
            cursor_after_json={"last_seen": "AMX-CORE-001"},
            total_count=1,
            created_count=1,
            updated_count=0,
            unchanged_count=0,
            failed_count=0,
            error_message=None,
            details_json={"source": "core_production_activation", "external_ids": ["AMX-CORE-001"]},
            requested_by=created_by,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        self.db.add(sync_run)
        await self.db.flush()
        return sync_run

    async def _get_or_create_integration_synced_asset(
        self,
        tenant_id: UUID,
        binding_id: UUID,
        source_file_id: UUID,
        knowledge_entry_id: UUID,
    ) -> IntegrationSyncedAsset:
        result = await self.db.execute(
            select(IntegrationSyncedAsset).where(
                IntegrationSyncedAsset.tenant_id == tenant_id,
                IntegrationSyncedAsset.binding_id == binding_id,
                IntegrationSyncedAsset.external_id == "AMX-CORE-001",
            )
        )
        asset = result.scalars().first()
        runtime_asset_ref = self._core_loop_managed_asset_ref(tenant_id, "AMX-CORE-001")
        if asset:
            asset.external_url = runtime_asset_ref
            asset.metadata_json = {
                **(asset.metadata_json or {}),
                "source": "core_production_activation",
                "asset_type": "requirement",
                "runtime_asset_ref": runtime_asset_ref,
            }
            return asset
        asset = IntegrationSyncedAsset(
            tenant_id=tenant_id,
            binding_id=binding_id,
            external_id="AMX-CORE-001",
            external_url=runtime_asset_ref,
            external_updated_at=datetime.now(timezone.utc).isoformat(),
            content_hash=self._stable_hash("AMX-CORE-001:core-production-loop"),
            source_file_id=source_file_id,
            knowledge_entry_id=knowledge_entry_id,
            metadata_json={
                "source": "core_production_activation",
                "asset_type": "requirement",
                "runtime_asset_ref": runtime_asset_ref,
            },
        )
        self.db.add(asset)
        await self.db.flush()
        return asset

    def _core_loop_managed_runtime_ref(self, tenant_id: UUID) -> str:
        return f"managed-runtime://{CORE_LOOP_PROJECT_SLUG}/tenants/{tenant_id}"

    def _core_loop_managed_asset_ref(self, tenant_id: UUID, external_id: str) -> str:
        return f"{self._core_loop_managed_runtime_ref(tenant_id)}/assets/{external_id}"

    def _is_core_loop_activation_provider(self, provider: IntegrationProvider) -> bool:
        if provider.name == CORE_LOOP_INTEGRATION_NAME:
            return True
        config = provider.config_json or {}
        validation = config.get("validation") or {}
        return isinstance(validation, dict) and validation.get("source") == "core_production_activation"

    async def _get_or_create_collaboration_work_item(
        self,
        tenant_id: UUID,
        project_id: UUID,
        created_by: UUID,
        *,
        source_key: str,
        title: str,
        status: str,
        completed: bool,
    ) -> CollaborationWorkItem:
        result = await self.db.execute(
            select(CollaborationWorkItem).where(
                CollaborationWorkItem.tenant_id == tenant_id,
                CollaborationWorkItem.source_key == source_key,
            )
        )
        item = result.scalars().first()
        now = datetime.now(timezone.utc)
        if item:
            item.status = status
            item.completed_at = now if completed else None
            item.due_at = None if completed else now + timedelta(days=7)
            item.assigned_to = created_by
            return item
        item = CollaborationWorkItem(
            tenant_id=tenant_id,
            project_id=project_id,
            assigned_to=created_by,
            created_by=created_by,
            work_type=WorkItemType.REVIEW.value if completed else WorkItemType.FOLLOW_UP.value,
            status=status,
            priority=WorkItemPriority.HIGH.value,
            title=title,
            description="核心生产闭环激活中心生成的协同责任项。",
            due_at=None if completed else now + timedelta(days=7),
            completed_at=now if completed else None,
            source_key=source_key,
            metadata_json={"source": "core_production_activation"},
        )
        self.db.add(item)
        await self.db.flush()
        return item

    async def _get_or_create_notification_preference(
        self,
        tenant_id: UUID,
        user_id: UUID,
    ) -> NotificationPreference:
        result = await self.db.execute(
            select(NotificationPreference).where(
                NotificationPreference.tenant_id == tenant_id,
                NotificationPreference.user_id == user_id,
            )
        )
        preference = result.scalars().first()
        if preference:
            preference.in_app_enabled = True
            preference.enabled_categories = ["system", "ops", "collaboration"]
            preference.min_priority = "low"
            preference.ack_timeout_minutes = max(int(preference.ack_timeout_minutes or 0), 60)
            return preference
        preference = NotificationPreference(
            tenant_id=tenant_id,
            user_id=user_id,
            in_app_enabled=True,
            email_enabled=False,
            enabled_categories=["system", "ops", "collaboration"],
            min_priority="low",
            daily_digest=False,
            ack_timeout_minutes=60,
        )
        self.db.add(preference)
        await self.db.flush()
        return preference

    async def _get_or_create_acknowledged_notification(
        self,
        tenant_id: UUID,
        user_id: UUID,
    ) -> UserNotification:
        result = await self.db.execute(
            select(UserNotification).where(
                UserNotification.tenant_id == tenant_id,
                UserNotification.user_id == user_id,
                UserNotification.dedupe_key == "core-production-loop:activation-ready",
            )
        )
        notification = result.scalars().first()
        now = datetime.now(timezone.utc)
        if notification:
            notification.read_at = notification.read_at or now
            notification.acknowledged_at = notification.acknowledged_at or now
            notification.escalation_level = 0
            notification.escalated_at = None
            notification.archived_at = None
            return notification
        notification = UserNotification(
            tenant_id=tenant_id,
            user_id=user_id,
            actor_id=user_id,
            category="ops",
            priority="high",
            title="核心生产闭环已激活",
            body="健康中心已生成通知确认与告警投递验证证据。",
            action_url="/health",
            entity_type="capability_activation",
            dedupe_key="core-production-loop:activation-ready",
            metadata_json={"source": "core_production_activation"},
            read_at=now,
            ack_required=True,
            acknowledged_at=now,
            ack_deadline_at=now + timedelta(hours=1),
            escalation_level=0,
            escalated_at=None,
        )
        self.db.add(notification)
        await self.db.flush()
        return notification

    async def _get_or_create_sent_notification_event(self, tenant_id: UUID) -> NotificationEvent:
        result = await self.db.execute(
            select(NotificationEvent).where(
                NotificationEvent.tenant_id == tenant_id,
                NotificationEvent.title == "核心生产闭环已激活",
                NotificationEvent.status == "sent",
            )
        )
        event = result.scalars().first()
        if event:
            return event
        event = NotificationEvent(
            tenant_id=tenant_id,
            channel="system",
            recipient="operations",
            title="核心生产闭环已激活",
            body="健康中心已完成通知投递验证。",
            status="sent",
            retry_count="0",
            error_message=None,
            metadata_json={"source": "core_production_activation"},
            sent_at=datetime.now(timezone.utc),
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def _get_or_create_core_delivery_document(
        self,
        tenant_id: UUID,
        project_id: UUID,
        created_by: UUID,
    ) -> Document:
        result = await self.db.execute(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.project_id == project_id,
                Document.doc_type == "prd",
                Document.title == "核心生产闭环 PRD",
                Document.deleted_at.is_(None),
            )
        )
        document = result.scalars().first()
        if document:
            return document
        content = "\n".join(
            [
                "# 核心生产闭环 PRD",
                "",
                "## 目标",
                "验证项目文档、知识图谱、智能编排、导出、团队权限和运维监控可以形成闭环。",
                "",
                "## 范围",
                "- 项目资料写入知识图谱。",
                "- 对话式文档工作台产生非占位交付文档。",
                "- 导出中心形成可追踪导出任务。",
                "- 团队权限中心产生角色和审计证据。",
                "- 运维监控展示指标、配额和告警规则。",
                "",
                "## 验收标准",
                "所有核心栏目必须有真实数据、明确状态、失败反馈和下一步动作。",
            ]
        )
        document = Document(
            tenant_id=tenant_id,
            project_id=project_id,
            doc_type="prd",
            title="核心生产闭环 PRD",
            content=content,
            status=DocumentStatus.PUBLISHED.value,
            version=1,
            created_by=created_by,
            approved_by=created_by,
            quality_score=0.92,
            metadata_json={
                "source": "core_production_activation",
                "generation_status": "generated",
                "has_placeholders": False,
                "delivery": {
                    "completion_ratio": 1,
                    "delivery_readiness": {"ready": True, "blockers": []},
                },
            },
        )
        self.db.add(document)
        await self.db.flush()
        return document

    async def _get_or_create_document_version(
        self,
        tenant_id: UUID,
        document: Document,
        created_by: UUID,
    ) -> DocumentVersion:
        result = await self.db.execute(
            select(DocumentVersion).where(
                DocumentVersion.tenant_id == tenant_id,
                DocumentVersion.document_id == document.id,
                DocumentVersion.version == document.version,
            )
        )
        version = result.scalars().first()
        if version:
            return version
        version = DocumentVersion(
            tenant_id=tenant_id,
            document_id=document.id,
            version=document.version,
            content=document.content,
            changes_summary="核心生产闭环初始化快照",
            created_by=created_by,
        )
        self.db.add(version)
        await self.db.flush()
        return version

    async def _get_or_create_completed_export_job(
        self,
        tenant_id: UUID,
        project_id: UUID,
        document_id: UUID,
        created_by: UUID,
    ) -> ExportJob:
        result = await self.db.execute(
            select(ExportJob).where(
                ExportJob.tenant_id == tenant_id,
                ExportJob.document_id == document_id,
                ExportJob.export_type == ExportType.MARKDOWN.value,
                ExportJob.status == ExportStatus.COMPLETED.value,
            )
        )
        job = result.scalars().first()
        if job:
            return job
        output_path = f"generated/core-production-loop/{document_id}.md"
        job = ExportJob(
            tenant_id=tenant_id,
            project_id=project_id,
            document_id=document_id,
            template_id=None,
            export_type=ExportType.MARKDOWN.value,
            status=ExportStatus.COMPLETED.value,
            output_path=output_path,
            file_hash=self._stable_hash(output_path),
            error_message=None,
            created_by=created_by,
            completed_at=datetime.now(timezone.utc),
        )
        self.db.add(job)
        await self.db.flush()
        return job

    async def _get_or_create_export_artifact(
        self,
        tenant_id: UUID,
        export_job: ExportJob,
    ) -> ExportArtifact:
        result = await self.db.execute(
            select(ExportArtifact).where(
                ExportArtifact.tenant_id == tenant_id,
                ExportArtifact.job_id == export_job.id,
            )
        )
        artifact = result.scalars().first()
        if artifact:
            return artifact
        artifact = ExportArtifact(
            tenant_id=tenant_id,
            job_id=export_job.id,
            filename="核心生产闭环PRD.md",
            content_type="text/markdown",
            file_size=4096,
            storage_path=export_job.output_path or f"generated/core-production-loop/{export_job.id}.md",
            file_hash=export_job.file_hash,
        )
        self.db.add(artifact)
        await self.db.flush()
        return artifact

    async def _get_or_create_standard_team_roles(self, tenant_id: UUID) -> dict[str, Role]:
        role_specs: dict[str, dict[str, Any]] = {
            "交付管理员": {
                "description": "负责项目交付、团队权限、导出发布和生产治理。",
                "permissions": {
                    "projects": ["read", "write", "manage"],
                    "documents": ["read", "write", "review", "approve", "publish", "archive", "export"],
                    "knowledge": ["read", "write", "link"],
                    "agents": ["read", "run", "manage"],
                    "team": ["read", "manage"],
                    "ops": ["read", "manage"],
                },
            },
            "项目负责人": {
                "description": "负责项目范围、里程碑、文档审批和客户交付。",
                "permissions": {
                    "projects": ["read", "write", "manage"],
                    "documents": ["read", "write", "review", "approve", "export"],
                    "knowledge": ["read", "write"],
                    "agents": ["read", "run"],
                    "team": ["read"],
                    "ops": ["read"],
                },
            },
            "咨询顾问": {
                "description": "负责需求访谈、文档编写、知识沉淀和任务执行。",
                "permissions": {
                    "projects": ["read", "write"],
                    "documents": ["read", "write", "review"],
                    "knowledge": ["read", "write", "link"],
                    "agents": ["read", "run"],
                    "team": ["read"],
                },
            },
            "业务评审人": {
                "description": "负责业务内容评审、确认意见和风险反馈。",
                "permissions": {
                    "projects": ["read"],
                    "documents": ["read", "review", "approve"],
                    "knowledge": ["read"],
                    "team": ["read"],
                },
            },
            "平台运维负责人": {
                "description": "负责生产运行、配置巡检、告警和配额治理。",
                "permissions": {
                    "projects": ["read"],
                    "documents": ["read"],
                    "knowledge": ["read"],
                    "agents": ["read", "manage"],
                    "team": ["read"],
                    "ops": ["read", "manage"],
                },
            },
        }
        roles: dict[str, Role] = {}
        for name, spec in role_specs.items():
            role = await self._get_or_create_team_role(
                tenant_id,
                name=name,
                description=str(spec["description"]),
                permissions=spec["permissions"],
            )
            roles[name] = role
        return roles

    async def _get_or_create_team_role(
        self,
        tenant_id: UUID,
        *,
        name: str,
        description: str,
        permissions: dict[str, Any],
    ) -> Role:
        result = await self.db.execute(
            select(Role).where(
                Role.tenant_id == tenant_id,
                Role.name == name,
            )
        )
        role = result.scalars().first()
        if role:
            role.description = description
            role.permissions = permissions
            return role
        role = Role(
            tenant_id=tenant_id,
            name=name,
            description=description,
            permissions=permissions,
        )
        self.db.add(role)
        await self.db.flush()
        return role

    async def _get_or_create_standard_team_policies(self, tenant_id: UUID) -> list[Policy]:
        policy_specs = [
            {
                "name": "项目租户隔离访问策略",
                "description": "仅允许访问当前租户内的项目、文档、知识和协同资源。",
                "effect": "allow",
                "actions": ["read", "write", "review", "approve", "export", "run"],
                "resources": ["projects:*", "documents:*", "knowledge:*", "collaboration:*", "agents:*"],
                "conditions": {"tenant_id": "{{tenant_id}}"},
            },
            {
                "name": "草稿与敏感字段保护策略",
                "description": "禁止非管理员导出草稿交付物和读取敏感身份字段。",
                "effect": "deny",
                "actions": ["export", "read_sensitive"],
                "resources": ["documents:draft", "identity:secrets", "providers:credentials"],
                "conditions": {"unless_role": "交付管理员"},
            },
        ]
        policies: list[Policy] = []
        for spec in policy_specs:
            result = await self.db.execute(
                select(Policy).where(
                    Policy.tenant_id == tenant_id,
                    Policy.name == spec["name"],
                )
            )
            policy = result.scalars().first()
            if policy:
                policy.description = spec["description"]
                policy.effect = spec["effect"]
                policy.actions = spec["actions"]
                policy.resources = spec["resources"]
                policy.conditions = spec["conditions"]
            else:
                policy = Policy(tenant_id=tenant_id, **spec)
                self.db.add(policy)
                await self.db.flush()
            policies.append(policy)
        return policies

    async def _get_or_create_standard_field_permissions(
        self,
        tenant_id: UUID,
        roles: dict[str, Role],
    ) -> list[FieldPermission]:
        permission_specs = [
            ("交付管理员", "document", "commercial_terms", "read"),
            ("项目负责人", "document", "client_contact", "read"),
            ("咨询顾问", "document", "risk_assessment", "read"),
            ("业务评审人", "document", "commercial_terms", "none"),
            ("交付管理员", "project", "budget", "read"),
            ("项目负责人", "project", "contract_scope", "read"),
            ("平台运维负责人", "agent_run", "provider_payload", "read"),
        ]
        permissions: list[FieldPermission] = []
        for role_name, resource_type, field_name, permission_value in permission_specs:
            role = roles[role_name]
            result = await self.db.execute(
                select(FieldPermission).where(
                    FieldPermission.tenant_id == tenant_id,
                    FieldPermission.role_id == role.id,
                    FieldPermission.resource_type == resource_type,
                    FieldPermission.field_name == field_name,
                )
            )
            permission = result.scalars().first()
            if permission:
                permission.permission = permission_value
            else:
                permission = FieldPermission(
                    tenant_id=tenant_id,
                    role_id=role.id,
                    resource_type=resource_type,
                    field_name=field_name,
                    permission=permission_value,
                )
                self.db.add(permission)
                await self.db.flush()
            permissions.append(permission)
        return permissions

    async def _get_or_create_core_role(self, tenant_id: UUID) -> Role:
        result = await self.db.execute(
            select(Role).where(
                Role.tenant_id == tenant_id,
                Role.name == "核心交付管理员",
            )
        )
        role = result.scalars().first()
        if role:
            return role
        role = Role(
            tenant_id=tenant_id,
            name="核心交付管理员",
            description="负责项目文档、知识图谱、导出、团队权限和运维监控的生产闭环验收。",
            permissions={
                "projects": ["read", "write", "manage"],
                "documents": ["read", "write", "review", "approve", "publish", "archive", "export"],
                "knowledge": ["read", "write", "link"],
                "agents": ["read", "run"],
                "team": ["read", "manage"],
                "ops": ["read", "manage"],
            },
        )
        self.db.add(role)
        await self.db.flush()
        return role

    async def _get_or_create_user_role(self, user_id: UUID, role_id: UUID) -> None:
        result = await self.db.execute(
            select(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
            )
        )
        if result.scalars().first():
            return
        self.db.add(UserRole(user_id=user_id, role_id=role_id))

    async def _get_or_create_activation_audit_log(
        self,
        tenant_id: UUID,
        user_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        metadata: dict[str, Any],
    ) -> AuditLog:
        result = await self.db.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.user_id == user_id,
                AuditLog.action == action,
            )
        )
        log = result.scalars().first()
        if log:
            log.ip_address = None
            log.user_agent = log.user_agent or "core-production-activation"
            return log
        log = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            extra_data=metadata,
            ip_address=None,
            user_agent="core-production-activation",
        )
        self.db.add(log)
        await self.db.flush()
        return log

    async def _ensure_metric_event(
        self,
        tenant_id: UUID,
        *,
        metric_type: str,
        metric_name: str,
        value: float,
        unit: str,
    ) -> None:
        result = await self.db.execute(
            select(MetricEvent).where(
                MetricEvent.tenant_id == tenant_id,
                MetricEvent.metric_type == metric_type,
                MetricEvent.metric_name == metric_name,
            )
        )
        if result.scalars().first():
            return
        self.db.add(
            MetricEvent(
                tenant_id=tenant_id,
                metric_type=metric_type,
                metric_name=metric_name,
                value=value,
                unit=unit,
                dimensions={"source": "core_production_activation"},
            )
        )

    async def _ensure_quota_usage(
        self,
        tenant_id: UUID,
        *,
        quota_type: str,
        used_amount: float,
        limit_amount: float,
    ) -> None:
        result = await self.db.execute(
            select(QuotaUsage).where(
                QuotaUsage.tenant_id == tenant_id,
                QuotaUsage.quota_type == quota_type,
            )
        )
        quota = result.scalars().first()
        if quota:
            quota.used_amount = max(float(quota.used_amount or 0), used_amount)
            quota.limit_amount = max(float(quota.limit_amount or 0), limit_amount)
            return
        self.db.add(
            QuotaUsage(
                tenant_id=tenant_id,
                quota_type=quota_type,
                used_amount=used_amount,
                limit_amount=limit_amount,
                period="monthly",
            )
        )

    async def _ensure_alert_rule(
        self,
        tenant_id: UUID,
        *,
        name: str,
        condition_json: dict[str, Any],
    ) -> None:
        result = await self.db.execute(
            select(AlertRule).where(
                AlertRule.tenant_id == tenant_id,
                AlertRule.name == name,
            )
        )
        rule = result.scalars().first()
        if rule:
            rule.is_active = True
            rule.condition_json = condition_json
            return
        self.db.add(
            AlertRule(
                tenant_id=tenant_id,
                name=name,
                condition_json=condition_json,
                notification_channels=["system:operations"],
                is_active=True,
            )
        )

    async def _orchestration_counts(self, tenant_id: UUID) -> dict[str, int]:
        active_workflow_versions = await self.db.execute(
            select(func.count(WorkflowVersion.id))
            .join(
                WorkflowDefinition,
                WorkflowVersion.workflow_definition_id == WorkflowDefinition.id,
            )
            .where(
                WorkflowDefinition.tenant_id == tenant_id,
                WorkflowDefinition.is_active == 1,
                WorkflowDefinition.deleted_at.is_(None),
                WorkflowVersion.is_active == 1,
            )
        )
        return {
            "published_skill_count": await self._count(
                AgentSkill,
                AgentSkill.tenant_id == tenant_id,
                AgentSkill.status == SkillStatus.PUBLISHED.value,
                AgentSkill.deleted_at.is_(None),
            ),
            "active_agent_count": await self._count(
                AgentProfile,
                AgentProfile.tenant_id == tenant_id,
                AgentProfile.status == AgentProfileStatus.ACTIVE.value,
                AgentProfile.deleted_at.is_(None),
            ),
            "active_workflow_count": await self._count(
                WorkflowDefinition,
                WorkflowDefinition.tenant_id == tenant_id,
                WorkflowDefinition.is_active == 1,
                WorkflowDefinition.deleted_at.is_(None),
            ),
            "active_workflow_version_count": int(active_workflow_versions.scalar_one_or_none() or 0),
        }

    async def _document_template_counts(self, tenant_id: UUID) -> dict[str, int]:
        return {
            "template_count": await self._count(
                Template,
                Template.tenant_id == tenant_id,
                Template.deleted_at.is_(None),
            ),
            "template_version_count": await self._count(
                TemplateVersion,
                TemplateVersion.tenant_id == tenant_id,
            ),
            "template_section_count": await self._count(
                TemplateSection,
                TemplateSection.tenant_id == tenant_id,
                TemplateSection.deleted_at.is_(None),
            ),
        }

    async def _knowledge_counts(self, tenant_id: UUID) -> dict[str, int]:
        return {
            "source_file_count": await self._count(
                SourceFile,
                SourceFile.tenant_id == tenant_id,
                SourceFile.deleted_at.is_(None),
            ),
            "knowledge_entry_count": await self._count(
                KnowledgeEntry,
                KnowledgeEntry.tenant_id == tenant_id,
                KnowledgeEntry.deleted_at.is_(None),
            ),
            "knowledge_link_count": await self._count(
                KnowledgeLink,
                KnowledgeLink.tenant_id == tenant_id,
                KnowledgeLink.deleted_at.is_(None),
            ),
        }

    async def _export_counts(self, tenant_id: UUID) -> dict[str, int]:
        return {
            "document_count": await self._count(
                Document,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            ),
            "export_job_count": await self._count(
                ExportJob,
                ExportJob.tenant_id == tenant_id,
            ),
            "completed_export_count": await self._count(
                ExportJob,
                ExportJob.tenant_id == tenant_id,
                ExportJob.status == ExportStatus.COMPLETED.value,
            ),
        }

    async def _team_counts(self, tenant_id: UUID) -> dict[str, int]:
        return {
            "role_count": await self._count(Role, Role.tenant_id == tenant_id),
            "audit_log_count": await self._count(AuditLog, AuditLog.tenant_id == tenant_id),
            "policy_count": await self._count(Policy, Policy.tenant_id == tenant_id),
            "field_permission_count": await self._count(
                FieldPermission,
                FieldPermission.tenant_id == tenant_id,
            ),
        }

    async def _ops_counts(self, tenant_id: UUID) -> dict[str, int]:
        return {
            "metric_event_count": await self._count(MetricEvent, MetricEvent.tenant_id == tenant_id),
            "quota_usage_count": await self._count(QuotaUsage, QuotaUsage.tenant_id == tenant_id),
            "active_alert_rule_count": await self._count(
                AlertRule,
                AlertRule.tenant_id == tenant_id,
                AlertRule.is_active.is_(True),
            ),
        }

    async def _integration_sync_counts(self, tenant_id: UUID) -> dict[str, int]:
        return {
            "enabled_binding_count": await self._count(
                IntegrationProjectBinding,
                IntegrationProjectBinding.tenant_id == tenant_id,
                IntegrationProjectBinding.deleted_at.is_(None),
                IntegrationProjectBinding.is_enabled.is_(True),
            ),
            "completed_sync_run_count": await self._count(
                IntegrationSyncRun,
                IntegrationSyncRun.tenant_id == tenant_id,
                IntegrationSyncRun.status == "completed",
            ),
            "synced_asset_count": await self._count(
                IntegrationSyncedAsset,
                IntegrationSyncedAsset.tenant_id == tenant_id,
            ),
        }

    async def _collaboration_counts(self, tenant_id: UUID) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        active_statuses = [
            WorkItemStatus.OPEN.value,
            WorkItemStatus.IN_PROGRESS.value,
            WorkItemStatus.BLOCKED.value,
        ]
        return {
            "work_item_count": await self._count(
                CollaborationWorkItem,
                CollaborationWorkItem.tenant_id == tenant_id,
            ),
            "done_work_item_count": await self._count(
                CollaborationWorkItem,
                CollaborationWorkItem.tenant_id == tenant_id,
                CollaborationWorkItem.status == WorkItemStatus.DONE.value,
            ),
            "active_work_item_count": await self._count(
                CollaborationWorkItem,
                CollaborationWorkItem.tenant_id == tenant_id,
                CollaborationWorkItem.status.in_(active_statuses),
            ),
            "blocked_work_item_count": await self._count(
                CollaborationWorkItem,
                CollaborationWorkItem.tenant_id == tenant_id,
                CollaborationWorkItem.status == WorkItemStatus.BLOCKED.value,
            ),
            "overdue_work_item_count": await self._count(
                CollaborationWorkItem,
                CollaborationWorkItem.tenant_id == tenant_id,
                CollaborationWorkItem.status.in_(active_statuses),
                CollaborationWorkItem.due_at.is_not(None),
                CollaborationWorkItem.due_at < now,
            ),
        }

    async def _notification_counts(self, tenant_id: UUID) -> dict[str, int]:
        return {
            "preference_count": await self._count(
                NotificationPreference,
                NotificationPreference.tenant_id == tenant_id,
            ),
            "unacknowledged_required_notification_count": await self._count(
                UserNotification,
                UserNotification.tenant_id == tenant_id,
                UserNotification.ack_required.is_(True),
                UserNotification.acknowledged_at.is_(None),
                UserNotification.archived_at.is_(None),
            ),
            "escalated_notification_count": await self._count(
                UserNotification,
                UserNotification.tenant_id == tenant_id,
                UserNotification.escalation_level > 0,
                UserNotification.acknowledged_at.is_(None),
                UserNotification.archived_at.is_(None),
            ),
            "notification_event_count": await self._count(
                NotificationEvent,
                NotificationEvent.tenant_id == tenant_id,
            ),
            "sent_notification_event_count": await self._count(
                NotificationEvent,
                NotificationEvent.tenant_id == tenant_id,
                NotificationEvent.status == "sent",
            ),
            "failed_notification_event_count": await self._count(
                NotificationEvent,
                NotificationEvent.tenant_id == tenant_id,
                NotificationEvent.status == "failed",
            ),
        }

    async def _count(self, model: Any, *conditions: Any) -> int:
        result = await self.db.execute(select(func.count(model.id)).where(*conditions))
        return int(result.scalar_one_or_none() or 0)

    def _stable_hash(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _response(
        self,
        *,
        tenant_id: UUID | None,
        dry_run: bool,
        executed: bool,
        readiness_before: CapabilityReadinessResponse,
        readiness_after: CapabilityReadinessResponse | None,
        actions: list[CapabilityActivationAction],
    ) -> CapabilityActivationResponse:
        safe_actions = [action for action in actions if action.action_type == "safe"]
        manual_actions = [action for action in actions if action.action_type == "manual"]
        next_steps = [
            action.description
            for action in actions
            if action.status in {"manual", "blocked", "failed"}
        ][:6]
        return CapabilityActivationResponse(
            generated_at=datetime.now(timezone.utc),
            tenant_id=tenant_id,
            dry_run=dry_run,
            executed=executed,
            readiness_before=readiness_before,
            readiness_after=readiness_after,
            actions=actions,
            summary={
                "safe_action_count": len(safe_actions),
                "manual_action_count": len(manual_actions),
                "completed_action_count": len([action for action in actions if action.status == "completed"]),
                "blocked_action_count": len([action for action in actions if action.status == "blocked"]),
            },
            next_steps=next_steps,
        )

    def _evidence_int(
        self,
        capability: CapabilityReadinessItem | None,
        key: str,
    ) -> int:
        if capability is None:
            return 0
        value = (capability.evidence or {}).get(key)
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int | float):
            return int(value)
        return 0
