"""Executable project delivery plans and milestone gate evaluation."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.collaboration.models import CollaborationWorkItem
from app.domains.collaboration.work_item_service import ACTIVE_STATUSES, CollaborationWorkItemService
from app.domains.documents.models import Document, DocumentType
from app.domains.export.models import ExportArtifact, ExportJob, ExportStatus, ExportType
from app.domains.projects.models import ProjectDeliveryPlan, ProjectMilestone
from app.domains.projects.schemas import (
    ProjectAcceptanceResponse,
    ProjectAcceptanceUpdate,
    ProjectDeliveryPlanResponse,
    ProjectDeliveryPlanSummary,
    ProjectMilestoneCreate,
    ProjectMilestoneUpdate,
)
from app.models.projects import Project


FINAL_DOCUMENT_STATUSES = {"approved", "published"}
VALID_MILESTONE_STATUSES = {"planned", "in_progress", "blocked", "completed"}


class ProjectDeliveryPlanService:
    """Manage project milestones and evaluate delivery gates."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def initialize(
        self,
        *,
        project_id: UUID,
        tenant_id: UUID,
        requested_by: UUID,
        blueprint_key: str,
        document_types: list[str] | None = None,
        workflow_template_ids: list[str] | None = None,
    ) -> ProjectDeliveryPlan:
        existing = await self.get_plan(project_id, tenant_id)
        if existing:
            return existing
        project = await self._project(project_id, tenant_id)
        if not document_types:
            document_types = list(
                dict.fromkeys(
                    (
                        await self.db.scalars(
                            select(Document.doc_type).where(
                                Document.project_id == project_id,
                                Document.deleted_at.is_(None),
                            )
                        )
                    ).all()
                )
            )
        workflow_template_ids = workflow_template_ids or []
        groups = self._milestone_groups(document_types, workflow_template_ids)
        plan = ProjectDeliveryPlan(
            tenant_id=tenant_id,
            project_id=project_id,
            blueprint_key=blueprint_key,
            status="active",
            summary_json={},
            settings_json={"gate_policy": "governed"},
            created_by=requested_by,
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(plan)
        await self.db.flush()
        for index, group in enumerate(groups):
            milestone = ProjectMilestone(
                tenant_id=tenant_id,
                project_id=project_id,
                plan_id=plan.id,
                owner_id=project.owner_id,
                order_index=index,
                **group,
            )
            self.db.add(milestone)
            await self.db.flush()
            await self._sync_work_item(milestone, requested_by)
        await self.db.flush()
        await self.db.refresh(plan)
        await self._refresh_plan(plan)
        return plan

    async def get_plan(self, project_id: UUID, tenant_id: UUID) -> ProjectDeliveryPlan | None:
        return await self.db.scalar(
            select(ProjectDeliveryPlan).where(
                ProjectDeliveryPlan.project_id == project_id,
                ProjectDeliveryPlan.tenant_id == tenant_id,
            )
        )

    async def build_response(
        self, project_id: UUID, tenant_id: UUID
    ) -> ProjectDeliveryPlanResponse | None:
        plan = await self.get_plan(project_id, tenant_id)
        if not plan:
            return None
        for milestone in plan.milestones:
            milestone.gate_results_json = await self._evaluate_gates(milestone)
        summary = await self._refresh_plan(plan)
        payload = ProjectDeliveryPlanResponse.model_validate(plan).model_dump()
        payload["summary"] = summary
        return ProjectDeliveryPlanResponse.model_validate(payload)

    async def create_milestone(
        self,
        *,
        project_id: UUID,
        tenant_id: UUID,
        requested_by: UUID,
        data: ProjectMilestoneCreate,
    ) -> ProjectMilestone:
        plan = await self.get_plan(project_id, tenant_id)
        if not plan:
            raise ValueError("Project delivery plan not found")
        if any(item.key == data.key for item in plan.milestones):
            raise ValueError("Milestone key already exists")
        self._validate_document_types(data.required_document_types)
        milestone = ProjectMilestone(
            tenant_id=tenant_id,
            project_id=project_id,
            plan_id=plan.id,
            owner_id=data.owner_id,
            key=data.key,
            title=data.title,
            description=data.description,
            priority=data.priority,
            order_index=len(plan.milestones),
            planned_start_at=data.planned_start_at,
            due_at=data.due_at,
            required_document_types_json=data.required_document_types,
            required_workflow_template_ids_json=data.required_workflow_template_ids,
            gate_results_json=[],
            metadata_json={},
        )
        self.db.add(milestone)
        await self.db.flush()
        await self._sync_work_item(milestone, requested_by)
        await self._refresh_plan(plan)
        return milestone

    async def update(
        self,
        milestone_id: UUID,
        tenant_id: UUID,
        requested_by: UUID,
        data: ProjectMilestoneUpdate,
        project_id: UUID | None = None,
    ) -> ProjectMilestone:
        milestone = await self._milestone(milestone_id, tenant_id, project_id)
        changes = data.model_dump(exclude_unset=True)
        if "required_document_types" in changes:
            self._validate_document_types(changes["required_document_types"])
        for key, value in changes.items():
            target = {
                "required_document_types": "required_document_types_json",
                "required_workflow_template_ids": "required_workflow_template_ids_json",
            }.get(key, key)
            setattr(milestone, target, value)
        if milestone.status == "blocked":
            milestone.status = "planned"
            milestone.completed_at = None
        await self.db.flush()
        await self._sync_work_item(milestone, requested_by)
        await self._set_work_item_status(milestone, "open")
        await self._refresh_plan(milestone.plan)
        return milestone

    async def delete(
        self,
        milestone_id: UUID,
        tenant_id: UUID,
        requested_by: UUID,
        project_id: UUID | None = None,
    ) -> None:
        milestone = await self._milestone(milestone_id, tenant_id, project_id)
        project = await self._project(milestone.project_id, tenant_id)
        if project.owner_id != requested_by:
            raise PermissionError("Only project owner can delete a milestone")
        plan = milestone.plan
        item = await self.db.scalar(
            select(CollaborationWorkItem).where(
                CollaborationWorkItem.tenant_id == tenant_id,
                CollaborationWorkItem.source_key == f"milestone:{milestone.id}",
            )
        )
        if item:
            await self.db.delete(item)
        plan.milestones.remove(milestone)
        await self.db.delete(milestone)
        for index, remaining in enumerate(plan.milestones):
            remaining.order_index = index
        await self.db.flush()
        await self._refresh_plan(plan)

    async def reorder(
        self, project_id: UUID, tenant_id: UUID, milestone_ids: list[UUID]
    ) -> ProjectDeliveryPlan:
        plan = await self.get_plan(project_id, tenant_id)
        if not plan or set(milestone_ids) != {item.id for item in plan.milestones}:
            raise ValueError("Milestone order must contain every project milestone exactly once")
        by_id = {item.id: item for item in plan.milestones}
        for index, milestone_id in enumerate(milestone_ids):
            by_id[milestone_id].order_index = index
        plan.milestones.sort(key=lambda item: item.order_index)
        await self.db.flush()
        await self.db.refresh(plan)
        return plan

    async def start(
        self, milestone_id: UUID, tenant_id: UUID, requested_by: UUID, project_id: UUID | None = None
    ) -> ProjectMilestone:
        milestone = await self._milestone(milestone_id, tenant_id, project_id)
        self._require_responsible(milestone, requested_by)
        if milestone.status == "completed":
            raise ValueError("Completed milestone must be reopened before starting")
        milestone.status = "in_progress"
        await self._set_work_item_status(milestone, "in_progress")
        await self.db.flush()
        return milestone

    async def complete(
        self, milestone_id: UUID, tenant_id: UUID, requested_by: UUID, project_id: UUID | None = None
    ) -> ProjectMilestone:
        milestone = await self._milestone(milestone_id, tenant_id, project_id)
        self._require_responsible(milestone, requested_by)
        gates = await self._evaluate_gates(milestone)
        blockers = [item["message"] for item in gates if item["status"] == "blocked"]
        milestone.gate_results_json = gates
        if blockers:
            milestone.status = "blocked"
            milestone.completed_at = None
            await self._set_work_item_status(milestone, "blocked")
            await self.db.flush()
            await self._refresh_plan(milestone.plan)
            return milestone
        milestone.status = "completed"
        milestone.completed_at = datetime.now(timezone.utc)
        await self._set_work_item_status(milestone, "done")
        await self.db.flush()
        await self._refresh_plan(milestone.plan)
        return milestone

    async def reopen(
        self, milestone_id: UUID, tenant_id: UUID, requested_by: UUID, project_id: UUID | None = None
    ) -> ProjectMilestone:
        milestone = await self._milestone(milestone_id, tenant_id, project_id)
        project = await self._project(milestone.project_id, tenant_id)
        if project.owner_id != requested_by:
            raise PermissionError("Only project owner can reopen a milestone")
        milestone.status = "planned"
        milestone.completed_at = None
        await self._set_work_item_status(milestone, "open")
        await self.db.flush()
        await self._refresh_plan(milestone.plan)
        return milestone

    async def get_acceptance(
        self, project_id: UUID, tenant_id: UUID
    ) -> ProjectAcceptanceResponse:
        plan = await self.get_plan(project_id, tenant_id)
        if not plan:
            raise ValueError("Project delivery plan not found")
        return await self._acceptance_response(plan)

    async def update_acceptance(
        self,
        project_id: UUID,
        tenant_id: UUID,
        requested_by: UUID,
        data: ProjectAcceptanceUpdate,
    ) -> ProjectAcceptanceResponse:
        plan = await self.get_plan(project_id, tenant_id)
        if not plan:
            raise ValueError("Project delivery plan not found")
        await self._require_project_owner(project_id, tenant_id, requested_by)
        existing = dict((plan.settings_json or {}).get("customer_acceptance") or {})
        payload = data.model_dump(mode="json")
        payload["updated_by"] = str(requested_by)
        payload["accepted_at"] = (
            datetime.now(timezone.utc).isoformat()
            if data.decision in {"accepted", "accepted_with_followups"}
            else None
        )
        payload["closed_at"] = existing.get("closed_at")
        plan.settings_json = {**(plan.settings_json or {}), "customer_acceptance": payload}
        await self.db.flush()
        return await self._acceptance_response(plan)

    async def close_delivery(
        self, project_id: UUID, tenant_id: UUID, requested_by: UUID
    ) -> ProjectAcceptanceResponse:
        plan = await self.get_plan(project_id, tenant_id)
        if not plan:
            raise ValueError("Project delivery plan not found")
        await self._require_project_owner(project_id, tenant_id, requested_by)
        response = await self._acceptance_response(plan)
        if response.gate.status != "passed":
            raise ValueError("; ".join(response.gate.blockers))
        acceptance = dict((plan.settings_json or {}).get("customer_acceptance") or {})
        acceptance["closed_at"] = datetime.now(timezone.utc).isoformat()
        acceptance["updated_by"] = str(requested_by)
        plan.settings_json = {**(plan.settings_json or {}), "customer_acceptance": acceptance}
        release = next((item for item in plan.milestones if item.key == "release-delivery"), None)
        if release:
            release.status = "completed"
            release.completed_at = datetime.now(timezone.utc)
            await self._set_work_item_status(release, "done")
        await self._refresh_plan(plan)
        return await self._acceptance_response(plan)

    async def reopen_delivery(
        self, project_id: UUID, tenant_id: UUID, requested_by: UUID
    ) -> ProjectAcceptanceResponse:
        plan = await self.get_plan(project_id, tenant_id)
        if not plan:
            raise ValueError("Project delivery plan not found")
        await self._require_project_owner(project_id, tenant_id, requested_by)
        acceptance = dict((plan.settings_json or {}).get("customer_acceptance") or {})
        acceptance["closed_at"] = None
        acceptance["updated_by"] = str(requested_by)
        plan.settings_json = {**(plan.settings_json or {}), "customer_acceptance": acceptance}
        release = next((item for item in plan.milestones if item.key == "release-delivery"), None)
        if release:
            release.status = "planned"
            release.completed_at = None
            await self._set_work_item_status(release, "open")
        await self._refresh_plan(plan)
        return await self._acceptance_response(plan)

    async def _acceptance_response(
        self, plan: ProjectDeliveryPlan
    ) -> ProjectAcceptanceResponse:
        acceptance = dict((plan.settings_json or {}).get("customer_acceptance") or {})
        items = list(acceptance.get("items") or [])
        package_jobs = list(
            (
                await self.db.scalars(
                    select(ExportJob).where(
                        ExportJob.tenant_id == plan.tenant_id,
                        ExportJob.project_id == plan.project_id,
                        ExportJob.export_type == ExportType.PROJECT_PACKAGE.value,
                        ExportJob.status == ExportStatus.COMPLETED.value,
                    )
                )
            ).all()
        )
        package_job_ids = [job.id for job in package_jobs]
        artifact_count = int(
            await self.db.scalar(
                select(func.count()).select_from(ExportArtifact).where(
                    ExportArtifact.job_id.in_(package_job_ids)
                )
            )
            or 0
        ) if package_job_ids else 0
        package_ready = bool(package_jobs and artifact_count)
        decision = acceptance.get("decision", "pending")
        blockers = []
        warnings = []
        if decision not in {"accepted", "accepted_with_followups"}:
            blockers.append("客户尚未给出可交付的验收结论")
        if not acceptance.get("customer_name") or not acceptance.get("contact_name"):
            blockers.append("客户与签署联系人信息不完整")
        if not items:
            blockers.append("尚未登记验收项")
        rejected = [item for item in items if item.get("status") == "rejected"]
        pending = [item for item in items if item.get("status") == "pending"]
        if rejected:
            blockers.append(f"{len(rejected)} 个验收项被拒绝")
        if pending and decision != "accepted_with_followups":
            blockers.append(f"{len(pending)} 个验收项尚未确认")
        elif pending:
            warnings.append(f"{len(pending)} 个验收项作为后续事项跟踪")
        if not package_ready:
            blockers.append("尚无包含可下载产物的正式项目交付包")
        incomplete = [
            item.title
            for item in plan.milestones
            if item.key != "release-delivery" and item.status != "completed"
        ]
        if incomplete:
            blockers.append(f"{len(incomplete)} 个前置交付里程碑尚未完成")
        status = "passed" if not blockers else "blocked"
        return ProjectAcceptanceResponse(
            project_id=plan.project_id,
            customer_name=acceptance.get("customer_name", ""),
            contact_name=acceptance.get("contact_name", ""),
            contact_email=acceptance.get("contact_email", ""),
            decision=decision,
            notes=acceptance.get("notes", ""),
            items=items,
            updated_by=acceptance.get("updated_by"),
            accepted_at=acceptance.get("accepted_at"),
            closed_at=acceptance.get("closed_at"),
            package_ready=package_ready,
            gate={
                "status": status,
                "label": "可正式关闭" if status == "passed" else "关闭门禁未通过",
                "blockers": blockers,
                "warnings": warnings,
            },
        )

    async def _evaluate_gates(self, milestone: ProjectMilestone) -> list[dict]:
        required = list(milestone.required_document_types_json or [])
        documents = list(
            (
                await self.db.scalars(
                    select(Document).where(
                        Document.project_id == milestone.project_id,
                        Document.doc_type.in_(required),
                        Document.deleted_at.is_(None),
                    )
                )
            ).all()
        ) if required else []
        by_type = {document.doc_type: document for document in documents}
        missing = [doc_type for doc_type in required if doc_type not in by_type]
        needs_final = milestone.key in {"review-traceability", "release-delivery"}
        unfinished = [
            doc_type for doc_type, document in by_type.items()
            if needs_final and document.status not in FINAL_DOCUMENT_STATUSES
        ]
        active_items = int(
            await self.db.scalar(
                select(func.count()).select_from(CollaborationWorkItem).where(
                    CollaborationWorkItem.project_id == milestone.project_id,
                    CollaborationWorkItem.status.in_(ACTIVE_STATUSES),
                    (
                        CollaborationWorkItem.source_key.is_(None)
                        | CollaborationWorkItem.source_key.not_like("milestone:%")
                    ),
                )
            ) or 0
        )
        return [
            {
                "key": "required-documents",
                "status": "blocked" if missing else "passed",
                "message": f"Missing required documents: {', '.join(missing)}" if missing else "Required documents exist",
                "action_href": f"/projects/{milestone.project_id}/documents",
            },
            {
                "key": "document-approval",
                "status": "blocked" if unfinished else "passed",
                "message": (
                    f"Documents must be approved or published: {', '.join(unfinished)}"
                    if unfinished else "Document approval gate passed"
                ),
                "action_href": f"/projects/{milestone.project_id}/documents",
            },
            {
                "key": "active-work-items",
                "status": "blocked" if active_items else "passed",
                "message": f"{active_items} active collaboration work items remain" if active_items else "No active collaboration blockers",
                "action_href": "/collaboration",
            },
        ]

    async def _refresh_plan(self, plan: ProjectDeliveryPlan) -> ProjectDeliveryPlanSummary:
        milestones = list(plan.milestones)
        now = datetime.now(timezone.utc)
        completed = sum(item.status == "completed" for item in milestones)
        blocked = sum(item.status == "blocked" for item in milestones)
        overdue = sum(
            bool(item.due_at and item.due_at < now and item.status != "completed")
            for item in milestones
        )
        next_item = next((item for item in milestones if item.status != "completed"), None)
        blockers = [item.title for item in milestones if item.status == "blocked"]
        summary = ProjectDeliveryPlanSummary(
            total_count=len(milestones),
            completed_count=completed,
            blocked_count=blocked,
            overdue_count=overdue,
            progress_percent=round(completed / len(milestones) * 100) if milestones else 0,
            next_milestone_id=next_item.id if next_item else None,
            blockers=blockers,
        )
        plan.summary_json = summary.model_dump(mode="json")
        plan.status = "completed" if milestones and completed == len(milestones) else "attention" if blocked or overdue else "active"
        plan.completed_at = now if plan.status == "completed" else None
        await self.db.flush()
        return summary

    async def _sync_work_item(self, milestone: ProjectMilestone, requested_by: UUID) -> None:
        service = CollaborationWorkItemService(self.db)
        item = await service.create_work_item(
            tenant_id=milestone.tenant_id,
            created_by=requested_by,
            project_id=milestone.project_id,
            assigned_to=milestone.owner_id,
            title=milestone.title,
            description=milestone.description,
            priority=milestone.priority,
            due_at=milestone.due_at,
            source_key=f"milestone:{milestone.id}",
            metadata={"milestone_id": str(milestone.id)},
        )
        item.assigned_to = milestone.owner_id
        item.title = milestone.title
        item.description = milestone.description
        item.priority = milestone.priority
        item.due_at = milestone.due_at
        await self.db.flush()

    async def _set_work_item_status(self, milestone: ProjectMilestone, status: str) -> None:
        item = await self.db.scalar(
            select(CollaborationWorkItem).where(
                CollaborationWorkItem.tenant_id == milestone.tenant_id,
                CollaborationWorkItem.source_key == f"milestone:{milestone.id}",
            )
        )
        if item:
            item.status = status
            item.completed_at = datetime.now(timezone.utc) if status == "done" else None

    async def _project(self, project_id: UUID, tenant_id: UUID) -> Project:
        project = await self.db.scalar(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        if not project:
            raise ValueError("Project not found")
        return project

    async def _require_project_owner(
        self, project_id: UUID, tenant_id: UUID, requested_by: UUID
    ) -> Project:
        project = await self._project(project_id, tenant_id)
        if project.owner_id != requested_by:
            raise PermissionError("Only project owner can manage formal delivery acceptance")
        return project

    async def _milestone(
        self, milestone_id: UUID, tenant_id: UUID, project_id: UUID | None = None
    ) -> ProjectMilestone:
        filters = [
            ProjectMilestone.id == milestone_id,
            ProjectMilestone.tenant_id == tenant_id,
        ]
        if project_id is not None:
            filters.append(ProjectMilestone.project_id == project_id)
        milestone = await self.db.scalar(
            select(ProjectMilestone).where(*filters)
        )
        if not milestone:
            raise ValueError("Project milestone not found")
        return milestone

    def _require_responsible(self, milestone: ProjectMilestone, requested_by: UUID) -> None:
        if requested_by not in {milestone.owner_id, milestone.plan.project.owner_id}:
            raise PermissionError("Only project or milestone owner can manage this milestone")

    @staticmethod
    def _validate_document_types(document_types: list[str]) -> None:
        allowed = {item.value for item in DocumentType}
        invalid = sorted(set(document_types) - allowed)
        if invalid:
            raise ValueError(f"Document type is not supported: {', '.join(invalid)}")

    @staticmethod
    def _milestone_groups(document_types: list[str], workflow_ids: list[str]) -> list[dict]:
        midpoint = max(1, len(document_types) // 2)
        return [
            {
                "key": "scope-readiness",
                "title": "资料与范围确认",
                "description": "确认项目范围、输入资料和交付责任。",
                "required_document_types_json": document_types[:1],
                "required_workflow_template_ids_json": [],
            },
            {
                "key": "core-authoring",
                "title": "核心文档编写",
                "description": "完成核心需求和设计文档。",
                "required_document_types_json": document_types[:midpoint],
                "required_workflow_template_ids_json": workflow_ids[:1],
            },
            {
                "key": "review-traceability",
                "title": "评审与追溯",
                "description": "完成文档评审、批准和追溯关系检查。",
                "required_document_types_json": document_types[:midpoint],
                "required_workflow_template_ids_json": workflow_ids[1:],
            },
            {
                "key": "release-delivery",
                "title": "交付发布",
                "description": "通过交付门禁并发布完整项目成果。",
                "required_document_types_json": document_types,
                "required_workflow_template_ids_json": workflow_ids,
            },
        ]
