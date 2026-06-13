"""Persistent work-item operations for the collaboration domain."""

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.collaboration.models import (
    CollaborationWorkItem,
    DocumentComment,
    WorkItemPriority,
    WorkItemStatus,
    WorkItemType,
)
from app.domains.documents.models import Document
from app.models.identity import User
from app.models.projects import Project, ProjectMember


ACTIVE_STATUSES = {
    WorkItemStatus.OPEN.value,
    WorkItemStatus.IN_PROGRESS.value,
    WorkItemStatus.BLOCKED.value,
}
VALID_STATUSES = {item.value for item in WorkItemStatus}
VALID_PRIORITIES = {item.value for item in WorkItemPriority}
VALID_TYPES = {item.value for item in WorkItemType}
logger = logging.getLogger(__name__)


class CollaborationWorkItemService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_work_item(
        self,
        *,
        tenant_id: UUID,
        created_by: UUID,
        project_id: UUID,
        title: str,
        description: str = "",
        work_type: str = WorkItemType.MANUAL.value,
        priority: str = WorkItemPriority.MEDIUM.value,
        document_id: UUID | None = None,
        comment_id: UUID | None = None,
        assigned_to: UUID | None = None,
        due_at: datetime | None = None,
        source_key: str | None = None,
        metadata: dict | None = None,
        require_creator_membership: bool = True,
    ) -> CollaborationWorkItem:
        if work_type not in VALID_TYPES:
            raise ValueError(f"Unsupported work item type '{work_type}'")
        if priority not in VALID_PRIORITIES:
            raise ValueError(f"Unsupported work item priority '{priority}'")
        if not title.strip():
            raise ValueError("Work item title is required")
        await self._project(project_id, tenant_id)
        if require_creator_membership:
            await self._project_member(created_by, project_id, tenant_id)
        else:
            await self._tenant_user(created_by, tenant_id)
        if assigned_to:
            await self._project_member(assigned_to, project_id, tenant_id)
        if document_id:
            document = await self.db.scalar(
                select(Document).where(
                    Document.id == document_id,
                    Document.tenant_id == tenant_id,
                    Document.deleted_at.is_(None),
                )
            )
            if not document or document.project_id != project_id:
                raise ValueError("Document does not belong to the selected project")
        if comment_id:
            comment = await self.db.scalar(
                select(DocumentComment).where(
                    DocumentComment.id == comment_id,
                    DocumentComment.tenant_id == tenant_id,
                    DocumentComment.deleted_at.is_(None),
                )
            )
            if not comment or document_id is None or comment.document_id != document_id:
                raise ValueError("Comment does not belong to the selected document")
        if source_key:
            existing = await self.db.scalar(
                select(CollaborationWorkItem).where(
                    CollaborationWorkItem.tenant_id == tenant_id,
                    CollaborationWorkItem.source_key == source_key,
                )
            )
            if existing:
                return existing

        item = CollaborationWorkItem(
            tenant_id=tenant_id,
            project_id=project_id,
            document_id=document_id,
            comment_id=comment_id,
            assigned_to=assigned_to,
            created_by=created_by,
            work_type=work_type,
            status=WorkItemStatus.OPEN.value,
            priority=priority,
            title=title.strip(),
            description=description.strip(),
            due_at=due_at,
            source_key=source_key,
            metadata_json=metadata or {},
        )
        if not source_key:
            self.db.add(item)
            await self.db.flush()
            await self._notify_assignee(item, created_by)
            return item

        try:
            async with self.db.begin_nested():
                self.db.add(item)
                await self.db.flush()
        except IntegrityError:
            existing = await self.db.scalar(
                select(CollaborationWorkItem).where(
                    CollaborationWorkItem.tenant_id == tenant_id,
                    CollaborationWorkItem.source_key == source_key,
                )
            )
            if existing:
                return existing
            raise
        await self._notify_assignee(item, created_by)
        return item

    async def list_work_items(
        self,
        tenant_id: UUID,
        current_user_id: UUID,
        *,
        status: str | None = None,
        priority: str | None = None,
        assignment: str = "all",
        project_id: UUID | None = None,
        overdue_only: bool = False,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        now = datetime.now(timezone.utc)
        visibility = self._visible_to(current_user_id, tenant_id)
        filters = [CollaborationWorkItem.tenant_id == tenant_id, visibility]
        if status:
            filters.append(CollaborationWorkItem.status == status)
        if priority:
            filters.append(CollaborationWorkItem.priority == priority)
        if assignment == "mine":
            filters.append(CollaborationWorkItem.assigned_to == current_user_id)
        elif assignment == "unassigned":
            filters.append(CollaborationWorkItem.assigned_to.is_(None))
        if project_id:
            filters.append(CollaborationWorkItem.project_id == project_id)
        if overdue_only:
            filters.extend(
                [
                    CollaborationWorkItem.status.in_(ACTIVE_STATUSES),
                    CollaborationWorkItem.due_at.is_not(None),
                    CollaborationWorkItem.due_at < now,
                ]
            )
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            filters.append(
                or_(
                    CollaborationWorkItem.title.ilike(pattern),
                    CollaborationWorkItem.description.ilike(pattern),
                )
            )

        total = int(
            await self.db.scalar(
                select(func.count()).select_from(CollaborationWorkItem).where(*filters)
            )
            or 0
        )
        items = list(
            (
                await self.db.scalars(
                    select(CollaborationWorkItem)
                    .where(*filters)
                    .order_by(
                        CollaborationWorkItem.due_at.asc().nullslast(),
                        CollaborationWorkItem.created_at.desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        project_ids = {item.project_id for item in items}
        assignee_ids = {item.assigned_to for item in items if item.assigned_to}
        projects = {
            project.id: project
            for project in (
                await self.db.scalars(select(Project).where(Project.id.in_(project_ids)))
            ).all()
        }
        assignees = (
            {
                user.id: user
                for user in (
                    await self.db.scalars(select(User).where(User.id.in_(assignee_ids)))
                ).all()
            }
            if assignee_ids
            else {}
        )
        for item in items:
            project = projects.get(item.project_id)
            assignee = assignees.get(item.assigned_to)
            item.project_name = project.name if project else ""
            item.assigned_to_name = (assignee.full_name or assignee.email) if assignee else None
        mine_count = await self._count(
            tenant_id,
            current_user_id,
            CollaborationWorkItem.assigned_to == current_user_id,
            CollaborationWorkItem.status.in_(ACTIVE_STATUSES),
        )
        unassigned_count = await self._count(
            tenant_id,
            current_user_id,
            CollaborationWorkItem.assigned_to.is_(None),
            CollaborationWorkItem.status.in_(ACTIVE_STATUSES),
        )
        overdue_count = await self._count(
            tenant_id,
            current_user_id,
            CollaborationWorkItem.status.in_(ACTIVE_STATUSES),
            CollaborationWorkItem.due_at.is_not(None),
            CollaborationWorkItem.due_at < now,
        )
        status_counts = {
            item_status: await self._count(
                tenant_id,
                current_user_id,
                CollaborationWorkItem.status == item_status,
            )
            for item_status in VALID_STATUSES
        }
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": page * page_size < total,
            "mine_count": mine_count,
            "unassigned_count": unassigned_count,
            "overdue_count": overdue_count,
            "status_counts": status_counts,
        }

    async def claim(self, work_item_id: UUID, tenant_id: UUID, user_id: UUID) -> CollaborationWorkItem:
        item = await self._owned(work_item_id, tenant_id)
        if item.assigned_to and item.assigned_to != user_id:
            raise PermissionError("Work item is already assigned")
        await self._project_member(user_id, item.project_id, tenant_id)
        item.assigned_to = user_id
        item.status = WorkItemStatus.IN_PROGRESS.value
        item.completed_at = None
        await self.db.flush()
        await self._notify_assignee(item, user_id, event="claimed")
        return item

    async def update_work_item(
        self,
        work_item_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        changes: dict,
    ) -> CollaborationWorkItem:
        item = await self._owned(work_item_id, tenant_id)
        await self._require_manager(item, user_id)
        previous_assignee = item.assigned_to
        if "assigned_to" in changes:
            assigned_to = changes["assigned_to"]
            if assigned_to is not None:
                await self._project_member(assigned_to, item.project_id, tenant_id)
            item.assigned_to = assigned_to
        if changes.get("title") is not None:
            if not str(changes["title"]).strip():
                raise ValueError("Work item title is required")
            item.title = str(changes["title"]).strip()
        if changes.get("description") is not None:
            item.description = str(changes["description"]).strip()
        if changes.get("priority") is not None:
            if changes["priority"] not in VALID_PRIORITIES:
                raise ValueError(f"Unsupported work item priority '{changes['priority']}'")
            item.priority = changes["priority"]
        if changes.get("status") is not None:
            if changes["status"] not in VALID_STATUSES:
                raise ValueError(f"Unsupported work item status '{changes['status']}'")
            item.status = changes["status"]
            item.completed_at = (
                datetime.now(timezone.utc)
                if item.status in {WorkItemStatus.DONE.value, WorkItemStatus.CANCELLED.value}
                else None
            )
        if "due_at" in changes:
            item.due_at = changes["due_at"]
        await self.db.flush()
        if item.assigned_to and item.assigned_to != previous_assignee:
            await self._notify_assignee(item, user_id)
        return item

    async def complete(self, work_item_id: UUID, tenant_id: UUID, user_id: UUID) -> CollaborationWorkItem:
        item = await self._owned(work_item_id, tenant_id)
        await self._require_manager(item, user_id)
        item.status = WorkItemStatus.DONE.value
        item.completed_at = datetime.now(timezone.utc)
        await self.db.flush()
        return item

    async def reopen(self, work_item_id: UUID, tenant_id: UUID, user_id: UUID) -> CollaborationWorkItem:
        item = await self._owned(work_item_id, tenant_id)
        await self._require_manager(item, user_id)
        item.status = WorkItemStatus.OPEN.value
        item.completed_at = None
        await self.db.flush()
        await self._notify_assignee(item, user_id, event="reopened")
        return item

    async def create_from_comment(
        self,
        *,
        tenant_id: UUID,
        comment_id: UUID,
        actor_id: UUID,
    ) -> CollaborationWorkItem | None:
        comment = await self.db.scalar(
            select(DocumentComment).where(
                DocumentComment.id == comment_id,
                DocumentComment.tenant_id == tenant_id,
                DocumentComment.deleted_at.is_(None),
            )
        )
        if not comment:
            return None
        document = await self.db.scalar(
            select(Document).where(
                Document.id == comment.document_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        if not document:
            return None
        project = await self._project(document.project_id, tenant_id)
        assigned_to = document.created_by if document.created_by != actor_id else project.owner_id
        if assigned_to == actor_id:
            assigned_to = None
        item = await self.create_work_item(
            tenant_id=tenant_id,
            created_by=actor_id,
            project_id=document.project_id,
            document_id=document.id,
            comment_id=comment.id,
            assigned_to=assigned_to,
            title=f"处理《{document.title}》评审评论",
            description=comment.content,
            work_type=WorkItemType.COMMENT_RESOLUTION.value,
            priority=WorkItemPriority.HIGH.value,
            source_key=f"comment:{comment.id}",
            metadata={"comment_anchor": comment.anchor, "comment_author_id": str(comment.user_id)},
            require_creator_membership=False,
        )
        if item.status in {WorkItemStatus.DONE.value, WorkItemStatus.CANCELLED.value}:
            item.status = WorkItemStatus.OPEN.value
            item.completed_at = None
            await self.db.flush()
        return item

    async def complete_for_comment(
        self,
        *,
        tenant_id: UUID,
        comment_id: UUID,
    ) -> CollaborationWorkItem | None:
        item = await self.db.scalar(
            select(CollaborationWorkItem).where(
                CollaborationWorkItem.tenant_id == tenant_id,
                CollaborationWorkItem.source_key == f"comment:{comment_id}",
            )
        )
        if not item:
            return None
        item.status = WorkItemStatus.DONE.value
        item.completed_at = datetime.now(timezone.utc)
        await self.db.flush()
        return item

    async def ensure_open_comment_work_items(self, tenant_id: UUID) -> list[CollaborationWorkItem]:
        comments = list(
            (
                await self.db.scalars(
                    select(DocumentComment).where(
                        DocumentComment.tenant_id == tenant_id,
                        DocumentComment.resolved.is_(False),
                        DocumentComment.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        items: list[CollaborationWorkItem] = []
        for comment in comments:
            item = await self.create_from_comment(
                tenant_id=tenant_id,
                comment_id=comment.id,
                actor_id=comment.user_id,
            )
            if item:
                items.append(item)
        return items

    async def list_comment_todos(self, tenant_id: UUID) -> list[dict]:
        items = list(
            (
                await self.db.scalars(
                    select(CollaborationWorkItem).where(
                        CollaborationWorkItem.tenant_id == tenant_id,
                        CollaborationWorkItem.work_type == WorkItemType.COMMENT_RESOLUTION.value,
                        CollaborationWorkItem.status.in_(ACTIVE_STATUSES),
                    )
                )
            ).all()
        )
        if not items:
            return []

        documents = {
            document.id: document
            for document in (
                await self.db.scalars(
                    select(Document).where(Document.id.in_({item.document_id for item in items if item.document_id}))
                )
            ).all()
        }
        assignee_ids = {item.assigned_to for item in items if item.assigned_to}
        assignees = (
            {
                user.id: user
                for user in (
                    await self.db.scalars(select(User).where(User.id.in_(assignee_ids)))
                ).all()
            }
            if assignee_ids
            else {}
        )
        grouped: dict[UUID, list[CollaborationWorkItem]] = {}
        for item in items:
            if item.document_id:
                grouped.setdefault(item.document_id, []).append(item)

        todos = []
        for document_id, document_items in grouped.items():
            document = documents.get(document_id)
            if not document:
                continue
            due_values = [item.due_at for item in document_items if item.due_at]
            first = document_items[0]
            assignee = assignees.get(first.assigned_to)
            todos.append(
                {
                    "id": f"work-item-{first.id}",
                    "document_id": document_id,
                    "document_title": document.title,
                    "assignee": assignee.full_name or assignee.email if assignee else "未分配",
                    "count": len(document_items),
                    "due": min(due_values).isoformat() if due_values else "未设置截止时间",
                    "action_href": f"/projects/{document.project_id}/documents/{document.id}",
                }
            )
        return sorted(todos, key=lambda item: (-item["count"], item["document_title"]))

    async def sync_review_action(
        self,
        *,
        tenant_id: UUID,
        document: Document,
        actor_id: UUID,
        action: str,
    ) -> None:
        review_source = f"review:{document.id}"
        review_item = await self.db.scalar(
            select(CollaborationWorkItem).where(
                CollaborationWorkItem.tenant_id == tenant_id,
                CollaborationWorkItem.source_key == review_source,
            )
        )
        if action == "assign-me":
            if review_item is None:
                review_item = await self.create_work_item(
                    tenant_id=tenant_id,
                    created_by=actor_id,
                    project_id=document.project_id,
                    document_id=document.id,
                    assigned_to=actor_id,
                    title=f"评审《{document.title}》",
                    work_type=WorkItemType.REVIEW.value,
                    priority=WorkItemPriority.HIGH.value,
                    source_key=review_source,
                )
            review_item.assigned_to = actor_id
            review_item.status = WorkItemStatus.IN_PROGRESS.value
            review_item.completed_at = None
        elif action == "pass-acceptance":
            items = list(
                (
                    await self.db.scalars(
                        select(CollaborationWorkItem).where(
                            CollaborationWorkItem.tenant_id == tenant_id,
                            CollaborationWorkItem.document_id == document.id,
                            CollaborationWorkItem.status.in_(ACTIVE_STATUSES),
                        )
                    )
                ).all()
            )
            for item in items:
                item.status = WorkItemStatus.DONE.value
                item.completed_at = datetime.now(timezone.utc)
        elif action == "return-revision":
            follow_up = await self.create_work_item(
                tenant_id=tenant_id,
                created_by=actor_id,
                project_id=document.project_id,
                document_id=document.id,
                assigned_to=document.created_by,
                title=f"修订《{document.title}》",
                description="文档评审已退回，请完成修订并重新提交评审。",
                work_type=WorkItemType.FOLLOW_UP.value,
                priority=WorkItemPriority.HIGH.value,
                source_key=f"follow-up:{document.id}",
            )
            follow_up.status = WorkItemStatus.BLOCKED.value
            follow_up.completed_at = None
        await self.db.flush()

    async def _count(self, tenant_id: UUID, current_user_id: UUID, *clauses) -> int:
        return int(
            await self.db.scalar(
                select(func.count())
                .select_from(CollaborationWorkItem)
                .where(
                    CollaborationWorkItem.tenant_id == tenant_id,
                    self._visible_to(current_user_id, tenant_id),
                    *clauses,
                )
            )
            or 0
        )

    def _visible_to(self, user_id: UUID, tenant_id: UUID):
        owns_project = exists(
            select(Project.id).where(
                Project.id == CollaborationWorkItem.project_id,
                Project.tenant_id == tenant_id,
                Project.owner_id == user_id,
            )
        )
        is_project_member = exists(
            select(ProjectMember.project_id).where(
                ProjectMember.project_id == CollaborationWorkItem.project_id,
                ProjectMember.user_id == user_id,
            )
        )
        return or_(owns_project, is_project_member)

    async def _owned(self, work_item_id: UUID, tenant_id: UUID) -> CollaborationWorkItem:
        item = await self.db.scalar(
            select(CollaborationWorkItem).where(
                CollaborationWorkItem.id == work_item_id,
                CollaborationWorkItem.tenant_id == tenant_id,
            )
        )
        if not item:
            raise ValueError("Work item not found")
        return item

    async def _project(self, project_id: UUID, tenant_id: UUID) -> Project:
        project = await self.db.scalar(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        if not project:
            raise ValueError("Project not found")
        return project

    async def _project_member(self, user_id: UUID, project_id: UUID, tenant_id: UUID) -> User:
        user = await self._tenant_user(user_id, tenant_id)
        project = await self._project(project_id, tenant_id)
        membership = await self.db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        if project.owner_id != user_id and not membership:
            raise PermissionError("User must be an active project member")
        return user

    async def _tenant_user(self, user_id: UUID, tenant_id: UUID) -> User:
        user = await self.db.scalar(
            select(User).where(
                User.id == user_id,
                User.tenant_id == tenant_id,
                User.deleted_at.is_(None),
            )
        )
        if not user:
            raise PermissionError("User must be an active tenant user")
        return user

    async def _require_manager(self, item: CollaborationWorkItem, user_id: UUID) -> None:
        if user_id in {item.assigned_to, item.created_by}:
            return
        project = await self._project(item.project_id, item.tenant_id)
        if project.owner_id == user_id:
            return
        raise PermissionError("User cannot manage this work item")

    async def _notify_assignee(
        self,
        item: CollaborationWorkItem,
        actor_id: UUID,
        *,
        event: str = "assigned",
    ) -> None:
        if not item.assigned_to or item.assigned_to == actor_id:
            return
        event_titles = {
            "assigned": "协同工作项已分派给你",
            "claimed": "协同工作项已领取",
            "reopened": "协同工作项已重开",
        }
        try:
            from app.domains.notifications.service import UserNotificationService

            async with self.db.begin_nested():
                await UserNotificationService(self.db).create_notification(
                    tenant_id=item.tenant_id,
                    user_id=item.assigned_to,
                    actor_id=actor_id,
                    project_id=item.project_id,
                    title=event_titles.get(event, "协同工作项状态已更新"),
                    body=item.title,
                    category="collaboration_work_item",
                    priority="high" if item.priority in {"high", "critical"} else "normal",
                    action_url="/collaboration",
                    entity_type="collaboration_work_item",
                    entity_id=item.id,
                    dedupe_key=f"work-item:{item.id}:{event}:{item.assigned_to}",
                )
        except Exception:
            logger.exception("Failed to notify assignee for collaboration work item %s", item.id)
