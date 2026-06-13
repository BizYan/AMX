"""Project Domain Services

Business logic for project management, members, and source files.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone
import inspect
from typing import Any
from uuid import UUID

from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.projects.models import (
    ProjectInvitation,
    ProjectMilestone,
    ProjectSettings,
    SourceFile,
    SourceFileStatus,
)
from app.domains.projects.schemas import (
    ProjectCreate,
    ProjectUpdate,
    ProjectMemberCreate,
    ProjectMemberUpdate,
    SourceFileCreate,
    SourceFileUpdate,
)
from app.models.projects import Project, ProjectMember
from app.models.identity import User


class ProjectService:
    """Service for project management operations."""

    DELIVERY_DOCUMENT_TYPES = [
        ("urs", "用户需求规格说明书"),
        ("brd", "业务需求文档"),
        ("prd", "产品需求文档"),
        ("user_story", "用户故事"),
        ("detailed_design", "详细设计说明"),
        ("interface", "接口说明"),
        ("data_dictionary", "数据字典"),
        ("test_case", "测试用例"),
    ]

    REVIEW_QUEUE_STATUSES = {
        "pending_review",
        "review",
        "in_review",
        "revision_required",
        "rejected",
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_project(self, data: ProjectCreate, tenant_id: UUID, owner_id: UUID | None = None) -> Project:
        """Create a new project.

        Args:
            data: Project creation data
            tenant_id: Tenant UUID
            owner_id: Optional owner user UUID

        Returns:
            Created Project

        Raises:
            ValueError: If slug already exists in tenant
        """
        # Check slug uniqueness within tenant
        existing = await self.db.execute(
            select(Project).where(
                Project.slug == data.slug,
                Project.tenant_id == tenant_id,
                Project.deleted_at.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Project with slug '{data.slug}' already exists in this tenant")

        project = Project(
            name=data.name,
            description=data.description,
            slug=data.slug,
            tenant_id=tenant_id,
            owner_id=owner_id,
        )
        self.db.add(project)
        await self.db.flush()

        if owner_id is not None:
            self.db.add(ProjectMember(project_id=project.id, user_id=owner_id))
            await self.db.flush()

        await self.db.refresh(project)
        return project

    async def get_project(
        self,
        project_id: UUID,
        tenant_id: UUID | None = None,
        include_deleted: bool = False,
    ) -> Project | None:
        """Get project by ID with optional tenant filter.

        Args:
            project_id: Project UUID
            tenant_id: Optional tenant filter
            include_deleted: Whether to include soft-deleted projects

        Returns:
            Project if found, None otherwise
        """
        query = select(Project).where(Project.id == project_id)
        if not include_deleted:
            query = query.where(Project.deleted_at.is_(None))
        if tenant_id is not None:
            query = query.where(Project.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_project_by_slug(self, slug: str, tenant_id: UUID) -> Project | None:
        """Get project by slug within a tenant.

        Args:
            slug: Project slug
            tenant_id: Tenant UUID

        Returns:
            Project if found, None otherwise
        """
        result = await self.db.execute(
            select(Project).where(
                Project.slug == slug,
                Project.tenant_id == tenant_id,
                Project.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_projects(
        self,
        tenant_id: UUID,
        user_id: UUID | None = None,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
    ) -> tuple[list[Project], int]:
        """List projects for a tenant (optionally filtered by membership).

        Args:
            tenant_id: Tenant UUID
            user_id: Optional user ID to filter projects they are member of
            skip: Number of records to skip
            limit: Maximum number of records to return
            status: Optional lifecycle status filter

        Returns:
            Tuple of (list of Projects, total count)
        """
        # Base query for tenant
        base_query = select(Project).where(
            Project.tenant_id == tenant_id,
            Project.deleted_at.is_(None),
        )
        if status is not None:
            base_query = base_query.where(Project.status == status)

        # If user_id provided, only show projects where user is a member
        if user_id:
            base_query = base_query.join(
                ProjectMember,
                ProjectMember.project_id == Project.id,
            ).where(ProjectMember.user_id == user_id)

        # Count rows from the filtered project subquery; referencing Project.id
        # outside the subquery creates a cartesian product in SQLAlchemy.
        project_count_subquery = base_query.with_only_columns(Project.id).order_by(None).subquery()
        count_query = select(func.count()).select_from(project_count_subquery)
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get paginated results
        result = await self.db.execute(
            base_query
            .options(selectinload(Project.members))
            .offset(skip)
            .limit(limit)
            .order_by(Project.created_at.desc())
        )
        projects = list(result.scalars().all())

        return projects, total

    async def set_project_status(
        self,
        project_id: UUID,
        status: str,
        tenant_id: UUID | None = None,
    ) -> Project | None:
        """Set a governed project lifecycle status."""
        if status not in {"active", "archived"}:
            raise ValueError(f"Unsupported project status: {status}")

        project = await self.get_project(project_id, tenant_id)
        if not project:
            return None

        project.status = status
        await self.db.flush()
        await self.db.refresh(project)
        return project

    async def update_project(
        self,
        project_id: UUID,
        data: ProjectUpdate,
        tenant_id: UUID | None = None,
    ) -> Project | None:
        """Update a project.

        Args:
            project_id: Project UUID
            data: Update data
            tenant_id: Optional tenant filter

        Returns:
            Updated Project if found, None otherwise

        Raises:
            ValueError: If slug already exists in tenant
        """
        project = await self.get_project(project_id, tenant_id)
        if not project:
            return None

        if data.slug is not None and data.slug != project.slug:
            # Check slug uniqueness
            existing = await self.db.execute(
                select(Project).where(
                    Project.slug == data.slug,
                    Project.tenant_id == project.tenant_id,
                    Project.deleted_at.is_(None),
                    Project.id != project_id,
                )
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Project with slug '{data.slug}' already exists in this tenant")
            project.slug = data.slug

        if data.name is not None:
            project.name = data.name
        if data.description is not None:
            project.description = data.description
        if data.status is not None:
            project.status = data.status

        await self.db.flush()
        await self.db.refresh(project)
        return project

    async def delete_project(
        self,
        project_id: UUID,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Soft delete a project.

        Args:
            project_id: Project UUID
            tenant_id: Optional tenant filter

        Returns:
            True if deleted, False if not found
        """
        project = await self.get_project(project_id, tenant_id)
        if not project:
            return False

        project.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    async def add_member(
        self,
        project_id: UUID,
        data: ProjectMemberCreate,
        tenant_id: UUID | None = None,
    ) -> ProjectMember:
        """Add a member to a project.

        Args:
            project_id: Project UUID
            data: Member creation data
            tenant_id: Optional tenant filter for project verification

        Returns:
            Created ProjectMember

        Raises:
            ValueError: If project not found or member already exists
        """
        project = await self.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")

        # Check if member already exists
        existing = await self.db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == data.user_id,
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("User is already a member of this project")

        member = ProjectMember(
            project_id=project_id,
            user_id=data.user_id,
            role_id=data.role_id,
        )
        self.db.add(member)
        await self.db.flush()
        await self.db.refresh(member)
        return member

    async def get_member(
        self,
        project_id: UUID,
        user_id: UUID,
    ) -> ProjectMember | None:
        """Get a project member.

        Args:
            project_id: Project UUID
            user_id: User UUID

        Returns:
            ProjectMember if found, None otherwise
        """
        result = await self.db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_members(
        self,
        project_id: UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[ProjectMember], int]:
        """List project members.

        Args:
            project_id: Project UUID
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of ProjectMembers, total count)
        """
        # Count total
        count_result = await self.db.execute(
            select(func.count(ProjectMember.user_id)).where(
                ProjectMember.project_id == project_id
            )
        )
        total = count_result.scalar()

        # Get paginated results
        result = await self.db.execute(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .offset(skip)
            .limit(limit)
            .order_by(ProjectMember.user_id)
        )
        members = list(result.scalars().all())

        return members, total

    async def remove_member(
        self,
        project_id: UUID,
        user_id: UUID,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Remove a member from a project.

        Args:
            project_id: Project UUID
            user_id: User UUID
            tenant_id: Optional tenant filter

        Returns:
            True if removed, False if not found
        """
        # Verify project access
        project = await self.get_project(project_id, tenant_id)
        if not project:
            return False

        member = await self.get_member(project_id, user_id)
        if not member:
            return False

        await self.db.delete(member)
        await self.db.flush()
        return True

    async def get_delivery_workbench(
        self,
        project_id: UUID,
        tenant_id: UUID,
    ) -> dict[str, Any] | None:
        """Build a project-level delivery cockpit from documents and adjacent domains."""
        from app.domains.change.models import (
            ChangeRequest,
            DocumentImpactAnalysis,
            DocumentReference,
            DocumentSyncProposal,
        )
        from app.domains.collaboration.models import DocumentComment
        from app.domains.documents.models import Document, DocumentGenerationSession, GenerationSessionStatus
        from app.domains.export.models import ExportJob
        from app.domains.knowledge.models import KnowledgeEntry
        from app.domains.templates.models import Template, TemplateSection, TemplateSectionSkillBinding, TemplateVersion

        project = await self.get_project(project_id, tenant_id)
        if not project:
            return None

        documents = list(
            (
                await self.db.execute(
                    select(Document)
                    .where(
                        Document.project_id == project_id,
                        Document.tenant_id == tenant_id,
                        Document.deleted_at.is_(None),
                    )
                    .order_by(Document.updated_at.desc())
                )
            )
            .scalars()
            .all()
        )

        active_sessions = list(
            (
                await self.db.execute(
                    select(DocumentGenerationSession)
                    .where(
                        DocumentGenerationSession.project_id == project_id,
                        DocumentGenerationSession.tenant_id == tenant_id,
                        DocumentGenerationSession.status == GenerationSessionStatus.ACTIVE.value,
                    )
                    .order_by(DocumentGenerationSession.updated_at.desc())
                )
            )
            .scalars()
            .all()
        )

        status_counts = Counter(document.status for document in documents)
        type_counts = Counter(document.doc_type for document in documents)

        files_by_status = dict(
            sorted(
                (
                    await self.db.execute(
                        select(SourceFile.status, func.count(SourceFile.id))
                        .where(
                            SourceFile.project_id == project_id,
                            SourceFile.tenant_id == tenant_id,
                            SourceFile.deleted_at.is_(None),
                        )
                        .group_by(SourceFile.status)
                    )
                ).all()
            )
        )
        source_file_total = sum(files_by_status.values())

        change_by_status = dict(
            sorted(
                (
                    await self.db.execute(
                        select(ChangeRequest.status, func.count(ChangeRequest.id))
                        .where(
                            ChangeRequest.project_id == project_id,
                            ChangeRequest.tenant_id == tenant_id,
                            ChangeRequest.deleted_at.is_(None),
                        )
                        .group_by(ChangeRequest.status)
                    )
                ).all()
            )
        )
        change_total = sum(change_by_status.values())

        member_total = await self.db.scalar(
            select(func.count(ProjectMember.user_id)).where(ProjectMember.project_id == project_id)
        ) or 0
        knowledge_total = await self.db.scalar(
            select(func.count(KnowledgeEntry.id)).where(
                KnowledgeEntry.project_id == project_id,
                KnowledgeEntry.tenant_id == tenant_id,
                KnowledgeEntry.deleted_at.is_(None),
            )
        ) or 0
        active_reference_total = await self.db.scalar(
            select(func.count(DocumentReference.id)).where(
                DocumentReference.project_id == project_id,
                DocumentReference.tenant_id == tenant_id,
                DocumentReference.status == "active",
                DocumentReference.deleted_at.is_(None),
            )
        ) or 0
        open_impact_total = await self.db.scalar(
            select(func.count(DocumentImpactAnalysis.id)).where(
                DocumentImpactAnalysis.project_id == project_id,
                DocumentImpactAnalysis.tenant_id == tenant_id,
                DocumentImpactAnalysis.status == "open",
            )
        ) or 0
        pending_sync_total = await self.db.scalar(
            select(func.count(DocumentSyncProposal.id)).where(
                DocumentSyncProposal.project_id == project_id,
                DocumentSyncProposal.tenant_id == tenant_id,
                DocumentSyncProposal.status == "pending",
            )
        ) or 0
        document_ids = [document.id for document in documents]
        unresolved_comment_total = 0
        if document_ids:
            unresolved_comment_total = await self.db.scalar(
                select(func.count(DocumentComment.id)).where(
                    DocumentComment.tenant_id == tenant_id,
                    DocumentComment.document_id.in_(document_ids),
                    DocumentComment.resolved.is_(False),
                    DocumentComment.deleted_at.is_(None),
                )
            ) or 0

        latest_export_job = (
            (
                await self.db.execute(
                    select(ExportJob)
                    .where(
                        ExportJob.project_id == project_id,
                        ExportJob.tenant_id == tenant_id,
                    )
                    .order_by(ExportJob.created_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

        expected_doc_types = [doc_type for doc_type, _ in self.DELIVERY_DOCUMENT_TYPES]
        templates = list(
            (
                await self.db.execute(
                    select(Template).where(
                        Template.tenant_id == tenant_id,
                        Template.doc_type.in_(expected_doc_types),
                        Template.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        template_counts = Counter(
            template.doc_type
            for template in templates
            if str(template.is_active).lower() in {"true", "1", "yes", "active", "published"}
        )
        section_counts = dict(
            (
                await self.db.execute(
                    select(Template.doc_type, func.count(TemplateSection.id))
                    .select_from(TemplateSection)
                    .join(TemplateVersion, TemplateVersion.id == TemplateSection.template_version_id)
                    .join(Template, Template.id == TemplateVersion.template_id)
                    .where(
                        Template.tenant_id == tenant_id,
                        Template.doc_type.in_(expected_doc_types),
                        Template.deleted_at.is_(None),
                        TemplateSection.deleted_at.is_(None),
                    )
                    .group_by(Template.doc_type)
                )
            ).all()
        )
        skill_binding_counts = dict(
            (
                await self.db.execute(
                    select(Template.doc_type, func.count(TemplateSectionSkillBinding.id))
                    .select_from(TemplateSectionSkillBinding)
                    .join(TemplateSection, TemplateSection.id == TemplateSectionSkillBinding.section_id)
                    .join(TemplateVersion, TemplateVersion.id == TemplateSection.template_version_id)
                    .join(Template, Template.id == TemplateVersion.template_id)
                    .where(
                        Template.tenant_id == tenant_id,
                        Template.doc_type.in_(expected_doc_types),
                        Template.deleted_at.is_(None),
                        TemplateSection.deleted_at.is_(None),
                    )
                    .group_by(Template.doc_type)
                )
            ).all()
        )
        active_references = list(
            (
                await self.db.execute(
                    select(DocumentReference).where(
                        DocumentReference.project_id == project_id,
                        DocumentReference.tenant_id == tenant_id,
                        DocumentReference.status == "active",
                        DocumentReference.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        pending_sync_proposals = list(
            (
                await self.db.execute(
                    select(DocumentSyncProposal)
                    .where(
                        DocumentSyncProposal.project_id == project_id,
                        DocumentSyncProposal.tenant_id == tenant_id,
                        DocumentSyncProposal.status == "pending",
                    )
                    .order_by(DocumentSyncProposal.created_at.desc())
                    .limit(6)
                )
            )
            .scalars()
            .all()
        )

        latest_by_type: dict[str, Document] = {}
        for document in documents:
            if document.doc_type not in latest_by_type:
                latest_by_type[document.doc_type] = document

        delivery_chain = []
        missing_types = []
        for doc_type, label in self.DELIVERY_DOCUMENT_TYPES:
            document = latest_by_type.get(doc_type)
            if document:
                delivery_meta = (document.metadata_json or {}).get("delivery", {})
                quality_summary = delivery_meta.get("quality_summary", {})
                delivery_chain.append(
                    {
                        "doc_type": doc_type,
                        "label": label,
                        "document_id": str(document.id),
                        "title": document.title,
                        "status": document.status,
                        "version": document.version,
                        "updated_at": document.updated_at,
                        "missing": False,
                        "completion_ratio": delivery_meta.get("completion_ratio", 1 if document.status in {"approved", "published"} else 0.5),
                        "quality_level": quality_summary.get("sufficiency_level") or quality_summary.get("level"),
                        "upstream_dependencies": delivery_meta.get("upstream_dependencies", []),
                        "blockers": [
                            item.get("message", str(item)) if isinstance(item, dict) else str(item)
                            for item in delivery_meta.get("pending_confirmations", [])
                        ],
                        "action_href": f"/projects/{project_id}/documents/{document.id}",
                    }
                )
            else:
                missing_types.append(label)
                delivery_chain.append(
                    {
                        "doc_type": doc_type,
                        "label": label,
                        "document_id": None,
                        "title": None,
                        "status": "missing",
                        "version": None,
                        "updated_at": None,
                        "missing": True,
                        "completion_ratio": 0,
                        "quality_level": None,
                        "upstream_dependencies": self._delivery_upstream_dependencies(doc_type),
                        "blockers": ["文档尚未生成"],
                        "action_href": f"/projects/{project_id}/documents/generate?docType={doc_type}",
                    }
                )

        def document_item(document: Document) -> dict[str, Any]:
            return {
                "id": str(document.id),
                "title": document.title,
                "doc_type": document.doc_type,
                "status": document.status,
                "version": document.version,
                "updated_at": document.updated_at,
            }

        review_queue = [
            document_item(document)
            for document in documents
            if document.status in self.REVIEW_QUEUE_STATUSES
        ][:8]
        recent_documents = [document_item(document) for document in documents[:8]]

        risks: list[dict[str, str]] = []
        if pending_sync_total:
            risks.append(
                {
                    "code": "pending_sync_proposals",
                    "severity": "high",
                    "title": "有待处理的影响同步提案",
                    "description": f"{pending_sync_total} 个下游文档同步提案需要人工确认。",
                    "target_href": f"/projects/{project_id}/traceability",
                }
            )
        if review_queue:
            risks.append(
                {
                    "code": "documents_need_review",
                    "severity": "high",
                    "title": "有文档等待评审处理",
                    "description": f"{len(review_queue)} 份文档处于评审、退回或修订状态。",
                    "target_href": f"/projects/{project_id}/documents",
                }
            )
        failed_file_count = files_by_status.get("failed", 0)
        if failed_file_count:
            risks.append(
                {
                    "code": "failed_source_files",
                    "severity": "medium",
                    "title": "有资料解析失败",
                    "description": f"{failed_file_count} 个项目资料需要重新上传或处理。",
                    "target_href": f"/projects/{project_id}/files",
                }
            )
        open_change_count = sum(
            count for status, count in change_by_status.items() if status in {"draft", "open", "approved"}
        )
        if open_change_count:
            risks.append(
                {
                    "code": "open_change_requests",
                    "severity": "medium",
                    "title": "有未闭环的变更请求",
                    "description": f"{open_change_count} 个变更请求尚未应用或关闭。",
                    "target_href": f"/projects/{project_id}/changes",
                }
            )
        if missing_types:
            shown = "、".join(missing_types[:3])
            suffix = "等" if len(missing_types) > 3 else ""
            risks.append(
                {
                    "code": "missing_delivery_documents",
                    "severity": "medium",
                    "title": "交付链路缺少关键文档",
                    "description": f"{shown}{suffix}尚未生成，交付链路未闭环。",
                    "target_href": f"/projects/{project_id}/documents/generate",
                }
            )
        if unresolved_comment_total:
            risks.append(
                {
                    "code": "unresolved_document_comments",
                    "severity": "medium",
                    "title": "仍有未解决的文档评论",
                    "description": f"{unresolved_comment_total} 条文档评论需要处理后再发布或打包导出。",
                    "target_href": f"/projects/{project_id}/documents",
                }
            )

        next_actions = self._build_delivery_next_actions(
            project_id=project_id,
            document_total=len(documents),
            source_file_total=source_file_total,
            review_queue_count=len(review_queue),
            pending_sync_total=pending_sync_total,
            failed_file_count=failed_file_count,
            missing_type_count=len(missing_types),
            open_change_count=open_change_count,
        )

        completed_document_count = sum(
            1 for doc_type in expected_doc_types if doc_type in latest_by_type
        )
        approved_or_published_count = sum(
            1
            for doc_type in expected_doc_types
            if doc_type in latest_by_type and latest_by_type[doc_type].status in {"approved", "published"}
        )
        export_blockers = []
        if missing_types:
            export_blockers.append(f"缺少 {len(missing_types)} 类核心交付文档")
        if review_queue:
            export_blockers.append(f"{len(review_queue)} 份文档仍在评审或修订")
        if pending_sync_total:
            export_blockers.append(f"{pending_sync_total} 个追溯同步提案待确认")
        if unresolved_comment_total:
            export_blockers.append(f"{unresolved_comment_total} 条评论未解决")

        ready_source_file_count = int(files_by_status.get(SourceFileStatus.READY.value, 0))
        pending_source_file_count = int(
            files_by_status.get(SourceFileStatus.PENDING.value, 0)
            + files_by_status.get(SourceFileStatus.PROCESSING.value, 0)
        )
        source_coverage_blockers = []
        if source_file_total == 0:
            source_coverage_blockers.append("尚未上传项目资料")
        if failed_file_count:
            source_coverage_blockers.append(f"{failed_file_count} 个资料解析失败")
        if pending_source_file_count:
            source_coverage_blockers.append(f"{pending_source_file_count} 个资料仍在处理中")
        if source_file_total and not knowledge_total:
            source_coverage_blockers.append("项目资料尚未沉淀为知识条目")
        if source_file_total == 0:
            source_coverage_status = "blocked"
            source_coverage_label = "缺少资料"
        elif failed_file_count or pending_source_file_count or not knowledge_total:
            source_coverage_status = "warning"
            source_coverage_label = "需要复核"
        else:
            source_coverage_status = "ready"
            source_coverage_label = "资料可用"
        source_coverage = {
            "status": source_coverage_status,
            "label": source_coverage_label,
            "source_file_total": int(source_file_total),
            "ready_source_file_count": ready_source_file_count,
            "pending_source_file_count": pending_source_file_count,
            "failed_source_file_count": int(failed_file_count),
            "knowledge_entry_count": int(knowledge_total),
            "blockers": source_coverage_blockers,
            "action_href": f"/projects/{project_id}/files",
        }
        source_ready_for_delivery = source_coverage_status == "ready"

        workflow_lanes = [
            {
                "key": "authoring",
                "label": "编写",
                "count": sum(1 for document in documents if document.status in {"draft", "writing"}),
                "attention_count": len(active_sessions),
                "document_ids": [document.id for document in documents if document.status in {"draft", "writing"}][:8],
                "href": f"/projects/{project_id}/documents/generate",
            },
            {
                "key": "review",
                "label": "评审",
                "count": len(review_queue),
                "attention_count": len(review_queue) + int(unresolved_comment_total),
                "document_ids": [document["id"] for document in review_queue],
                "href": f"/projects/{project_id}/documents",
            },
            {
                "key": "release",
                "label": "发布",
                "count": approved_or_published_count,
                "attention_count": len(expected_doc_types) - approved_or_published_count,
                "document_ids": [
                    latest_by_type[doc_type].id
                    for doc_type in expected_doc_types
                    if doc_type in latest_by_type and latest_by_type[doc_type].status in {"approved", "published"}
                ],
                "href": f"/projects/{project_id}/documents",
            },
            {
                "key": "traceability",
                "label": "追溯",
                "count": int(active_reference_total),
                "attention_count": int(open_impact_total) + int(pending_sync_total),
                "document_ids": [],
                "href": f"/projects/{project_id}/traceability",
            },
            {
                "key": "export",
                "label": "导出",
                "count": 1 if latest_export_job else 0,
                "attention_count": len(export_blockers),
                "document_ids": [],
                "href": "/exports",
            },
        ]

        def gate_status(blocked: bool, warning: bool) -> str:
            if blocked:
                return "blocked"
            if warning:
                return "warning"
            return "passed"

        quality_gates = [
            {
                "key": "source_files",
                "label": "资料准备",
                "status": gate_status(failed_file_count > 0, source_file_total == 0),
                "score": 100 if source_file_total and not failed_file_count else (50 if source_file_total else 20),
                "message": "项目资料已可用于生成" if source_file_total and not failed_file_count else "需要补齐或修复项目资料",
                "target_href": f"/projects/{project_id}/files",
            },
            {
                "key": "delivery_chain",
                "label": "交付链完整性",
                "status": gate_status(False, bool(missing_types)),
                "score": round((completed_document_count / len(expected_doc_types)) * 100),
                "message": "核心交付文档已齐备" if not missing_types else f"仍缺少 {len(missing_types)} 类核心文档",
                "target_href": f"/projects/{project_id}/documents/generate",
            },
            {
                "key": "review",
                "label": "评审闭环",
                "status": gate_status(bool(review_queue), unresolved_comment_total > 0),
                "score": 100 if not review_queue and not unresolved_comment_total else max(20, 100 - (len(review_queue) * 20) - min(40, int(unresolved_comment_total) * 5)),
                "message": "评审与评论已闭环" if not review_queue and not unresolved_comment_total else "存在待评审文档或未解决评论",
                "target_href": f"/projects/{project_id}/documents",
            },
            {
                "key": "traceability",
                "label": "追溯一致性",
                "status": gate_status(bool(pending_sync_total), bool(open_impact_total) or active_reference_total == 0),
                "score": 100 if active_reference_total and not pending_sync_total and not open_impact_total else (60 if active_reference_total else 30),
                "message": "追溯关系稳定" if active_reference_total and not pending_sync_total and not open_impact_total else "需要处理追溯缺口或影响同步",
                "target_href": f"/projects/{project_id}/traceability",
            },
            {
                "key": "export",
                "label": "导出包准备",
                "status": gate_status(bool(export_blockers), False),
                "score": 100 if not export_blockers else max(10, 100 - len(export_blockers) * 25),
                "message": "可以生成项目交付包" if not export_blockers else export_blockers[0],
                "target_href": "/exports",
            },
        ]

        template_coverage = [
            {
                "doc_type": doc_type,
                "label": label,
                "template_available": template_counts.get(doc_type, 0) > 0,
                "active_template_count": int(template_counts.get(doc_type, 0)),
                "section_count": int(section_counts.get(doc_type, 0)),
                "skill_binding_count": int(skill_binding_counts.get(doc_type, 0)),
                "action_href": f"/templates?docType={doc_type}",
            }
            for doc_type, label in self.DELIVERY_DOCUMENT_TYPES
        ]
        package_manifest = []
        for index, (doc_type, label) in enumerate(self.DELIVERY_DOCUMENT_TYPES, start=1):
            document = latest_by_type.get(doc_type)
            blockers = []
            if not document:
                blockers.append("文档尚未生成")
            elif document.status not in {"approved", "published"}:
                blockers.append("文档尚未批准或发布")
            if document:
                delivery_meta = (document.metadata_json or {}).get("delivery", {})
                pending_confirmations = delivery_meta.get("pending_confirmations", [])
                if pending_confirmations:
                    blockers.append(f"{len(pending_confirmations)} 个生成确认项未关闭")
            package_manifest.append(
                {
                    "doc_type": doc_type,
                    "label": label,
                    "required": True,
                    "included": bool(document),
                    "release_ready": bool(document) and not blockers,
                    "document_id": document.id if document else None,
                    "title": document.title if document else None,
                    "status": document.status if document else "missing",
                    "version": document.version if document else None,
                    "export_order": index,
                    "blockers": blockers,
                    "action_href": f"/projects/{project_id}/documents/{document.id}" if document else f"/projects/{project_id}/documents/generate?docType={doc_type}",
                }
            )

        reference_pairs = {
            (reference.source_document_id, reference.target_document_id)
            for reference in active_references
        }
        expected_edges = [
            ("urs", "brd"),
            ("brd", "prd"),
            ("prd", "user_story"),
            ("prd", "detailed_design"),
            ("user_story", "detailed_design"),
            ("detailed_design", "interface"),
            ("detailed_design", "data_dictionary"),
            ("interface", "data_dictionary"),
            ("prd", "test_case"),
            ("detailed_design", "test_case"),
            ("interface", "test_case"),
        ]
        traceability_actions = []
        for source_type, target_type in expected_edges:
            source_doc = latest_by_type.get(source_type)
            target_doc = latest_by_type.get(target_type)
            if not source_doc or not target_doc:
                continue
            if (source_doc.id, target_doc.id) in reference_pairs:
                continue
            traceability_actions.append(
                {
                    "code": f"missing_reference_{source_type}_{target_type}",
                    "status": "missing_reference",
                    "source_document_id": source_doc.id,
                    "source_title": source_doc.title,
                    "source_doc_type": source_doc.doc_type,
                    "target_document_id": target_doc.id,
                    "target_title": target_doc.title,
                    "target_doc_type": target_doc.doc_type,
                    "reference_type": "derives_from",
                    "reason": f"缺少 {source_doc.doc_type.upper()} 到 {target_doc.doc_type.upper()} 的正式追溯引用",
                    "action_href": f"/projects/{project_id}/traceability",
                }
            )
        document_by_id = {document.id: document for document in documents}
        for proposal in pending_sync_proposals:
            source_doc = document_by_id.get(proposal.source_document_id)
            target_doc = document_by_id.get(proposal.target_document_id)
            traceability_actions.append(
                {
                    "code": f"pending_sync_{proposal.id}",
                    "status": "pending_sync",
                    "source_document_id": proposal.source_document_id,
                    "source_title": source_doc.title if source_doc else None,
                    "source_doc_type": source_doc.doc_type if source_doc else None,
                    "target_document_id": proposal.target_document_id,
                    "target_title": target_doc.title if target_doc else None,
                    "target_doc_type": target_doc.doc_type if target_doc else None,
                    "reference_type": "sync_proposal",
                    "reason": proposal.reason or "下游文档同步提案待确认",
                    "action_href": f"/projects/{project_id}/traceability",
                }
            )
        traceability_actions = traceability_actions[:8]

        collaboration_actions = []
        if active_sessions:
            collaboration_actions.append(
                {
                    "code": "resume_authoring_sessions",
                    "label": "继续对话式编写",
                    "description": f"{len(active_sessions)} 个文档生成会话仍未完成",
                    "count": len(active_sessions),
                    "priority": "high",
                    "action_href": f"/projects/{project_id}/documents/generate?sessionId={active_sessions[0].id}",
                }
            )
        if review_queue:
            collaboration_actions.append(
                {
                    "code": "process_review_queue",
                    "label": "处理文档评审",
                    "description": f"{len(review_queue)} 份文档等待评审、修订或退回处理",
                    "count": len(review_queue),
                    "priority": "high",
                    "action_href": f"/projects/{project_id}/documents",
                }
            )
        if unresolved_comment_total:
            collaboration_actions.append(
                {
                    "code": "resolve_document_comments",
                    "label": "解决文档评论",
                    "description": f"{unresolved_comment_total} 条评论尚未关闭",
                    "count": int(unresolved_comment_total),
                    "priority": "medium",
                    "action_href": f"/projects/{project_id}/documents",
                }
            )
        if open_change_count:
            collaboration_actions.append(
                {
                    "code": "close_document_changes",
                    "label": "关闭文档变更",
                    "description": f"{open_change_count} 个变更请求尚未闭环",
                    "count": open_change_count,
                    "priority": "medium",
                    "action_href": f"/projects/{project_id}/changes",
                }
            )
        if not collaboration_actions:
            collaboration_actions.append(
                {
                    "code": "review_release_readiness",
                    "label": "复核发布准备度",
                    "description": "协同阻塞已清空，可以复核追溯和导出包",
                    "count": 0,
                    "priority": "low",
                    "action_href": f"/projects/{project_id}/documents",
                }
            )

        traceability_gap_by_type: Counter[str] = Counter()
        for action in traceability_actions:
            source_type = action.get("source_doc_type")
            target_type = action.get("target_doc_type")
            if source_type:
                traceability_gap_by_type[source_type] += 1
            if target_type:
                traceability_gap_by_type[target_type] += 1
        active_session_by_type = {session.doc_type: session for session in active_sessions}

        def control_action(code: str, label: str, href: str, priority: str = "medium") -> dict[str, str]:
            return {"code": code, "label": label, "href": href, "priority": priority}

        control_matrix = []
        delivery_label_by_type = dict(self.DELIVERY_DOCUMENT_TYPES)
        for doc_type, label in self.DELIVERY_DOCUMENT_TYPES:
            document = latest_by_type.get(doc_type)
            delivery_meta = (document.metadata_json or {}).get("delivery", {}) if document else {}
            upstream_missing = [
                dependency
                for dependency in self._delivery_upstream_dependencies(doc_type)
                if dependency not in latest_by_type
            ]
            pending_confirmations = delivery_meta.get("pending_confirmations", [])
            blockers = []
            if not document:
                blockers.append("文档尚未生成")
            if upstream_missing:
                blockers.append(
                    "缺少上游依据：" + "、".join(delivery_label_by_type.get(item, item) for item in upstream_missing)
                )
            if document and document.status in self.REVIEW_QUEUE_STATUSES:
                blockers.append("文档仍在评审、退回或修订状态")
            elif document and document.status not in {"approved", "published"}:
                blockers.append("文档尚未批准或发布")
            if pending_confirmations:
                blockers.append(f"{len(pending_confirmations)} 个生成确认项未关闭")
            traceability_gap_count = int(traceability_gap_by_type.get(doc_type, 0))
            if traceability_gap_count:
                blockers.append(f"{traceability_gap_count} 个追溯缺口待处理")
            if not source_ready_for_delivery:
                blockers.append(source_coverage_blockers[0] if source_coverage_blockers else "资料覆盖需要复核")

            if doc_type in active_session_by_type:
                stage = "authoring"
                stage_label = "编写中"
                primary_action = control_action(
                    "resume_authoring",
                    "继续编写",
                    f"/projects/{project_id}/documents/generate?sessionId={active_session_by_type[doc_type].id}",
                    "high",
                )
            elif not document:
                stage = "missing"
                stage_label = "待生成"
                primary_action = control_action(
                    "start_authoring",
                    "开始编写",
                    f"/projects/{project_id}/documents/generate?docType={doc_type}",
                    "high",
                )
            elif document.status in self.REVIEW_QUEUE_STATUSES:
                stage = "review"
                stage_label = "评审中"
                primary_action = control_action(
                    "review_document",
                    "处理评审",
                    f"/projects/{project_id}/documents/{document.id}",
                    "high",
                )
            elif document.status == "published" and not blockers:
                stage = "published"
                stage_label = "已发布"
                primary_action = control_action(
                    "open_document",
                    "查看文档",
                    f"/projects/{project_id}/documents/{document.id}",
                    "low",
                )
            elif document.status == "approved" and not blockers:
                stage = "release_ready"
                stage_label = "可发布"
                primary_action = control_action(
                    "publish_document",
                    "发布文档",
                    f"/projects/{project_id}/documents/{document.id}",
                    "medium",
                )
            else:
                stage = "blocked"
                stage_label = "待处理"
                primary_action = control_action(
                    "repair_document",
                    "处理阻塞",
                    f"/projects/{project_id}/documents/{document.id}" if document else f"/projects/{project_id}/documents/generate?docType={doc_type}",
                    "high",
                )

            secondary_actions = [
                control_action("open_template", "模板章节", f"/templates?docType={doc_type}", "low"),
                control_action("open_traceability", "追溯检查", f"/projects/{project_id}/traceability", "medium"),
            ]
            if document:
                secondary_actions.append(
                    control_action("open_document", "打开文档", f"/projects/{project_id}/documents/{document.id}", "low")
                )
            else:
                secondary_actions.append(
                    control_action("upload_sources", "补充资料", f"/projects/{project_id}/files", "medium")
                )

            control_matrix.append(
                {
                    "doc_type": doc_type,
                    "label": label,
                    "stage": stage,
                    "stage_label": stage_label,
                    "document_id": document.id if document else None,
                    "title": document.title if document else None,
                    "status": document.status if document else "missing",
                    "version": document.version if document else None,
                    "completion_ratio": delivery_meta.get(
                        "completion_ratio",
                        1 if document and document.status in {"approved", "published"} else (0.5 if document else 0),
                    ),
                    "quality_level": (delivery_meta.get("quality_summary", {}) or {}).get("sufficiency_level")
                    or (delivery_meta.get("quality_summary", {}) or {}).get("level"),
                    "template_ready": template_counts.get(doc_type, 0) > 0 and section_counts.get(doc_type, 0) > 0,
                    "source_ready": source_ready_for_delivery,
                    "release_ready": bool(document) and not blockers and document.status in {"approved", "published"},
                    "package_included": bool(document),
                    "upstream_missing": upstream_missing,
                    "traceability_gap_count": traceability_gap_count,
                    "blockers": blockers[:5],
                    "primary_action": primary_action,
                    "secondary_actions": secondary_actions,
                }
            )

        return {
            "project_id": str(project_id),
            "generated_at": datetime.now(timezone.utc),
            "totals": {
                "documents": len(documents),
                "source_files": source_file_total,
                "knowledge_entries": int(knowledge_total),
                "members": int(member_total),
                "change_requests": change_total,
            },
            "document_status_counts": dict(sorted(status_counts.items())),
            "document_type_counts": dict(sorted(type_counts.items())),
            "source_file_status_counts": files_by_status,
            "change_status_counts": change_by_status,
            "traceability": {
                "active_references": int(active_reference_total),
                "open_impact_analyses": int(open_impact_total),
                "pending_sync_proposals": int(pending_sync_total),
            },
            "delivery_chain": delivery_chain,
            "review_queue": review_queue,
            "recent_documents": recent_documents,
            "risks": risks,
            "next_actions": next_actions,
            "active_sessions": [
                {
                    "id": session.id,
                    "doc_type": session.doc_type,
                    "title": session.title,
                    "status": session.status,
                    "current_section_key": session.current_section_key,
                    "confirmed_sections": int((session.quality_summary_json or {}).get("confirmed_sections", 0)),
                    "section_count": int((session.quality_summary_json or {}).get("section_count", 0)),
                    "updated_at": session.updated_at,
                }
                for session in active_sessions[:8]
            ],
            "readiness": {
                "ready": not risks and len(missing_types) == 0,
                "export_ready": len(missing_types) == 0 and not review_queue and pending_sync_total == 0,
                "review_ready": len(documents) > 0 and not review_queue,
                "blockers": [risk["title"] for risk in risks],
            },
            "workflow_lanes": workflow_lanes,
            "quality_gates": quality_gates,
            "template_coverage": template_coverage,
            "export_package": {
                "ready": not export_blockers,
                "required_document_count": len(expected_doc_types),
                "completed_document_count": completed_document_count,
                "approved_or_published_count": approved_or_published_count,
                "latest_job_id": latest_export_job.id if latest_export_job else None,
                "latest_job_status": latest_export_job.status if latest_export_job else None,
                "blockers": export_blockers,
                "action_href": "/exports",
            },
            "collaboration_summary": {
                "member_count": int(member_total),
                "unresolved_comment_count": int(unresolved_comment_total),
                "review_queue_count": len(review_queue),
                "active_session_count": len(active_sessions),
                "open_change_count": open_change_count,
                "action_href": "/collaboration",
            },
            "package_manifest": package_manifest,
            "traceability_actions": traceability_actions,
            "collaboration_actions": collaboration_actions,
            "control_matrix": control_matrix,
            "source_coverage": source_coverage,
        }

    @staticmethod
    def _delivery_upstream_dependencies(doc_type: str) -> list[str]:
        """Return expected upstream document types for one delivery-chain slot."""
        return {
            "urs": [],
            "brd": ["urs"],
            "prd": ["urs", "brd"],
            "user_story": ["prd"],
            "detailed_design": ["prd", "user_story"],
            "interface": ["prd", "detailed_design"],
            "data_dictionary": ["detailed_design", "interface"],
            "test_case": ["prd", "detailed_design", "interface"],
        }.get(doc_type, [])

    async def get_document_workbench(
        self,
        project_id: UUID,
        tenant_id: UUID,
    ) -> dict[str, Any] | None:
        """Alias for the project document workbench API."""
        return await self.get_delivery_workbench(project_id, tenant_id)

    async def get_system_delivery_overview(
        self,
        tenant_id: UUID,
        user_id: UUID,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Build the system-level command center from project delivery workbenches."""
        projects, total_projects = await self.list_projects(
            tenant_id=tenant_id,
            user_id=user_id,
            skip=0,
            limit=limit,
            status="active",
        )

        project_digests: list[dict[str, Any]] = []
        critical_actions: list[dict[str, Any]] = []
        operating_plan: list[dict[str, Any]] = []
        phase_stats = self._empty_delivery_phase_stats()
        gate_stats = self._empty_release_gate_stats()
        totals = {
            "projects": int(total_projects or 0),
            "documents": 0,
            "source_files": 0,
            "knowledge_entries": 0,
            "open_changes": 0,
            "review_queue": 0,
            "export_ready_projects": 0,
            "blocked_projects": 0,
        }

        for project in projects:
            workbench = await self.get_document_workbench(project.id, tenant_id)
            if not workbench:
                continue

            wb_totals = workbench.get("totals", {})
            readiness = workbench.get("readiness") or {}
            export_package = workbench.get("export_package") or {}
            collaboration_summary = workbench.get("collaboration_summary") or {}
            source_coverage = workbench.get("source_coverage") or {}
            traceability = workbench.get("traceability") or {}
            risks = workbench.get("risks") or []
            next_actions = workbench.get("next_actions") or []

            document_count = int(wb_totals.get("documents", 0))
            source_file_count = int(wb_totals.get("source_files", 0))
            knowledge_entry_count = int(wb_totals.get("knowledge_entries", 0))
            open_change_count = int(collaboration_summary.get("open_change_count", 0))
            review_queue_count = int(collaboration_summary.get("review_queue_count", 0))
            pending_sync_count = int(traceability.get("pending_sync_proposals", 0))
            blocker_count = len(readiness.get("blockers") or []) + len(risks)
            export_ready = bool(export_package.get("ready"))
            required_document_count = int(export_package.get("required_document_count") or 0)
            completed_document_count = int(export_package.get("completed_document_count") or document_count)
            source_ready = source_file_count > 0 and str(source_coverage.get("status") or "") in {"ready", "good"}
            documents_complete = (
                document_count > 0
                and (required_document_count <= 0 or completed_document_count >= required_document_count)
            )
            traceability_clear = pending_sync_count == 0 and open_change_count == 0
            review_clear = review_queue_count == 0
            release_gate_status = (
                "passed"
                if source_ready and documents_complete and traceability_clear and review_clear and export_ready
                else "blocked"
            )
            delivery_phase = self._delivery_phase(
                source_ready=source_ready,
                documents_complete=documents_complete,
                review_queue_count=review_queue_count,
                open_change_count=open_change_count,
                pending_sync_count=pending_sync_count,
                export_ready=export_ready,
            )
            phase_stats[delivery_phase["key"]]["project_count"] += 1
            phase_stats[delivery_phase["key"]]["blocked_project_count"] += 1 if blocker_count else 0
            phase_stats[delivery_phase["key"]]["ready_project_count"] += 1 if release_gate_status == "passed" else 0
            self._update_release_gate_stats(
                gate_stats,
                project_name=project.name,
                source_ready=source_ready,
                documents_complete=documents_complete,
                traceability_clear=traceability_clear,
                review_clear=review_clear,
                export_ready=export_ready,
            )

            totals["documents"] += document_count
            totals["source_files"] += source_file_count
            totals["knowledge_entries"] += knowledge_entry_count
            totals["open_changes"] += open_change_count
            totals["review_queue"] += review_queue_count
            totals["export_ready_projects"] += 1 if export_ready else 0
            totals["blocked_projects"] += 1 if blocker_count else 0

            readiness_score = self._score_project_delivery(
                document_count=document_count,
                source_file_count=source_file_count,
                knowledge_entry_count=knowledge_entry_count,
                blocker_count=blocker_count,
                review_queue_count=review_queue_count,
                export_ready=export_ready,
                source_status=str(source_coverage.get("status") or ""),
            )
            primary_action = next_actions[0] if next_actions else {
                "code": "open_project",
                "label": "打开项目",
                "description": "查看项目交付驾驶舱。",
                "href": f"/projects/{project.id}",
                "priority": "low",
            }

            project_digests.append(
                {
                    "project_id": project.id,
                    "name": project.name,
                    "status": project.status or "active",
                    "updated_at": project.updated_at,
                    "readiness_score": readiness_score,
                    "readiness_label": self._readiness_label(readiness_score),
                    "blocker_count": blocker_count,
                    "document_count": document_count,
                    "source_file_count": source_file_count,
                    "knowledge_entry_count": knowledge_entry_count,
                    "open_change_count": open_change_count,
                    "review_queue_count": review_queue_count,
                    "export_ready": export_ready,
                    "delivery_phase_key": delivery_phase["key"],
                    "delivery_phase_label": delivery_phase["label"],
                    "release_gate_status": release_gate_status,
                    "next_action_label": primary_action.get("label", "打开项目"),
                    "next_action_href": primary_action.get("href", f"/projects/{project.id}"),
                    "next_action_priority": primary_action.get("priority", "medium"),
                }
            )

            operating_plan.append(
                {
                    "project_id": project.id,
                    "project_name": project.name,
                    "phase_key": delivery_phase["key"],
                    "phase_label": delivery_phase["label"],
                    "action_code": primary_action.get("code", "open_project"),
                    "action_label": primary_action.get("label", "打开项目"),
                    "action_description": primary_action.get("description", ""),
                    "action_href": primary_action.get("href", f"/projects/{project.id}"),
                    "priority": primary_action.get("priority", "medium"),
                    "status": "passed" if release_gate_status == "passed" else "blocked" if blocker_count else "attention",
                }
            )

            for action in next_actions[:3]:
                critical_actions.append(
                    {
                        "project_id": project.id,
                        "project_name": project.name,
                        "code": action.get("code", "next_action"),
                        "label": action.get("label", "处理项目动作"),
                        "description": action.get("description", ""),
                        "href": action.get("href", f"/projects/{project.id}"),
                        "priority": action.get("priority", "medium"),
                    }
                )

        project_digests.sort(key=lambda item: (item["readiness_score"], -item["blocker_count"]))
        critical_actions.sort(key=lambda item: self._priority_rank(item.get("priority", "medium")))
        operating_plan.sort(
            key=lambda item: (
                self._priority_rank(item.get("priority", "medium")),
                self._phase_rank(item.get("phase_key", "intake")),
                item.get("project_name", ""),
            )
        )
        readiness_score = self._score_system_delivery(totals)
        module_health = self._build_system_module_health(totals)
        capability_counts = await self._get_system_capability_counts(tenant_id)
        completion_capabilities = self._build_completion_capabilities(totals, capability_counts)
        completion_gaps = self._build_completion_gaps(completion_capabilities)
        completion_score = (
            int(sum(item["score"] for item in completion_capabilities) / len(completion_capabilities))
            if completion_capabilities
            else 0
        )
        production_gate = self._build_production_gate(completion_capabilities)
        milestone_portfolio = (
            await self._build_milestone_portfolio(tenant_id=tenant_id, projects=projects)
            if projects
            else self._empty_milestone_portfolio()
        )

        return {
            "generated_at": datetime.now(timezone.utc),
            "readiness_score": readiness_score,
            "totals": totals,
            "module_health": module_health,
            "projects": project_digests,
            "critical_actions": critical_actions[:10],
            "phase_summary": self._build_phase_summary(phase_stats),
            "release_gates": self._build_release_gates(gate_stats, int(total_projects or 0)),
            "operating_plan": operating_plan[:12],
            "completion_capabilities": completion_capabilities,
            "completion_gaps": completion_gaps,
            "completion_score": completion_score,
            "production_gate": production_gate,
            "milestone_portfolio": milestone_portfolio,
        }

    async def _build_milestone_portfolio(
        self,
        *,
        tenant_id: UUID,
        projects: list[Project],
    ) -> dict[str, Any]:
        """Aggregate milestone risks and owner load for visible projects only."""
        project_names = {project.id: project.name for project in projects}
        milestone_result = await self.db.scalars(
            select(ProjectMilestone).where(
                ProjectMilestone.tenant_id == tenant_id,
                ProjectMilestone.project_id.in_(project_names),
            )
        )
        milestone_values = milestone_result.all()
        if inspect.isawaitable(milestone_values):
            milestone_values = await milestone_values
        milestones = list(milestone_values or [])
        if not milestones:
            return self._empty_milestone_portfolio()

        owner_ids = {item.owner_id for item in milestones if item.owner_id}
        owners = {}
        if owner_ids:
            owner_result = await self.db.scalars(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.id.in_(owner_ids),
                    User.deleted_at.is_(None),
                )
            )
            owner_values = owner_result.all()
            if inspect.isawaitable(owner_values):
                owner_values = await owner_values
            owners = {user.id: user.full_name or user.email for user in (owner_values or [])}
        now = datetime.now(timezone.utc)
        status_counts = dict(Counter(item.status for item in milestones))
        digests: list[dict[str, Any]] = []
        owner_stats: dict[UUID | None, dict[str, Any]] = {}
        for milestone in milestones:
            due_at = milestone.due_at
            comparable_due = (
                due_at.replace(tzinfo=timezone.utc)
                if due_at is not None and due_at.tzinfo is None
                else due_at
            )
            is_overdue = bool(
                comparable_due and comparable_due < now and milestone.status != "completed"
            )
            gate_blocker_count = sum(
                item.get("status") == "blocked" for item in (milestone.gate_results_json or [])
            )
            owner_name = owners.get(milestone.owner_id, "未分配")
            digest = {
                "milestone_id": milestone.id,
                "project_id": milestone.project_id,
                "project_name": project_names.get(milestone.project_id, ""),
                "title": milestone.title,
                "status": milestone.status,
                "priority": milestone.priority,
                "owner_id": milestone.owner_id,
                "owner_name": owner_name,
                "due_at": milestone.due_at,
                "is_overdue": is_overdue,
                "gate_blocker_count": gate_blocker_count,
                "action_href": f"/projects/{milestone.project_id}/plan",
            }
            digests.append(digest)
            owner = owner_stats.setdefault(
                milestone.owner_id,
                {
                    "owner_id": milestone.owner_id,
                    "owner_name": owner_name,
                    "active_count": 0,
                    "blocked_count": 0,
                    "overdue_count": 0,
                    "projects": set(),
                    "action_href": "/collaboration",
                },
            )
            if milestone.status != "completed":
                owner["active_count"] += 1
                owner["projects"].add(milestone.project_id)
            if milestone.status == "blocked" or gate_blocker_count:
                owner["blocked_count"] += 1
            if is_overdue:
                owner["overdue_count"] += 1

        priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        active = [item for item in digests if item["status"] != "completed"]

        def due_sort_value(item: dict[str, Any]) -> datetime:
            value = item["due_at"]
            if value is None:
                return datetime.max.replace(tzinfo=timezone.utc)
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

        active.sort(
            key=lambda item: (
                not item["is_overdue"],
                item["due_at"] is None,
                due_sort_value(item),
                priority_rank.get(item["priority"], 9),
                item["project_name"],
            )
        )
        blocked = [
            item for item in active
            if item["status"] == "blocked" or item["gate_blocker_count"] > 0
        ]
        owner_load = []
        for item in owner_stats.values():
            item["project_count"] = len(item.pop("projects"))
            if item["active_count"]:
                owner_load.append(item)
        owner_load.sort(
            key=lambda item: (
                -item["overdue_count"],
                -item["blocked_count"],
                -item["active_count"],
                item["owner_name"],
            )
        )
        return {
            "totals": {
                "total": len(milestones),
                "active": len(active),
                "completed": status_counts.get("completed", 0),
                "blocked": len(blocked),
                "overdue": sum(item["is_overdue"] for item in active),
                "unassigned": sum(item["owner_id"] is None for item in active),
            },
            "status_counts": status_counts,
            "upcoming": active[:12],
            "blocked": blocked[:12],
            "owner_load": owner_load[:12],
        }

    @staticmethod
    def _empty_milestone_portfolio() -> dict[str, Any]:
        return {
            "totals": {
                "total": 0,
                "active": 0,
                "completed": 0,
                "blocked": 0,
                "overdue": 0,
                "unassigned": 0,
            },
            "status_counts": {},
            "upcoming": [],
            "blocked": [],
            "owner_load": [],
        }

    async def _get_system_capability_counts(self, tenant_id: UUID) -> dict[str, int]:
        """Collect cross-domain counts used by the system completion matrix."""
        from app.domains.agent.models import AgentProfile, AgentSkill, WorkflowDefinition
        from app.domains.collaboration.models import CollaborationWorkItem, WorkItemStatus
        from app.domains.export.models import ExportJob
        from app.domains.identity.models import AuditLog
        from app.domains.integrations.models import (
            IntegrationProjectBinding,
            IntegrationProvider,
            IntegrationSyncedAsset,
            IntegrationSyncRun,
        )
        from app.domains.notifications.models import NotificationPreference, UserNotification
        from app.domains.ops.models import AlertRule, MetricEvent, NotificationEvent, QuotaUsage
        from app.domains.providers.models import Provider
        from app.domains.templates.models import Template, TemplateSection, TemplateVersion
        from app.models.identity import Role, User

        async def count(query) -> int:
            result = await self.db.execute(query)
            value = result.scalar_one_or_none()
            if inspect.isawaitable(value):
                value = await value
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        return {
            "published_skills": await count(
                select(func.count(AgentSkill.id)).where(
                    AgentSkill.tenant_id == tenant_id,
                    AgentSkill.status == "published",
                    AgentSkill.deleted_at.is_(None),
                )
            ),
            "active_agents": await count(
                select(func.count(AgentProfile.id)).where(
                    AgentProfile.tenant_id == tenant_id,
                    AgentProfile.status == "active",
                    AgentProfile.deleted_at.is_(None),
                )
            ),
            "active_workflows": await count(
                select(func.count(WorkflowDefinition.id)).where(
                    WorkflowDefinition.tenant_id == tenant_id,
                    WorkflowDefinition.is_active == 1,
                    WorkflowDefinition.deleted_at.is_(None),
                )
            ),
            "providers": await count(
                select(func.count(Provider.id)).where(
                    Provider.tenant_id == tenant_id,
                    Provider.deleted_at.is_(None),
                )
            ),
            "live_providers": await count(
                select(func.count(Provider.id)).where(
                    Provider.tenant_id == tenant_id,
                    Provider.status == "active",
                    Provider.deleted_at.is_(None),
                )
            ),
            "active_templates": await count(
                select(func.count(Template.id)).where(
                    Template.tenant_id == tenant_id,
                    Template.is_active == "true",
                    Template.deleted_at.is_(None),
                )
            ),
            "template_versions": await count(
                select(func.count(TemplateVersion.id)).where(
                    TemplateVersion.tenant_id == tenant_id,
                    TemplateVersion.is_active == "true",
                )
            ),
            "template_sections": await count(
                select(func.count(TemplateSection.id)).where(
                    TemplateSection.tenant_id == tenant_id,
                )
            ),
            "completed_exports": await count(
                select(func.count(ExportJob.id)).where(
                    ExportJob.tenant_id == tenant_id,
                    ExportJob.status == "completed",
                )
            ),
            "roles": await count(
                select(func.count(Role.id)).where(
                    Role.tenant_id == tenant_id,
                )
            ),
            "users": await count(
                select(func.count(User.id)).where(
                    User.tenant_id == tenant_id,
                    User.is_active.is_(True),
                )
            ),
            "audit_logs": await count(
                select(func.count(AuditLog.id)).where(
                    AuditLog.tenant_id == tenant_id,
                )
            ),
            "metric_events": await count(
                select(func.count(MetricEvent.id)).where(
                    MetricEvent.tenant_id == tenant_id,
                )
            ),
            "quota_usages": await count(
                select(func.count(QuotaUsage.id)).where(
                    QuotaUsage.tenant_id == tenant_id,
                )
            ),
            "active_alert_rules": await count(
                select(func.count(AlertRule.id)).where(
                    AlertRule.tenant_id == tenant_id,
                    AlertRule.is_active.is_(True),
                )
            ),
            "enabled_integrations": await count(
                select(func.count(IntegrationProvider.id)).where(
                    IntegrationProvider.tenant_id == tenant_id,
                    IntegrationProvider.is_enabled.is_(True),
                    IntegrationProvider.deleted_at.is_(None),
                )
            ),
            "integration_bindings": await count(
                select(func.count(IntegrationProjectBinding.id)).where(
                    IntegrationProjectBinding.tenant_id == tenant_id,
                    IntegrationProjectBinding.is_enabled.is_(True),
                    IntegrationProjectBinding.deleted_at.is_(None),
                )
            ),
            "completed_sync_runs": await count(
                select(func.count(IntegrationSyncRun.id)).where(
                    IntegrationSyncRun.tenant_id == tenant_id,
                    IntegrationSyncRun.status == "completed",
                )
            ),
            "synced_assets": await count(
                select(func.count(IntegrationSyncedAsset.id)).where(
                    IntegrationSyncedAsset.tenant_id == tenant_id,
                )
            ),
            "collaboration_work_items": await count(
                select(func.count(CollaborationWorkItem.id)).where(
                    CollaborationWorkItem.tenant_id == tenant_id,
                )
            ),
            "completed_work_items": await count(
                select(func.count(CollaborationWorkItem.id)).where(
                    CollaborationWorkItem.tenant_id == tenant_id,
                    CollaborationWorkItem.status == WorkItemStatus.DONE.value,
                )
            ),
            "open_work_items": await count(
                select(func.count(CollaborationWorkItem.id)).where(
                    CollaborationWorkItem.tenant_id == tenant_id,
                    CollaborationWorkItem.status.in_(
                        [
                            WorkItemStatus.OPEN.value,
                            WorkItemStatus.IN_PROGRESS.value,
                            WorkItemStatus.BLOCKED.value,
                        ]
                    ),
                )
            ),
            "blocked_work_items": await count(
                select(func.count(CollaborationWorkItem.id)).where(
                    CollaborationWorkItem.tenant_id == tenant_id,
                    CollaborationWorkItem.status == WorkItemStatus.BLOCKED.value,
                )
            ),
            "overdue_work_items": await count(
                select(func.count(CollaborationWorkItem.id)).where(
                    CollaborationWorkItem.tenant_id == tenant_id,
                    CollaborationWorkItem.status.in_(
                        [
                            WorkItemStatus.OPEN.value,
                            WorkItemStatus.IN_PROGRESS.value,
                            WorkItemStatus.BLOCKED.value,
                        ]
                    ),
                    CollaborationWorkItem.due_at.is_not(None),
                    CollaborationWorkItem.due_at < datetime.now(timezone.utc),
                )
            ),
            "notification_preferences": await count(
                select(func.count(NotificationPreference.id)).where(
                    NotificationPreference.tenant_id == tenant_id,
                )
            ),
            "unacknowledged_notifications": await count(
                select(func.count(UserNotification.id)).where(
                    UserNotification.tenant_id == tenant_id,
                    UserNotification.ack_required.is_(True),
                    UserNotification.acknowledged_at.is_(None),
                    UserNotification.archived_at.is_(None),
                )
            ),
            "escalated_notifications": await count(
                select(func.count(UserNotification.id)).where(
                    UserNotification.tenant_id == tenant_id,
                    UserNotification.ack_required.is_(True),
                    UserNotification.acknowledged_at.is_(None),
                    UserNotification.escalation_level > 0,
                )
            ),
            "notification_deliveries": await count(
                select(func.count(NotificationEvent.id)).where(
                    NotificationEvent.tenant_id == tenant_id,
                )
            ),
            "sent_notification_deliveries": await count(
                select(func.count(NotificationEvent.id)).where(
                    NotificationEvent.tenant_id == tenant_id,
                    NotificationEvent.status == "sent",
                )
            ),
            "failed_notification_deliveries": await count(
                select(func.count(NotificationEvent.id)).where(
                    NotificationEvent.tenant_id == tenant_id,
                    NotificationEvent.status == "failed",
                )
            ),
        }

    @staticmethod
    def _capability_status(score: int) -> str:
        if score >= 85:
            return "ready"
        if score >= 60:
            return "attention"
        return "blocked"

    @classmethod
    def _completion_capability(
        cls,
        *,
        key: str,
        label: str,
        score: int,
        summary: str,
        evidence: dict[str, int | str | bool],
        blockers: list[str],
        action_label: str,
        action_href: str,
    ) -> dict[str, Any]:
        score = max(0, min(100, score))
        return {
            "key": key,
            "label": label,
            "status": cls._capability_status(score),
            "score": score,
            "summary": summary,
            "evidence": evidence,
            "blockers": blockers,
            "action_label": action_label,
            "action_href": action_href,
        }

    @classmethod
    def _build_completion_capabilities(
        cls,
        totals: dict[str, int],
        counts: dict[str, int],
    ) -> list[dict[str, Any]]:
        """Build production completeness status across all core modules."""
        project_count = int(totals.get("projects", 0))
        document_count = int(totals.get("documents", 0))
        source_count = int(totals.get("source_files", 0))
        knowledge_count = int(totals.get("knowledge_entries", 0))
        blocked_projects = int(totals.get("blocked_projects", 0))
        review_queue = int(totals.get("review_queue", 0))
        open_changes = int(totals.get("open_changes", 0))
        export_ready_projects = int(totals.get("export_ready_projects", 0))

        capabilities: list[dict[str, Any]] = []

        doc_score = 0
        doc_score += 25 if project_count else 0
        doc_score += min(document_count * 7, 45)
        doc_score += 30 if project_count and blocked_projects == 0 else max(0, 30 - blocked_projects * 10)
        capabilities.append(
            cls._completion_capability(
                key="project_documents",
                label="项目文档闭环",
                score=doc_score,
                summary=f"{document_count} 份文档，{blocked_projects} 个项目存在阻塞。",
                evidence={
                    "projects": project_count,
                    "documents": document_count,
                    "blocked_projects": blocked_projects,
                },
                blockers=[
                    *([] if project_count else ["尚未创建项目。"]),
                    *([] if document_count else ["尚未生成或沉淀项目交付文档。"]),
                    *([] if blocked_projects == 0 else [f"{blocked_projects} 个项目仍有交付阻塞。"]),
                ],
                action_label="进入项目文档",
                action_href="/projects",
            )
        )

        source_score = 0
        source_score += 40 if source_count else 0
        source_score += 45 if knowledge_count else 0
        source_score += 15 if source_count and knowledge_count else 0
        capabilities.append(
            cls._completion_capability(
                key="source_knowledge",
                label="资料与知识图谱",
                score=source_score,
                summary=f"{source_count} 份资料，{knowledge_count} 条知识。",
                evidence={"source_files": source_count, "knowledge_entries": knowledge_count},
                blockers=[
                    *([] if source_count else ["项目资料尚未进入系统。"]),
                    *([] if knowledge_count else ["知识图谱尚未形成可检索事实。"]),
                ],
                action_label="查看知识图谱",
                action_href="/knowledge/graph",
            )
        )

        orchestration_score = min(counts.get("published_skills", 0) * 12, 36)
        orchestration_score += min(counts.get("active_agents", 0) * 18, 36)
        orchestration_score += min(counts.get("active_workflows", 0) * 14, 28)
        capabilities.append(
            cls._completion_capability(
                key="intelligent_orchestration",
                label="智能编排",
                score=orchestration_score,
                summary=(
                    f"{counts.get('active_agents', 0)} 个活跃 Agent，"
                    f"{counts.get('published_skills', 0)} 个已发布 Skill，"
                    f"{counts.get('active_workflows', 0)} 条工作流。"
                ),
                evidence={
                    "active_agents": counts.get("active_agents", 0),
                    "published_skills": counts.get("published_skills", 0),
                    "active_workflows": counts.get("active_workflows", 0),
                },
                blockers=[
                    *([] if counts.get("published_skills", 0) else ["Skill 市场尚无已发布能力。"]),
                    *([] if counts.get("active_agents", 0) else ["尚无可运行 Agent。"]),
                    *([] if counts.get("active_workflows", 0) else ["尚无活跃工作流。"]),
                ],
                action_label="打开智能编排",
                action_href="/agents",
            )
        )

        template_score = min(counts.get("active_templates", 0) * 15, 35)
        template_score += min(counts.get("template_versions", 0) * 10, 25)
        template_score += min(counts.get("template_sections", 0) * 4, 40)
        capabilities.append(
            cls._completion_capability(
                key="template_governance",
                label="模板与章节治理",
                score=template_score,
                summary=(
                    f"{counts.get('active_templates', 0)} 个模板，"
                    f"{counts.get('template_sections', 0)} 个章节定义。"
                ),
                evidence={
                    "active_templates": counts.get("active_templates", 0),
                    "template_versions": counts.get("template_versions", 0),
                    "template_sections": counts.get("template_sections", 0),
                },
                blockers=[
                    *([] if counts.get("active_templates", 0) else ["尚未配置可复用文档模板。"]),
                    *([] if counts.get("template_sections", 0) else ["模板章节拆分尚未建立。"]),
                ],
                action_label="管理模板",
                action_href="/templates",
            )
        )

        traceability_score = 50 if document_count else 0
        traceability_score += 25 if open_changes == 0 else max(0, 25 - open_changes * 5)
        traceability_score += 25 if review_queue == 0 else max(0, 25 - review_queue * 5)
        capabilities.append(
            cls._completion_capability(
                key="traceability_change",
                label="追溯与变更",
                score=traceability_score,
                summary=f"{open_changes} 个开放变更，{review_queue} 个评审队列项。",
                evidence={"open_changes": open_changes, "review_queue": review_queue},
                blockers=[
                    *([] if document_count else ["没有可追溯的文档资产。"]),
                    *([] if open_changes == 0 else [f"{open_changes} 个变更仍需处理。"]),
                    *([] if review_queue == 0 else [f"{review_queue} 个评审项仍未关闭。"]),
                ],
                action_label="处理追溯变更",
                action_href="/audit",
            )
        )

        export_score = 0
        export_score += 45 if export_ready_projects else 0
        export_score += min(counts.get("completed_exports", 0) * 20, 40)
        export_score += 15 if document_count else 0
        capabilities.append(
            cls._completion_capability(
                key="export_release",
                label="导出发布",
                score=export_score,
                summary=f"{export_ready_projects} 个项目可导出，{counts.get('completed_exports', 0)} 个完成导出任务。",
                evidence={
                    "export_ready_projects": export_ready_projects,
                    "completed_exports": counts.get("completed_exports", 0),
                },
                blockers=[
                    *([] if export_ready_projects else ["尚无项目交付包达到可导出状态。"]),
                    *([] if counts.get("completed_exports", 0) else ["尚无完成的导出任务作为发布证据。"]),
                ],
                action_label="进入导出中心",
                action_href="/exports",
            )
        )

        provider_score = 50 if counts.get("providers", 0) else 0
        provider_score += 50 if counts.get("live_providers", 0) else 0
        capabilities.append(
            cls._completion_capability(
                key="provider_operations",
                label="供应商与模型运维",
                score=provider_score,
                summary=f"{counts.get('providers', 0)} 个供应商，{counts.get('live_providers', 0)} 个活跃供应商。",
                evidence={
                    "providers": counts.get("providers", 0),
                    "live_providers": counts.get("live_providers", 0),
                },
                blockers=[
                    *([] if counts.get("providers", 0) else ["尚未配置供应商。"]),
                    *([] if counts.get("live_providers", 0) else ["尚无活跃供应商可支撑生成闭环。"]),
                ],
                action_label="检查供应商",
                action_href="/providers",
            )
        )

        permission_score = 35 if counts.get("users", 0) else 0
        permission_score += 35 if counts.get("roles", 0) else 0
        permission_score += 30 if counts.get("audit_logs", 0) else 0
        capabilities.append(
            cls._completion_capability(
                key="team_permissions",
                label="团队与权限",
                score=permission_score,
                summary=(
                    f"{counts.get('users', 0)} 个活跃用户，"
                    f"{counts.get('roles', 0)} 个角色，"
                    f"{counts.get('audit_logs', 0)} 条审计记录。"
                ),
                evidence={
                    "users": counts.get("users", 0),
                    "roles": counts.get("roles", 0),
                    "audit_logs": counts.get("audit_logs", 0),
                },
                blockers=[
                    *([] if counts.get("users", 0) else ["尚无活跃用户。"]),
                    *([] if counts.get("roles", 0) else ["尚未配置角色权限。"]),
                    *([] if counts.get("audit_logs", 0) else ["尚无权限或关键操作审计证据。"]),
                ],
                action_label="管理团队权限",
                action_href="/team",
            )
        )

        operations_score = 0
        operations_score += 35 if counts.get("metric_events", 0) else 0
        operations_score += 35 if counts.get("quota_usages", 0) else 0
        operations_score += 30 if counts.get("active_alert_rules", 0) else 0
        capabilities.append(
            cls._completion_capability(
                key="system_operations",
                label="运维监控与审计",
                score=operations_score,
                summary=(
                    f"{counts.get('metric_events', 0)} 条指标，"
                    f"{counts.get('quota_usages', 0)} 条配额，"
                    f"{counts.get('active_alert_rules', 0)} 条告警规则。"
                ),
                evidence={
                    "metric_events": counts.get("metric_events", 0),
                    "quota_usages": counts.get("quota_usages", 0),
                    "active_alert_rules": counts.get("active_alert_rules", 0),
                },
                blockers=[
                    *([] if counts.get("metric_events", 0) else ["尚无运行指标证据。"]),
                    *([] if counts.get("quota_usages", 0) else ["尚无租户配额使用记录。"]),
                    *([] if counts.get("active_alert_rules", 0) else ["尚未配置可用告警规则。"]),
                ],
                action_label="查看运维监控",
                action_href="/system-health",
            )
        )

        integration_score = 0
        integration_score += 25 if counts.get("enabled_integrations", 0) else 0
        integration_score += 25 if counts.get("integration_bindings", 0) else 0
        integration_score += 25 if counts.get("completed_sync_runs", 0) else 0
        integration_score += 25 if counts.get("synced_assets", 0) else 0
        capabilities.append(
            cls._completion_capability(
                key="external_integration_sync",
                label="外部集成同步闭环",
                score=integration_score,
                summary=(
                    f"{counts.get('enabled_integrations', 0)} 个已启用集成，"
                    f"{counts.get('integration_bindings', 0)} 个项目绑定，"
                    f"{counts.get('synced_assets', 0)} 个已同步资产。"
                ),
                evidence={
                    "enabled_integrations": counts.get("enabled_integrations", 0),
                    "integration_bindings": counts.get("integration_bindings", 0),
                    "completed_sync_runs": counts.get("completed_sync_runs", 0),
                    "synced_assets": counts.get("synced_assets", 0),
                },
                blockers=[
                    *([] if counts.get("enabled_integrations", 0) else ["尚未启用外部集成。"]),
                    *([] if counts.get("integration_bindings", 0) else ["外部集成尚未绑定到项目。"]),
                    *([] if counts.get("completed_sync_runs", 0) else ["尚无成功完成的外部同步记录。"]),
                    *([] if counts.get("synced_assets", 0) else ["外部同步尚未落地为项目资料和知识资产。"]),
                ],
                action_label="管理外部集成",
                action_href="/settings?tab=integrations",
            )
        )

        collaboration_score = 20 if counts.get("collaboration_work_items", 0) else 0
        collaboration_score += 30 if counts.get("completed_work_items", 0) else 0
        collaboration_score += 25 if counts.get("blocked_work_items", 0) == 0 else 0
        collaboration_score += 25 if counts.get("overdue_work_items", 0) == 0 else 0
        capabilities.append(
            cls._completion_capability(
                key="collaboration_execution",
                label="协同责任与评审处置",
                score=collaboration_score,
                summary=(
                    f"{counts.get('open_work_items', 0)} 个开放协同事项，"
                    f"{counts.get('blocked_work_items', 0)} 个阻塞，"
                    f"{counts.get('overdue_work_items', 0)} 个逾期。"
                ),
                evidence={
                    "collaboration_work_items": counts.get("collaboration_work_items", 0),
                    "completed_work_items": counts.get("completed_work_items", 0),
                    "open_work_items": counts.get("open_work_items", 0),
                    "blocked_work_items": counts.get("blocked_work_items", 0),
                    "overdue_work_items": counts.get("overdue_work_items", 0),
                },
                blockers=[
                    *([] if counts.get("collaboration_work_items", 0) else ["尚无可追踪的协同责任事项。"]),
                    *([] if counts.get("completed_work_items", 0) else ["尚无完成的协同处置证据。"]),
                    *(
                        []
                        if counts.get("blocked_work_items", 0) == 0
                        else [f"{counts.get('blocked_work_items', 0)} 个协同事项处于阻塞状态。"]
                    ),
                    *(
                        []
                        if counts.get("overdue_work_items", 0) == 0
                        else [f"{counts.get('overdue_work_items', 0)} 个协同事项已经逾期。"]
                    ),
                ],
                action_label="处理协同事项",
                action_href="/collaboration",
            )
        )

        notification_score = 20 if counts.get("notification_preferences", 0) else 0
        notification_score += 20 if counts.get("notification_deliveries", 0) else 0
        notification_score += 20 if counts.get("sent_notification_deliveries", 0) else 0
        notification_score += 20 if counts.get("unacknowledged_notifications", 0) == 0 else 0
        notification_score += (
            20
            if counts.get("escalated_notifications", 0) == 0
            and counts.get("failed_notification_deliveries", 0) == 0
            else 0
        )
        capabilities.append(
            cls._completion_capability(
                key="notification_alert_handling",
                label="通知确认与告警处置",
                score=notification_score,
                summary=(
                    f"{counts.get('unacknowledged_notifications', 0)} 条待确认，"
                    f"{counts.get('escalated_notifications', 0)} 条已升级，"
                    f"{counts.get('failed_notification_deliveries', 0)} 条投递失败。"
                ),
                evidence={
                    "notification_preferences": counts.get("notification_preferences", 0),
                    "unacknowledged_notifications": counts.get("unacknowledged_notifications", 0),
                    "escalated_notifications": counts.get("escalated_notifications", 0),
                    "notification_deliveries": counts.get("notification_deliveries", 0),
                    "sent_notification_deliveries": counts.get("sent_notification_deliveries", 0),
                    "failed_notification_deliveries": counts.get("failed_notification_deliveries", 0),
                },
                blockers=[
                    *([] if counts.get("notification_preferences", 0) else ["尚未配置通知偏好。"]),
                    *([] if counts.get("notification_deliveries", 0) else ["尚无通知投递审计证据。"]),
                    *([] if counts.get("sent_notification_deliveries", 0) else ["尚无成功通知投递证据。"]),
                    *(
                        []
                        if counts.get("unacknowledged_notifications", 0) == 0
                        else [f"{counts.get('unacknowledged_notifications', 0)} 条必确认通知尚未确认。"]
                    ),
                    *(
                        []
                        if counts.get("escalated_notifications", 0) == 0
                        else [f"{counts.get('escalated_notifications', 0)} 条升级通知尚未确认。"]
                    ),
                    *(
                        []
                        if counts.get("failed_notification_deliveries", 0) == 0
                        else [f"{counts.get('failed_notification_deliveries', 0)} 条通知投递失败。"]
                    ),
                ],
                action_label="处理通知与告警",
                action_href="/notifications",
            )
        )

        return capabilities

    @staticmethod
    def _build_production_gate(capabilities: list[dict[str, Any]]) -> dict[str, Any]:
        """Build one strict, actionable production gate from capability evidence."""
        hard_blockers = {
            "notification_alert_handling": (
                "escalated_notifications",
                "failed_notification_deliveries",
            ),
            "collaboration_execution": (
                "blocked_work_items",
                "overdue_work_items",
            ),
        }
        checks: list[dict[str, Any]] = []
        blocking_count = 0
        attention_count = 0
        ready_count = 0

        for capability in capabilities:
            evidence = capability.get("evidence") or {}
            hard_blocked = any(
                int(evidence.get(key, 0) or 0) > 0
                for key in hard_blockers.get(capability["key"], ())
            )
            capability_status = str(capability.get("status") or "blocked")
            gate_status = "blocked" if hard_blocked or capability_status == "blocked" else capability_status
            if gate_status == "blocked":
                blocking_count += 1
            elif gate_status == "attention":
                attention_count += 1
            else:
                ready_count += 1

            if gate_status != "ready":
                checks.append(
                    {
                        "capability_key": capability["key"],
                        "label": capability["label"],
                        "status": gate_status,
                        "score": int(capability.get("score", 0)),
                        "detail": "；".join((capability.get("blockers") or [])[:3]) or capability.get("summary", ""),
                        "action_label": capability["action_label"],
                        "action_href": capability["action_href"],
                    }
                )

        checks.sort(key=lambda item: (0 if item["status"] == "blocked" else 1, item["score"], item["label"]))
        score = (
            int(sum(int(item.get("score", 0)) for item in capabilities) / len(capabilities))
            if capabilities
            else 0
        )
        status = "blocked" if blocking_count else "attention" if attention_count else "passed"
        return {
            "status": status,
            "score": score,
            "production_ready": status == "passed",
            "ready_count": ready_count,
            "attention_count": attention_count,
            "blocking_count": blocking_count,
            "total_count": len(capabilities),
            "checks": checks,
        }

    @staticmethod
    def _build_completion_gaps(capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Flatten blocked capability evidence into an actionable system gap queue."""
        severity_rank = {"critical": 0, "high": 1, "medium": 2}
        gaps: list[dict[str, Any]] = []
        for capability in capabilities:
            score = int(capability.get("score", 0))
            blockers = capability.get("blockers") or []
            if not blockers:
                continue
            severity = "critical" if score < 40 else "high" if score < 70 else "medium"
            gaps.append(
                {
                    "key": f"{capability['key']}_gap",
                    "capability_key": capability["key"],
                    "severity": severity,
                    "title": f"{capability['label']}未闭环",
                    "detail": "；".join(blockers[:3]),
                    "action_label": capability["action_label"],
                    "action_href": capability["action_href"],
                }
            )
        gaps.sort(key=lambda item: (severity_rank.get(item["severity"], 3), item["title"]))
        return gaps[:8]

    @staticmethod
    def _priority_rank(priority: str) -> int:
        return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(priority, 2)

    @staticmethod
    def _phase_rank(phase_key: str) -> int:
        return {"intake": 0, "authoring": 1, "review": 2, "release": 3}.get(phase_key, 1)

    @staticmethod
    def _empty_delivery_phase_stats() -> dict[str, dict[str, Any]]:
        phases = [
            ("intake", "资料导入", "/projects"),
            ("authoring", "文档编写", "/documents"),
            ("review", "评审追溯", "/collaboration"),
            ("release", "导出发布", "/exports"),
        ]
        return {
            key: {
                "key": key,
                "label": label,
                "project_count": 0,
                "blocked_project_count": 0,
                "ready_project_count": 0,
                "action_href": href,
            }
            for key, label, href in phases
        }

    @staticmethod
    def _empty_release_gate_stats() -> dict[str, dict[str, Any]]:
        gates = [
            ("sources_ready", "项目资料就绪", "/projects"),
            ("documents_complete", "核心文档完整", "/documents"),
            ("traceability_clear", "追溯变更清理", "/projects"),
            ("review_clear", "评审协同完成", "/collaboration"),
            ("export_ready", "交付包可导出", "/exports"),
        ]
        return {
            key: {
                "key": key,
                "label": label,
                "passed_count": 0,
                "blockers": [],
                "action_href": href,
            }
            for key, label, href in gates
        }

    @staticmethod
    def _delivery_phase(
        *,
        source_ready: bool,
        documents_complete: bool,
        review_queue_count: int,
        open_change_count: int,
        pending_sync_count: int,
        export_ready: bool,
    ) -> dict[str, str]:
        if not source_ready:
            return {"key": "intake", "label": "资料导入"}
        if not documents_complete:
            return {"key": "authoring", "label": "文档编写"}
        if review_queue_count > 0 or open_change_count > 0 or pending_sync_count > 0:
            return {"key": "review", "label": "评审追溯"}
        if export_ready:
            return {"key": "release", "label": "导出发布"}
        return {"key": "release", "label": "导出发布"}

    @staticmethod
    def _update_release_gate_stats(
        gate_stats: dict[str, dict[str, Any]],
        *,
        project_name: str,
        source_ready: bool,
        documents_complete: bool,
        traceability_clear: bool,
        review_clear: bool,
        export_ready: bool,
    ) -> None:
        gate_values = {
            "sources_ready": (source_ready, "缺少可用项目资料"),
            "documents_complete": (documents_complete, "核心交付文档尚未完整"),
            "traceability_clear": (traceability_clear, "仍有变更或追溯同步待处理"),
            "review_clear": (review_clear, "仍有文档评审队列"),
            "export_ready": (export_ready, "交付包尚不可导出"),
        }
        for key, (passed, blocker) in gate_values.items():
            if passed:
                gate_stats[key]["passed_count"] += 1
            else:
                gate_stats[key]["blockers"].append(f"{project_name}: {blocker}")

    @staticmethod
    def _build_phase_summary(phase_stats: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for key in ("intake", "authoring", "review", "release"):
            phase = phase_stats[key]
            count = int(phase["project_count"])
            blocked_count = int(phase["blocked_project_count"])
            ready_count = int(phase["ready_project_count"])
            if count == 0:
                score = 0
                status = "empty"
            else:
                score = max(
                    0,
                    min(100, int(100 * ready_count / count) if ready_count else 100 - min(blocked_count * 25, 75)),
                )
                status = "healthy" if ready_count == count else "attention" if blocked_count < count else "blocked"
            summaries.append(
                {
                    **phase,
                    "status": status,
                    "score": score,
                    "summary": f"{count} 个项目处于{phase['label']}阶段，{blocked_count} 个存在阻塞。",
                }
            )
        return summaries

    @staticmethod
    def _build_release_gates(
        gate_stats: dict[str, dict[str, Any]],
        total_projects: int,
    ) -> list[dict[str, Any]]:
        total = max(total_projects, 0)
        gates: list[dict[str, Any]] = []
        for key in ("sources_ready", "documents_complete", "traceability_clear", "review_clear", "export_ready"):
            gate = gate_stats[key]
            passed_count = int(gate["passed_count"])
            score = 100 if total == 0 else int(100 * passed_count / total)
            if total == 0:
                status = "empty"
            elif passed_count == total:
                status = "passed"
            else:
                status = "blocked"
            gates.append(
                {
                    **gate,
                    "status": status,
                    "total_count": total,
                    "score": score,
                    "blockers": gate["blockers"][:5],
                }
            )
        return gates

    @staticmethod
    def _readiness_label(score: int) -> str:
        if score >= 85:
            return "可交付"
        if score >= 65:
            return "接近可用"
        if score >= 40:
            return "推进中"
        return "需启动"

    @staticmethod
    def _score_project_delivery(
        *,
        document_count: int,
        source_file_count: int,
        knowledge_entry_count: int,
        blocker_count: int,
        review_queue_count: int,
        export_ready: bool,
        source_status: str,
    ) -> int:
        score = 0
        score += 18 if source_file_count else 0
        score += 18 if knowledge_entry_count else 0
        score += min(document_count * 8, 32)
        score += 18 if export_ready else 0
        score += 8 if source_status in {"ready", "good"} else 0
        score -= min(blocker_count * 10, 40)
        score -= min(review_queue_count * 5, 20)
        return max(0, min(100, score))

    @staticmethod
    def _score_system_delivery(totals: dict[str, int]) -> int:
        project_count = max(totals.get("projects", 0), 1)
        score = 25 if totals.get("source_files", 0) else 0
        score += 20 if totals.get("knowledge_entries", 0) else 0
        score += 25 if totals.get("documents", 0) else 0
        score += int(20 * (totals.get("export_ready_projects", 0) / project_count))
        score -= min(totals.get("blocked_projects", 0) * 12, 35)
        score -= min(totals.get("review_queue", 0) * 4, 20)
        score -= min(totals.get("open_changes", 0) * 3, 15)
        return max(0, min(100, score))

    @staticmethod
    def _build_system_module_health(totals: dict[str, int]) -> list[dict[str, Any]]:
        def module(key: str, label: str, score: int, summary: str, href: str) -> dict[str, Any]:
            if score >= 80:
                status = "healthy"
            elif score >= 50:
                status = "attention"
            else:
                status = "blocked"
            return {
                "key": key,
                "label": label,
                "status": status,
                "score": score,
                "summary": summary,
                "action_href": href,
            }

        project_count = max(totals.get("projects", 0), 1)
        return [
            module(
                "sources",
                "项目资料",
                90 if totals.get("source_files", 0) else 30,
                f"{totals.get('source_files', 0)} 份资料已进入项目。",
                "/projects",
            ),
            module(
                "knowledge",
                "知识图谱",
                90 if totals.get("knowledge_entries", 0) else 35,
                f"{totals.get('knowledge_entries', 0)} 条知识可用于生成和追溯。",
                "/knowledge/graph",
            ),
            module(
                "documents",
                "项目文档",
                85 if totals.get("documents", 0) else 30,
                f"{totals.get('documents', 0)} 份文档处于交付链路中。",
                "/documents",
            ),
            module(
                "review",
                "评审协同",
                max(30, 90 - totals.get("review_queue", 0) * 10),
                f"{totals.get('review_queue', 0)} 份文档仍在评审队列。",
                "/collaboration",
            ),
            module(
                "changes",
                "变更追溯",
                max(30, 90 - totals.get("open_changes", 0) * 8),
                f"{totals.get('open_changes', 0)} 个变更仍需处理。",
                "/projects",
            ),
            module(
                "export",
                "导出交付",
                int(100 * totals.get("export_ready_projects", 0) / project_count),
                f"{totals.get('export_ready_projects', 0)} 个项目达到导出条件。",
                "/exports",
            ),
        ]

    def _build_delivery_next_actions(
        self,
        *,
        project_id: UUID,
        document_total: int,
        source_file_total: int,
        review_queue_count: int,
        pending_sync_total: int,
        failed_file_count: int,
        missing_type_count: int,
        open_change_count: int,
    ) -> list[dict[str, str]]:
        """Create ordered, actionable recommendations for the delivery cockpit."""
        actions: list[dict[str, str]] = []

        def add(code: str, label: str, description: str, href: str, priority: str) -> None:
            actions.append(
                {
                    "code": code,
                    "label": label,
                    "description": description,
                    "href": href,
                    "priority": priority,
                }
            )

        if document_total == 0:
            add(
                "generate_first_document",
                "生成首份项目文档",
                "从 URS 或 BRD 开始建立项目交付链路。",
                f"/projects/{project_id}/documents/generate",
                "high",
            )
        if review_queue_count:
            add(
                "review_documents",
                "处理文档评审",
                "优先处理评审中、退回或待修订的文档。",
                f"/projects/{project_id}/documents",
                "high",
            )
        if pending_sync_total:
            add(
                "review_traceability_sync",
                "处理影响同步",
                "确认上游变更是否需要同步到下游交付物。",
                f"/projects/{project_id}/traceability",
                "high",
            )
        if failed_file_count:
            add(
                "resolve_source_file_failures",
                "处理失败资料",
                "重新上传或检查解析失败的项目资料。",
                f"/projects/{project_id}/files",
                "medium",
            )
        if missing_type_count:
            add(
                "generate_missing_documents",
                "补齐交付文档",
                "生成缺失的 BRD、PRD、设计或测试交付物。",
                f"/projects/{project_id}/documents/generate",
                "medium",
            )
        if source_file_total == 0:
            add(
                "upload_source_files",
                "上传项目资料",
                "先上传招标文件、访谈纪要或现状流程文档。",
                f"/projects/{project_id}/files",
                "medium",
            )
        if open_change_count:
            add(
                "close_change_requests",
                "关闭变更请求",
                "推进待应用或待确认的变更请求。",
                f"/projects/{project_id}/changes",
                "medium",
            )

        if not actions:
            add(
                "open_traceability_matrix",
                "检查可追溯链路",
                "复核项目文档和知识条目的追溯关系。",
                f"/projects/{project_id}/traceability",
                "low",
            )

        return actions[:6]


class ProjectSettingsService:
    """Service for project settings management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_settings(self, project_id: UUID) -> ProjectSettings | None:
        """Get project settings.

        Args:
            project_id: Project UUID

        Returns:
            ProjectSettings if found, None otherwise
        """
        result = await self.db.execute(
            select(ProjectSettings).where(ProjectSettings.project_id == project_id)
        )
        return result.scalar_one_or_none()

    async def upsert_settings(
        self,
        project_id: UUID,
        settings: dict[str, Any],
    ) -> ProjectSettings:
        """Create or update project settings.

        Args:
            project_id: Project UUID
            settings: Settings dictionary

        Returns:
            ProjectSettings
        """
        existing = await self.get_settings(project_id)

        if existing:
            existing.settings_json = settings
            await self.db.flush()
            await self.db.refresh(existing)
            return existing

        new_settings = ProjectSettings(
            project_id=project_id,
            settings_json=settings,
        )
        self.db.add(new_settings)
        await self.db.flush()
        await self.db.refresh(new_settings)
        return new_settings


class SourceFileService:
    """Service for source file management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_source_file(
        self,
        project_id: UUID,
        tenant_id: UUID,
        data: SourceFileCreate,
    ) -> SourceFile:
        """Create a source file record.

        Args:
            project_id: Project UUID
            tenant_id: Tenant UUID
            data: Source file creation data

        Returns:
            Created SourceFile
        """
        source_file = SourceFile(
            project_id=project_id,
            tenant_id=tenant_id,
            filename=data.filename,
            original_filename=data.original_filename,
            content_type=data.content_type,
            size=str(data.size),  # Store as string
            hash=data.hash,
            storage_path=data.storage_path,
            status=SourceFileStatus.PENDING.value,
            metadata_json=data.metadata,
        )
        self.db.add(source_file)
        await self.db.flush()
        await self.db.refresh(source_file)
        return source_file

    async def get_source_file(
        self,
        file_id: UUID,
        tenant_id: UUID | None = None,
    ) -> SourceFile | None:
        """Get source file by ID.

        Args:
            file_id: Source file UUID
            tenant_id: Optional tenant filter

        Returns:
            SourceFile if found, None otherwise
        """
        query = select(SourceFile).where(
            SourceFile.id == file_id,
            SourceFile.deleted_at.is_(None),
        )
        if tenant_id is not None:
            query = query.where(SourceFile.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_source_files(
        self,
        project_id: UUID,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[SourceFile], int]:
        """List source files for a project.

        Args:
            project_id: Project UUID
            tenant_id: Tenant UUID
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of SourceFiles, total count)
        """
        # Count total
        count_result = await self.db.execute(
            select(func.count(SourceFile.id)).where(
                SourceFile.project_id == project_id,
                SourceFile.tenant_id == tenant_id,
                SourceFile.deleted_at.is_(None),
            )
        )
        total = count_result.scalar()

        # Get paginated results
        result = await self.db.execute(
            select(SourceFile)
            .where(
                SourceFile.project_id == project_id,
                SourceFile.tenant_id == tenant_id,
                SourceFile.deleted_at.is_(None),
            )
            .offset(skip)
            .limit(limit)
            .order_by(SourceFile.created_at.desc())
        )
        files = list(result.scalars().all())

        return files, total

    async def update_source_file(
        self,
        file_id: UUID,
        data: SourceFileUpdate,
        tenant_id: UUID | None = None,
    ) -> SourceFile | None:
        """Update source file status/metadata.

        Args:
            file_id: Source file UUID
            data: Update data
            tenant_id: Optional tenant filter

        Returns:
            Updated SourceFile if found, None otherwise
        """
        source_file = await self.get_source_file(file_id, tenant_id)
        if not source_file:
            return None

        if data.status is not None:
            source_file.status = data.status
        if data.metadata is not None:
            source_file.metadata_json = data.metadata

        await self.db.flush()
        await self.db.refresh(source_file)
        return source_file

    async def ingest_source_file(
        self,
        source_file_id: UUID,
        tenant_id: UUID,
        project_id: UUID,
        storage: Any | None = None,
    ) -> list[Any]:
        """Parse a stored source file, create knowledge entries, and update ingestion metadata."""
        from app.domains.knowledge.service import KnowledgeService

        source_file = await self.get_source_file(source_file_id, tenant_id)
        if not source_file or source_file.project_id != project_id:
            return []

        started_at = datetime.now(timezone.utc)
        source_file.status = SourceFileStatus.PROCESSING.value
        source_file.metadata_json = {
            **(source_file.metadata_json or {}),
            "ingestionStage": "正在解析与知识抽取",
            "ingestionSummary": "系统正在读取原始资料、切分正文并写入知识库。",
            "requiredAction": None,
            "errorMessage": None,
            "ingestionStartedAt": started_at.isoformat(),
        }
        await self.db.flush()

        try:
            knowledge_service = KnowledgeService(self.db)
            entries = await knowledge_service.ingest_source_file(
                source_file_id=source_file.id,
                tenant_id=tenant_id,
                project_id=project_id,
                storage=storage,
            )
        except Exception as exc:
            source_file.status = SourceFileStatus.FAILED.value
            source_file.metadata_json = {
                **(source_file.metadata_json or {}),
                "ingestionStage": "资料读取或解析失败",
                "ingestionSummary": f"{source_file.original_filename} 未能完成知识摄取。",
                "extractedKnowledgeCount": 0,
                "requiredAction": "重新上传资料或确认存储文件可访问",
                "errorMessage": f"{source_file.original_filename}: {exc}",
                "ingestionFinishedAt": datetime.now(timezone.utc).isoformat(),
            }
            await self.db.flush()
            await self.db.refresh(source_file)
            return []

        source_file.status = SourceFileStatus.READY.value
        link_count = 0
        if entries:
            from app.domains.knowledge.models import KnowledgeLink

            entry_ids = [entry.id for entry in entries]
            link_count = (
                await self.db.execute(
                    select(func.count())
                    .select_from(KnowledgeLink)
                    .where(
                        KnowledgeLink.tenant_id == tenant_id,
                        KnowledgeLink.deleted_at.is_(None),
                        KnowledgeLink.source_entry_id.in_(entry_ids),
                        KnowledgeLink.target_entry_id.in_(entry_ids),
                    )
                )
            ).scalar_one()

        count = len(entries)
        source_file.metadata_json = {
            **(source_file.metadata_json or {}),
            "ingestionStage": "已完成解析和知识抽取",
            "ingestionSummary": f"{source_file.original_filename} 已抽取 {count} 条知识条目，可用于文档生成、知识图谱和变更追溯。",
            "extractedKnowledgeCount": count,
            "knowledgeLinkCount": link_count,
            "requiredAction": None,
            "errorMessage": None,
            "ingestionFinishedAt": datetime.now(timezone.utc).isoformat(),
        }
        await self.db.flush()
        await self.db.refresh(source_file)
        return entries

    async def delete_source_file(
        self,
        file_id: UUID,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Soft delete a source file.

        Args:
            file_id: Source file UUID
            tenant_id: Optional tenant filter

        Returns:
            True if deleted, False if not found
        """
        source_file = await self.get_source_file(file_id, tenant_id)
        if not source_file:
            return False

        source_file.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    async def get_file_by_hash(
        self,
        project_id: UUID,
        hash: str,
        tenant_id: UUID,
    ) -> SourceFile | None:
        """Get source file by hash (for deduplication).

        Args:
            project_id: Project UUID
            hash: SHA256 hash
            tenant_id: Tenant UUID

        Returns:
            SourceFile if found, None otherwise
        """
        result = await self.db.execute(
            select(SourceFile).where(
                SourceFile.project_id == project_id,
                SourceFile.hash == hash,
                SourceFile.tenant_id == tenant_id,
                SourceFile.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()
