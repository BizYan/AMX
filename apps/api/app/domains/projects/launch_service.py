"""Project launch blueprint catalog and idempotent initialization service."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.agent.service import WorkflowService
from app.domains.documents.models import Document, DocumentStatus, DocumentType
from app.domains.projects.models import ProjectLaunchPlan
from app.domains.projects.schemas import (
    ProjectCreate,
    ProjectLaunchBlueprint,
    ProjectLaunchCreate,
)
from app.domains.projects.service import ProjectService, ProjectSettingsService
from app.models.identity import User
from app.models.projects import Project, ProjectMember


DOCUMENT_LABELS = {
    "urs": "用户需求规格说明书",
    "brd": "业务需求文档",
    "prd": "产品需求文档",
    "detailed_design": "详细设计说明",
    "interface": "接口说明",
    "data_dictionary": "数据字典",
    "test_case": "测试用例",
}


@dataclass
class ProjectLaunchResult:
    """Service result containing the project and current launch plan."""

    project: Project
    plan: ProjectLaunchPlan


class ProjectLaunchService:
    """Create a project and idempotently initialize its delivery assets."""

    BLUEPRINTS = [
        ProjectLaunchBlueprint(
            key="consulting-discovery",
            name="咨询调研与需求澄清",
            description="用于访谈、现状调研、问题澄清和业务需求确认。",
            scenarios=["咨询调研", "需求澄清", "立项论证"],
            document_types=["urs", "brd"],
            workflow_template_ids=["brd-document-generation", "document-quality-assessment"],
            checks=["项目负责人已加入", "初始交付文档已规划", "推荐工作流已就绪"],
            next_actions=["导入调研资料", "启动需求澄清", "分派文档负责人"],
        ),
        ProjectLaunchBlueprint(
            key="product-delivery",
            name="产品需求到交付",
            description="覆盖用户需求、业务需求、产品设计、详细设计与测试验收。",
            scenarios=["产品建设", "业务系统交付", "功能迭代"],
            document_types=["urs", "brd", "prd", "detailed_design", "test_case"],
            workflow_template_ids=[
                "brd-document-generation",
                "document-quality-assessment",
                "human-approval-delivery-pipeline",
            ],
            checks=["项目负责人已加入", "核心交付链已规划", "质量和审批工作流已就绪"],
            next_actions=["导入需求资料", "开始对话式编写", "确认交付里程碑"],
        ),
        ProjectLaunchBlueprint(
            key="system-modernization",
            name="系统升级与迁移",
            description="覆盖现状评估、需求、设计、接口、数据和测试交付链。",
            scenarios=["遗留系统升级", "平台迁移", "架构现代化"],
            document_types=[
                "urs",
                "brd",
                "prd",
                "detailed_design",
                "interface",
                "data_dictionary",
                "test_case",
            ],
            workflow_template_ids=[
                "change-impact-governance",
                "parallel-quality-review",
                "human-approval-delivery-pipeline",
            ],
            checks=["项目负责人已加入", "迁移交付链已规划", "变更治理和审批工作流已就绪"],
            next_actions=["导入现状资料", "建立接口与数据清单", "启动变更影响分析"],
        ),
    ]

    def __init__(self, db: AsyncSession):
        self.db = db

    @classmethod
    def list_blueprints(cls) -> list[ProjectLaunchBlueprint]:
        return [item.model_copy(deep=True) for item in cls.BLUEPRINTS]

    @classmethod
    def get_blueprint(cls, key: str) -> ProjectLaunchBlueprint | None:
        return next((item.model_copy(deep=True) for item in cls.BLUEPRINTS if item.key == key), None)

    async def launch(
        self,
        *,
        tenant_id: UUID,
        created_by: UUID,
        data: ProjectLaunchCreate,
    ) -> ProjectLaunchResult:
        blueprint = self.get_blueprint(data.blueprint_key)
        if blueprint is None:
            raise ValueError("Project launch blueprint not found")

        document_types = data.document_types if data.document_types is not None else blueprint.document_types
        workflow_template_ids = (
            data.workflow_template_ids
            if data.workflow_template_ids is not None
            else blueprint.workflow_template_ids
        )
        await self._validate_configuration(
            tenant_id=tenant_id,
            member_ids=data.member_ids,
            document_types=document_types,
            workflow_template_ids=workflow_template_ids,
        )

        project = await ProjectService(self.db).create_project(
            ProjectCreate(
                name=data.name,
                description=data.description,
                slug=data.slug,
                status="active",
            ),
            tenant_id=tenant_id,
            owner_id=created_by,
        )
        plan = ProjectLaunchPlan(
            tenant_id=tenant_id,
            project_id=project.id,
            blueprint_key=blueprint.key,
            status="pending",
            config_json={
                "member_ids": [str(member_id) for member_id in data.member_ids],
                "document_types": document_types,
                "workflow_template_ids": workflow_template_ids,
                "project_settings": {
                    "launch_blueprint": blueprint.key,
                    "launch_status": "pending",
                },
            },
            checks_json=[],
            results_json={},
            created_by=created_by,
        )
        self.db.add(plan)
        await self.db.flush()
        return await self._execute(project=project, plan=plan, requested_by=created_by)

    async def get_plan(self, project_id: UUID, tenant_id: UUID) -> ProjectLaunchPlan | None:
        return await self.db.scalar(
            select(ProjectLaunchPlan).where(
                ProjectLaunchPlan.project_id == project_id,
                ProjectLaunchPlan.tenant_id == tenant_id,
            )
        )

    async def get_result(self, project_id: UUID, tenant_id: UUID) -> ProjectLaunchResult | None:
        project = await ProjectService(self.db).get_project(project_id, tenant_id)
        plan = await self.get_plan(project_id, tenant_id)
        if project is None or plan is None:
            return None
        return ProjectLaunchResult(project=project, plan=plan)

    async def retry(
        self,
        *,
        project_id: UUID,
        tenant_id: UUID,
        requested_by: UUID,
    ) -> ProjectLaunchResult:
        result = await self.get_result(project_id, tenant_id)
        if result is None:
            raise LookupError("Project launch plan not found")
        return await self._execute(project=result.project, plan=result.plan, requested_by=requested_by)

    async def _validate_configuration(
        self,
        *,
        tenant_id: UUID,
        member_ids: list[UUID],
        document_types: list[str],
        workflow_template_ids: list[str],
    ) -> None:
        allowed_document_types = {item.value for item in DocumentType}
        invalid_document_types = sorted(set(document_types) - allowed_document_types)
        if invalid_document_types:
            raise ValueError(f"Document type is not supported: {', '.join(invalid_document_types)}")

        allowed_workflows = {
            item["template_id"] for item in WorkflowService.list_workflow_templates()
        }
        invalid_workflows = sorted(set(workflow_template_ids) - allowed_workflows)
        if invalid_workflows:
            raise ValueError(f"Workflow template is not supported: {', '.join(invalid_workflows)}")

        unique_member_ids = set(member_ids)
        if unique_member_ids:
            valid_members = set(
                (
                    await self.db.execute(
                        select(User.id).where(
                            User.id.in_(unique_member_ids),
                            User.tenant_id == tenant_id,
                            User.is_active.is_(True),
                            User.deleted_at.is_(None),
                        )
                    )
                ).scalars().all()
            )
            if valid_members != unique_member_ids:
                raise ValueError("Project members must be active users in the current tenant")

    async def _execute(
        self,
        *,
        project: Project,
        plan: ProjectLaunchPlan,
        requested_by: UUID,
    ) -> ProjectLaunchResult:
        plan.status = "running"
        plan.error_message = None
        plan.attempt_count = (plan.attempt_count or 0) + 1
        await self.db.flush()

        config = dict(plan.config_json or {})
        document_types = list(config.get("document_types") or [])
        workflow_template_ids = list(config.get("workflow_template_ids") or [])
        member_ids = [UUID(value) for value in config.get("member_ids") or []]

        try:
            member_result = await self._ensure_members(project.id, member_ids)
            document_result = await self._ensure_documents(
                project=project,
                document_types=document_types,
                requested_by=requested_by,
                blueprint_key=plan.blueprint_key,
            )
            await WorkflowService(self.db).ensure_default_workflows(project.tenant_id, requested_by)
            await self._ensure_settings(project.id, plan.blueprint_key, workflow_template_ids)
            from app.domains.projects.delivery_plan_service import ProjectDeliveryPlanService

            await ProjectDeliveryPlanService(self.db).initialize(
                project_id=project.id,
                tenant_id=project.tenant_id,
                requested_by=requested_by,
                blueprint_key=plan.blueprint_key,
                document_types=document_types,
                workflow_template_ids=workflow_template_ids,
            )

            checks = [
                {"key": "owner", "label": "项目负责人已加入", "status": "passed"},
                {
                    "key": "documents",
                    "label": "初始交付文档已规划",
                    "status": "passed" if document_types else "attention",
                },
                {
                    "key": "workflows",
                    "label": "推荐工作流已就绪",
                    "status": "passed" if workflow_template_ids else "attention",
                },
            ]
            plan.checks_json = checks
            plan.results_json = {
                "members": member_result,
                "documents": document_result,
                "workflows": {
                    "selected": workflow_template_ids,
                    "available": len(WorkflowService.list_workflow_templates()),
                },
                "next_actions": (self.get_blueprint(plan.blueprint_key) or self.BLUEPRINTS[0]).next_actions,
            }
            plan.status = "ready" if all(item["status"] == "passed" for item in checks) else "attention"
            plan.completed_at = datetime.now(timezone.utc)
            config["project_settings"] = {
                **dict(config.get("project_settings") or {}),
                "launch_blueprint": plan.blueprint_key,
                "launch_status": plan.status,
            }
            plan.config_json = config
        except Exception as error:
            plan.status = "failed"
            plan.error_message = str(error)
            plan.completed_at = datetime.now(timezone.utc)
            plan.checks_json = [
                {
                    "key": "initialization",
                    "label": "项目启动初始化",
                    "status": "failed",
                    "message": str(error),
                }
            ]
            plan.results_json = {
                "next_actions": ["检查失败原因", "修复依赖后重新检查启动计划"],
            }
            await self.db.flush()
            await self.db.refresh(plan)
            return ProjectLaunchResult(project=project, plan=plan)

        await self.db.flush()
        await self.db.refresh(plan)
        return ProjectLaunchResult(project=project, plan=plan)

    async def _ensure_members(self, project_id: UUID, member_ids: list[UUID]) -> dict[str, int]:
        existing_ids = set(
            (
                await self.db.execute(
                    select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
                )
            ).scalars().all()
        )
        added = 0
        for member_id in member_ids:
            if member_id in existing_ids:
                continue
            self.db.add(ProjectMember(project_id=project_id, user_id=member_id))
            existing_ids.add(member_id)
            added += 1
        await self.db.flush()
        return {"added": added, "existing": len(existing_ids) - added}

    async def _ensure_documents(
        self,
        *,
        project: Project,
        document_types: list[str],
        requested_by: UUID,
        blueprint_key: str,
    ) -> dict[str, Any]:
        existing_types = set(
            (
                await self.db.execute(
                    select(Document.doc_type).where(
                        Document.project_id == project.id,
                        Document.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
        )
        created_types: list[str] = []
        for doc_type in document_types:
            if doc_type in existing_types:
                continue
            label = DOCUMENT_LABELS.get(doc_type, doc_type)
            self.db.add(
                Document(
                    tenant_id=project.tenant_id,
                    project_id=project.id,
                    doc_type=doc_type,
                    title=f"{project.name} - {label}",
                    content="",
                    status=DocumentStatus.DRAFT.value,
                    created_by=requested_by,
                    metadata_json={
                        "launch_blueprint": blueprint_key,
                        "generation_status": "planned",
                        "has_placeholders": False,
                    },
                )
            )
            existing_types.add(doc_type)
            created_types.append(doc_type)
        await self.db.flush()
        return {
            "created": len(created_types),
            "existing": len(document_types) - len(created_types),
            "created_types": created_types,
        }

    async def _ensure_settings(
        self,
        project_id: UUID,
        blueprint_key: str,
        workflow_template_ids: list[str],
    ) -> None:
        settings_service = ProjectSettingsService(self.db)
        existing = await settings_service.get_settings(project_id)
        settings = dict(existing.settings_json or {}) if existing else {}
        settings["project_launch"] = {
            "blueprint_key": blueprint_key,
            "workflow_template_ids": workflow_template_ids,
        }
        await settings_service.upsert_settings(project_id=project_id, settings=settings)
