"""Collaboration Service

Business logic for pessimistic locking, document snapshots, and comments.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.collaboration.models import (
    CollaborationLock,
    CollaborationWorkItem,
    DocumentComment,
    DocumentSnapshot,
    CommentThread,
    LockType,
    SnapshotType,
    ThreadType,
    WorkItemStatus,
)
from app.domains.collaboration.work_item_service import CollaborationWorkItemService
from app.domains.documents.models import Document, DocumentBaseline, DocumentEntity, DocumentStatus, DocumentVersion
from app.domains.identity.models import AuditLog
from app.models.identity import Role, User, UserRole
from app.models.projects import Project
from app.services.audit_service import AuditService


REVIEWABLE_DOCUMENT_STATUSES = {
    DocumentStatus.PENDING_REVIEW.value,
    DocumentStatus.REVIEW.value,
    DocumentStatus.IN_REVIEW.value,
    DocumentStatus.REVISION_REQUIRED.value,
    DocumentStatus.APPROVED.value,
    DocumentStatus.PUBLISHED.value,
}

DOCUMENT_TYPE_LABELS = {
    "urs": "URS",
    "brd": "BRD",
    "prd": "PRD",
    "user_story": "用户故事",
    "detailed_design": "详细设计",
    "interface": "接口说明",
    "data_dictionary": "数据字典",
    "test_case": "测试用例",
}

REVIEW_STATUS_LABELS = {
    "PASSED": "通过验收",
    "BLOCKED": "退回修订",
    "PASSED_WITH_FOLLOW_UPS": "带跟进项通过",
}


class LockConflictException(Exception):
    """Exception raised when a lock conflict occurs."""

    def __init__(self, message: str, existing_lock: CollaborationLock | None = None):
        self.message = message
        self.existing_lock = existing_lock
        super().__init__(self.message)


class LockNotFoundException(Exception):
    """Exception raised when a lock is not found."""

    pass


class LockExpiredException(Exception):
    """Exception raised when a lock has expired."""

    pass


class LockManager:
    """Manager for pessimistic resource locking.

    Provides exclusive and shared lock semantics with configurable TTL.
    - Exclusive locks: Only one user can hold this lock on a resource
    - Shared locks: Multiple users can hold shared locks simultaneously
    - Acquiring an exclusive lock invalidates all shared locks on the same resource
    - Locks auto-expire after TTL to prevent stuck locks from crashed sessions
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def acquire_lock(
        self,
        tenant_id: UUID,
        resource_type: str,
        resource_id: UUID,
        user_id: UUID,
        lock_type: str = "exclusive",
        ttl_seconds: int = 300,
    ) -> CollaborationLock:
        """Acquire a lock on a resource.

        Args:
            tenant_id: Tenant UUID
            resource_type: Type of resource (document, section, entity)
            resource_id: UUID of the resource
            user_id: UUID of the user acquiring the lock
            lock_type: "exclusive" or "shared"
            ttl_seconds: Time-to-live in seconds (10-3600)

        Returns:
            Created CollaborationLock

        Raises:
            LockConflictException: If lock cannot be acquired due to conflict
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        # Check for existing locks on this resource
        existing_locks = await self._get_active_locks(tenant_id, resource_type, resource_id)

        if lock_type == LockType.EXCLUSIVE.value:
            # Exclusive lock: cannot coexist with any other lock
            # First, clean up any expired locks
            await self._cleanup_expired_locks(tenant_id, resource_type, resource_id)

            # Re-check after cleanup
            existing_locks = await self._get_active_locks(tenant_id, resource_type, resource_id)

            if existing_locks:
                # There are existing locks - check if user already has one
                user_lock = next((l for l in existing_locks if l.locked_by == user_id), None)
                if user_lock and user_lock.lock_type == LockType.EXCLUSIVE.value:
                    # User already has exclusive lock, refresh it
                    user_lock.expires_at = expires_at
                    user_lock.locked_at = now
                    await self.db.flush()
                    await self.db.refresh(user_lock)
                    return user_lock
                raise LockConflictException(
                    f"Resource is locked by another user",
                    existing_lock=existing_locks[0] if existing_locks else None,
                )

            # Create new exclusive lock
            lock = CollaborationLock(
                tenant_id=tenant_id,
                resource_type=resource_type,
                resource_id=resource_id,
                locked_by=user_id,
                locked_at=now,
                expires_at=expires_at,
                lock_type=LockType.EXCLUSIVE.value,
            )
            self.db.add(lock)
            await self.db.flush()
            await self.db.refresh(lock)
            return lock

        else:  # Shared lock
            # Shared lock: can coexist with other shared locks
            # But exclusive locks block shared lock acquisition
            # First, clean up expired locks
            await self._cleanup_expired_locks(tenant_id, resource_type, resource_id)

            # Re-check after cleanup
            existing_locks = await self._get_active_locks(tenant_id, resource_type, resource_id)

            # Check if there's an exclusive lock
            exclusive_lock = next(
                (l for l in existing_locks if l.lock_type == LockType.EXCLUSIVE.value),
                None,
            )
            if exclusive_lock:
                raise LockConflictException(
                    f"Resource has an exclusive lock",
                    existing_lock=exclusive_lock,
                )

            # Check if user already has a shared lock
            user_shared_lock = next(
                (l for l in existing_locks if l.locked_by == user_id and l.lock_type == LockType.SHARED.value),
                None,
            )
            if user_shared_lock:
                # Refresh existing shared lock
                user_shared_lock.expires_at = expires_at
                user_shared_lock.locked_at = now
                await self.db.flush()
                await self.db.refresh(user_shared_lock)
                return user_shared_lock

            # Create new shared lock
            lock = CollaborationLock(
                tenant_id=tenant_id,
                resource_type=resource_type,
                resource_id=resource_id,
                locked_by=user_id,
                locked_at=now,
                expires_at=expires_at,
                lock_type=LockType.SHARED.value,
            )
            self.db.add(lock)
            await self.db.flush()
            await self.db.refresh(lock)
            return lock

    async def release_lock(
        self,
        lock_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Release a lock.

        Args:
            lock_id: UUID of the lock to release
            tenant_id: Tenant UUID for verification
            user_id: UUID of the user releasing the lock

        Returns:
            True if released, False if not found

        Raises:
            LockNotFoundException: If lock not found
        """
        result = await self.db.execute(
            select(CollaborationLock).where(
                CollaborationLock.id == lock_id,
                CollaborationLock.tenant_id == tenant_id,
                CollaborationLock.locked_by == user_id,
            )
        )
        lock = result.scalar_one_or_none()

        if not lock:
            raise LockNotFoundException(f"Lock not found or not owned by user")

        await self.db.delete(lock)
        await self.db.flush()
        return True

    async def refresh_lock(
        self,
        lock_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        ttl_seconds: int = 300,
    ) -> CollaborationLock:
        """Extend lock TTL.

        Args:
            lock_id: UUID of the lock to refresh
            tenant_id: Tenant UUID for verification
            user_id: UUID of the user refreshing the lock
            ttl_seconds: New TTL in seconds

        Returns:
            Updated CollaborationLock

        Raises:
            LockNotFoundException: If lock not found
            LockExpiredException: If lock has expired
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        result = await self.db.execute(
            select(CollaborationLock).where(
                CollaborationLock.id == lock_id,
                CollaborationLock.tenant_id == tenant_id,
                CollaborationLock.locked_by == user_id,
            )
        )
        lock = result.scalar_one_or_none()

        if not lock:
            raise LockNotFoundException(f"Lock not found or not owned by user")

        if lock.expires_at < now:
            raise LockExpiredException(f"Lock has expired")

        lock.expires_at = expires_at
        lock.locked_at = now
        await self.db.flush()
        await self.db.refresh(lock)
        return lock

    async def get_active_locks(
        self,
        tenant_id: UUID,
        resource_type: str,
        resource_id: UUID,
    ) -> list[CollaborationLock]:
        """Get all active (non-expired) locks on a resource.

        Args:
            tenant_id: Tenant UUID
            resource_type: Type of resource
            resource_id: UUID of the resource

        Returns:
            List of active CollaborationLocks
        """
        # Clean up expired locks first
        await self._cleanup_expired_locks(tenant_id, resource_type, resource_id)

        return await self._get_active_locks(tenant_id, resource_type, resource_id)

    async def _get_active_locks(
        self,
        tenant_id: UUID,
        resource_type: str,
        resource_id: UUID,
    ) -> list[CollaborationLock]:
        """Get active locks without cleanup."""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(CollaborationLock).where(
                CollaborationLock.tenant_id == tenant_id,
                CollaborationLock.resource_type == resource_type,
                CollaborationLock.resource_id == resource_id,
                CollaborationLock.expires_at > now,
            )
        )
        return list(result.scalars().all())

    async def _cleanup_expired_locks(
        self,
        tenant_id: UUID,
        resource_type: str,
        resource_id: UUID,
    ) -> None:
        """Remove expired locks."""
        now = datetime.now(timezone.utc)
        # Delete expired locks
        await self.db.execute(
            CollaborationLock.__table__.delete().where(
                CollaborationLock.tenant_id == tenant_id,
                CollaborationLock.resource_type == resource_type,
                CollaborationLock.resource_id == resource_id,
                CollaborationLock.expires_at <= now,
            )
        )


class CollaborationService:
    """Service for collaboration features including locking, snapshots, and comments."""

    def __init__(self, db: AsyncSession, audit_service: AuditService):
        self.db = db
        self.audit_service = audit_service
        self.lock_manager = LockManager(db)

    async def build_review_hub(
        self,
        tenant_id: UUID | None,
        current_user_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Build the tenant collaboration review command center from real delivery data."""
        work_items = CollaborationWorkItemService(self.db)
        await work_items.ensure_open_comment_work_items(tenant_id)
        users = await self._list_tenant_users(tenant_id)
        role_by_user = await self._role_name_by_user(tenant_id)
        documents = await self._list_reviewable_documents(tenant_id)
        document_ids = [document.id for document in documents]
        project_by_id = await self._project_by_id({document.project_id for document in documents})
        unresolved_by_document = await self._unresolved_comment_count_by_document(document_ids)
        snapshot_count_by_document = await self._snapshot_count_by_document(document_ids)
        baseline_count_by_document = await self._baseline_count_by_document(document_ids)

        pending_by_user: dict[UUID, int] = {}
        focus_by_user: dict[UUID, str] = {}
        for document in documents:
            pending_count = unresolved_by_document.get(document.id, 0)
            if document.created_by:
                pending_by_user[document.created_by] = pending_by_user.get(document.created_by, 0) + max(1, pending_count)
                focus_by_user.setdefault(document.created_by, document.title)

        members = [
            self._member_response(
                user=user,
                role=role_by_user.get(user.id, "项目成员"),
                current_user_id=current_user_id,
                pending_count=pending_by_user.get(user.id, 0),
                current_focus=focus_by_user.get(user.id, "暂无待处理评审"),
            )
            for user in users
        ]

        owner_by_id = {user.id: user for user in users}
        review_queue = [
            self._review_item_response(
                document=document,
                project=project_by_id.get(document.project_id),
                owner=owner_by_id.get(document.created_by),
                owner_role=role_by_user.get(document.created_by, "项目成员"),
                pending_comments=unresolved_by_document.get(document.id, 0),
                snapshot_count=snapshot_count_by_document.get(document.id, 0),
                baseline_count=baseline_count_by_document.get(document.id, 0),
            )
            for document in documents
        ]

        return {
            "members": members,
            "review_queue": review_queue,
            "comment_todos": await work_items.list_comment_todos(tenant_id),
            "recent_activities": await self._recent_activities(tenant_id, owner_by_id, documents),
            "acceptance_decisions": self._acceptance_decisions(review_queue),
        }

    async def build_acceptance_command_center(
        self,
        tenant_id: UUID | None,
        current_user_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Build acceptance release readiness from reviews, comments, and work items."""
        hub = await self.build_review_hub(
            tenant_id=tenant_id,
            current_user_id=current_user_id,
        )
        work_item_stats = await self._work_item_acceptance_stats(tenant_id)
        reviews = hub["review_queue"]
        total_reviews = len(reviews)
        passed_reviews = sum(1 for item in reviews if item["status"] == "PASSED")
        blocked_reviews = sum(1 for item in reviews if item["status"] == "BLOCKED")
        follow_up_reviews = sum(1 for item in reviews if item["status"] == "PASSED_WITH_FOLLOW_UPS")
        pending_comments = sum(int(item["pending_comments"]) for item in reviews)
        active_members = sum(1 for member in hub["members"] if member["status"] in {"online", "pending"})

        summary = {
            "total_reviews": total_reviews,
            "passed_reviews": passed_reviews,
            "blocked_reviews": blocked_reviews,
            "follow_up_reviews": follow_up_reviews,
            "pending_comments": pending_comments,
            "open_work_items": work_item_stats["open_work_items"],
            "overdue_work_items": work_item_stats["overdue_work_items"],
            "unassigned_work_items": work_item_stats["unassigned_work_items"],
            "active_members": active_members,
        }
        risk_items = self._acceptance_risks(summary)
        release_gate = self._acceptance_release_gate(summary, risk_items)

        return {
            "release_gate": release_gate,
            "summary": summary,
            "risk_items": risk_items,
            "priority_actions": self._acceptance_priority_actions(summary),
            "review_queue": reviews[:8],
            "comment_todos": hub["comment_todos"][:8],
            "acceptance_decisions": hub["acceptance_decisions"],
        }

    async def perform_review_action(
        self,
        tenant_id: UUID | None,
        document_id: UUID,
        user_id: UUID,
        action: str,
    ) -> dict[str, Any]:
        """Apply a collaboration review action to a document and return the updated queue item."""
        document = await self._get_review_document(tenant_id, document_id)
        if document is None:
            raise ValueError("Review item not found")

        metadata = dict(document.metadata_json or {})
        review_flow = dict(metadata.get("review_flow") or {})
        old_status = document.status
        new_status = old_status
        audit_metadata: dict[str, Any] = {"action": action, "from_status": old_status}

        if action == "assign-me":
            review_flow["assignee_id"] = str(user_id)
            review_flow["assigned_at"] = datetime.now(timezone.utc).isoformat()
        elif action == "mark-read":
            read_by = dict(review_flow.get("read_by") or {})
            read_by[str(user_id)] = datetime.now(timezone.utc).isoformat()
            review_flow["read_by"] = read_by
        elif action == "pass-acceptance":
            new_status = DocumentStatus.APPROVED.value
            document.approved_by = user_id
            resolved_count = await self._resolve_document_comments(tenant_id, document.id, user_id)
            audit_metadata["resolved_comment_count"] = resolved_count
        elif action == "return-revision":
            new_status = DocumentStatus.REVISION_REQUIRED.value
            review_flow["returned_by"] = str(user_id)
            review_flow["returned_at"] = datetime.now(timezone.utc).isoformat()
        else:
            raise ValueError(f"Unsupported review action '{action}'")

        if new_status != old_status:
            document.status = new_status
            history = list(review_flow.get("status_history") or [])
            history.append(
                {
                    "from_status": old_status,
                    "to_status": new_status,
                    "action": f"collaboration.{action}",
                    "reason": REVIEW_STATUS_LABELS.get(self._review_status(new_status, 0), action),
                    "changed_by": str(user_id),
                    "changed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            review_flow["status_history"] = history

        metadata["review_flow"] = review_flow
        metadata["status"] = document.status
        document.metadata_json = metadata
        await self.db.flush()
        await self.db.refresh(document)
        await CollaborationWorkItemService(self.db).sync_review_action(
            tenant_id=tenant_id,
            document=document,
            actor_id=user_id,
            action=action,
        )

        await self.audit_service.log_action(
            tenant_id=tenant_id,
            user_id=user_id,
            action=f"collaboration.review.{action}",
            resource_type="document",
            resource_id=document.id,
            metadata={**audit_metadata, "to_status": document.status},
        )
        if old_status != document.status:
            from app.domains.notifications.service import UserNotificationService

            await UserNotificationService(self.db).notify_project_members(
                tenant_id=tenant_id,
                project_id=document.project_id,
                actor_id=user_id,
                title="文档评审状态已更新",
                body=f"《{document.title}》已从 {old_status} 更新为 {document.status}。",
                category="document_lifecycle",
                priority="high",
                action_url=f"/projects/{document.project_id}/documents/{document.id}",
                entity_type="document",
                entity_id=document.id,
                dedupe_key=f"collaboration-review:{document.id}:{document.status}:{document.version}",
            )

        owner = await self._get_user(document.created_by)
        role_by_user = await self._role_name_by_user(tenant_id)
        pending_comments = (await self._unresolved_comment_count_by_document([document.id])).get(document.id, 0)
        snapshot_count = (await self._snapshot_count_by_document([document.id])).get(document.id, 0)
        baseline_count = (await self._baseline_count_by_document([document.id])).get(document.id, 0)
        project = (await self._project_by_id({document.project_id})).get(document.project_id)
        return self._review_item_response(
            document=document,
            project=project,
            owner=owner,
            owner_role=role_by_user.get(document.created_by, "项目成员"),
            pending_comments=pending_comments,
            snapshot_count=snapshot_count,
            baseline_count=baseline_count,
        )

    async def _list_tenant_users(self, tenant_id: UUID | None) -> list[User]:
        query = select(User).where(User.deleted_at.is_(None), User.is_active.is_(True))
        if tenant_id is not None:
            query = query.where(User.tenant_id == tenant_id)
        query = query.order_by(User.created_at.asc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def _get_user(self, user_id: UUID | None) -> User | None:
        if user_id is None:
            return None
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def _role_name_by_user(self, tenant_id: UUID | None) -> dict[UUID, str]:
        query = select(UserRole.user_id, Role.name).join(Role, UserRole.role_id == Role.id)
        if tenant_id is not None:
            query = query.where(Role.tenant_id == tenant_id)
        result = await self.db.execute(query)
        role_by_user: dict[UUID, str] = {}
        for user_id, role_name in result.all():
            role_by_user.setdefault(user_id, role_name)
        return role_by_user

    async def _list_reviewable_documents(self, tenant_id: UUID | None) -> list[Document]:
        query = select(Document).where(
            Document.deleted_at.is_(None),
            Document.status.in_(REVIEWABLE_DOCUMENT_STATUSES),
        )
        if tenant_id is not None:
            query = query.where(Document.tenant_id == tenant_id)
        query = query.order_by(Document.updated_at.desc()).limit(50)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def _get_review_document(self, tenant_id: UUID | None, document_id: UUID) -> Document | None:
        query = select(Document).where(Document.id == document_id, Document.deleted_at.is_(None))
        if tenant_id is not None:
            query = query.where(Document.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def _project_by_id(self, project_ids: set[UUID]) -> dict[UUID, Project]:
        if not project_ids:
            return {}
        result = await self.db.execute(select(Project).where(Project.id.in_(project_ids)))
        return {project.id: project for project in result.scalars().all()}

    async def _unresolved_comment_count_by_document(self, document_ids: list[UUID]) -> dict[UUID, int]:
        if not document_ids:
            return {}
        result = await self.db.execute(
            select(DocumentComment.document_id, func.count(DocumentComment.id))
            .where(
                DocumentComment.document_id.in_(document_ids),
                DocumentComment.deleted_at.is_(None),
                DocumentComment.resolved.is_(False),
            )
            .group_by(DocumentComment.document_id)
        )
        return {document_id: int(count or 0) for document_id, count in result.all()}

    async def _snapshot_count_by_document(self, document_ids: list[UUID]) -> dict[UUID, int]:
        if not document_ids:
            return {}
        result = await self.db.execute(
            select(DocumentSnapshot.document_id, func.count(DocumentSnapshot.id))
            .where(DocumentSnapshot.document_id.in_(document_ids))
            .group_by(DocumentSnapshot.document_id)
        )
        return {document_id: int(count or 0) for document_id, count in result.all()}

    async def _baseline_count_by_document(self, document_ids: list[UUID]) -> dict[UUID, int]:
        if not document_ids:
            return {}
        result = await self.db.execute(
            select(DocumentBaseline.document_id, func.count(DocumentBaseline.id))
            .where(DocumentBaseline.document_id.in_(document_ids))
            .group_by(DocumentBaseline.document_id)
        )
        return {document_id: int(count or 0) for document_id, count in result.all()}

    async def _work_item_acceptance_stats(self, tenant_id: UUID | None) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        open_statuses = [
            WorkItemStatus.OPEN.value,
            WorkItemStatus.IN_PROGRESS.value,
            WorkItemStatus.BLOCKED.value,
        ]
        filters = [CollaborationWorkItem.status.in_(open_statuses)]
        if tenant_id is not None:
            filters.append(CollaborationWorkItem.tenant_id == tenant_id)

        open_count = await self.db.scalar(
            select(func.count(CollaborationWorkItem.id)).where(*filters)
        )
        overdue_count = await self.db.scalar(
            select(func.count(CollaborationWorkItem.id)).where(
                *filters,
                CollaborationWorkItem.due_at.is_not(None),
                CollaborationWorkItem.due_at < now,
            )
        )
        unassigned_count = await self.db.scalar(
            select(func.count(CollaborationWorkItem.id)).where(
                *filters,
                CollaborationWorkItem.assigned_to.is_(None),
            )
        )
        return {
            "open_work_items": int(open_count or 0),
            "overdue_work_items": int(overdue_count or 0),
            "unassigned_work_items": int(unassigned_count or 0),
        }

    def _acceptance_risks(self, summary: dict[str, int]) -> list[dict[str, Any]]:
        risks: list[dict[str, Any]] = []
        if summary["blocked_reviews"]:
            risks.append({
                "code": "blocked_reviews",
                "severity": "critical",
                "title": "存在退回修订评审",
                "detail": "仍有文档处于退回修订或阻塞状态，不能进入正式验收发布。",
                "count": summary["blocked_reviews"],
                "href": "/collaboration",
            })
        if summary["pending_comments"]:
            risks.append({
                "code": "pending_comments",
                "severity": "high",
                "title": "评论待办未关闭",
                "detail": "验收前需要关闭或明确转为跟进项，避免发布后责任不清。",
                "count": summary["pending_comments"],
                "href": "/collaboration",
            })
        if summary["follow_up_reviews"]:
            risks.append({
                "code": "follow_up_reviews",
                "severity": "medium",
                "title": "存在带跟进项通过的评审",
                "detail": "需要确认跟进项责任人、截止时间和是否影响发布。",
                "count": summary["follow_up_reviews"],
                "href": "/collaboration",
            })
        if summary["overdue_work_items"]:
            risks.append({
                "code": "overdue_work_items",
                "severity": "high",
                "title": "协同工作项已逾期",
                "detail": "逾期工作项需要重新分配或升级处理。",
                "count": summary["overdue_work_items"],
                "href": "/collaboration",
            })
        if summary["unassigned_work_items"]:
            risks.append({
                "code": "unassigned_work_items",
                "severity": "medium",
                "title": "协同工作项待领取",
                "detail": "验收事项缺少责任人会影响交付闭环。",
                "count": summary["unassigned_work_items"],
                "href": "/collaboration",
            })
        return risks

    def _acceptance_release_gate(
        self,
        summary: dict[str, int],
        risk_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        blockers = [
            item["title"]
            for item in risk_items
            if item["severity"] in {"critical", "high"}
        ]
        warnings = [
            item["title"]
            for item in risk_items
            if item["severity"] == "medium"
        ]
        if blockers:
            return {
                "status": "blocked",
                "label": "验收阻断",
                "summary": "协同验收仍存在必须关闭的评审、评论或工作项阻断。",
                "blockers": blockers,
                "warnings": warnings,
            }
        if warnings or summary["open_work_items"]:
            return {
                "status": "attention",
                "label": "需复核",
                "summary": "没有硬阻断，但仍有跟进项或工作项需要发布前确认。",
                "blockers": [],
                "warnings": warnings or ["仍有协同工作项需要确认"],
            }
        return {
            "status": "passed",
            "label": "可进入验收发布",
            "summary": "评审、评论和协同工作项均满足验收发布条件。",
            "blockers": [],
            "warnings": [],
        }

    def _acceptance_priority_actions(self, summary: dict[str, int]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        if summary["blocked_reviews"] or summary["pending_comments"]:
            actions.append({
                "code": "close_review_blockers",
                "title": "关闭评审与评论阻断",
                "description": "处理退回修订、未解决评论和验收前必须确认的文档问题。",
                "href": "/collaboration",
                "priority": "critical" if summary["blocked_reviews"] else "high",
            })
        if summary["unassigned_work_items"] or summary["overdue_work_items"]:
            actions.append({
                "code": "assign_work_items",
                "title": "分配并推进协同工作项",
                "description": "为待领取或逾期工作项明确责任人和截止时间。",
                "href": "/collaboration",
                "priority": "high" if summary["overdue_work_items"] else "medium",
            })
        if summary["follow_up_reviews"]:
            actions.append({
                "code": "confirm_follow_ups",
                "title": "确认带跟进项通过的评审",
                "description": "确认跟进项不会阻断发布，或转为发布后责任清单。",
                "href": "/collaboration",
                "priority": "medium",
            })
        if not actions:
            actions.append({
                "code": "preserve_acceptance_evidence",
                "title": "保留验收证据",
                "description": "保留评审决策、评论关闭记录和协同活动，作为发布附件。",
                "href": "/collaboration",
                "priority": "medium",
            })
        return actions

    async def _resolve_document_comments(
        self,
        tenant_id: UUID | None,
        document_id: UUID,
        user_id: UUID,
    ) -> int:
        query = select(DocumentComment).where(
            DocumentComment.document_id == document_id,
            DocumentComment.deleted_at.is_(None),
            DocumentComment.resolved.is_(False),
        )
        if tenant_id is not None:
            query = query.where(DocumentComment.tenant_id == tenant_id)
        result = await self.db.execute(query)
        comments = list(result.scalars().all())
        for comment in comments:
            comment.resolved = True
        if comments:
            await self.audit_service.log_action(
                tenant_id=tenant_id,
                user_id=user_id,
                action="collaboration.comments.bulk_resolve_for_acceptance",
                resource_type="document",
                resource_id=document_id,
                metadata={"count": len(comments)},
            )
        return len(comments)

    async def _recent_activities(
        self,
        tenant_id: UUID | None,
        users_by_id: dict[UUID, User],
        documents: list[Document],
    ) -> list[dict[str, Any]]:
        query = select(AuditLog)
        if tenant_id is not None:
            query = query.where(AuditLog.tenant_id == tenant_id)
        query = query.where(AuditLog.action.like("collaboration.%")).order_by(AuditLog.created_at.desc()).limit(8)
        result = await self.db.execute(query)
        logs = list(result.scalars().all())
        if logs:
            return [
                {
                    "id": str(log.id),
                    "actor": self._user_name(users_by_id.get(log.user_id)),
                    "action": self._activity_label(log.action),
                    "target": log.resource_type or "协同对象",
                    "created_at": log.created_at,
                }
                for log in logs
            ]

        return [
            {
                "id": f"document-{document.id}",
                "actor": self._user_name(users_by_id.get(document.created_by)),
                "action": self._activity_label(f"document.{document.status}"),
                "target": document.title,
                "created_at": document.updated_at,
            }
            for document in documents[:8]
        ]

    def _member_response(
        self,
        *,
        user: User,
        role: str,
        current_user_id: UUID | None,
        pending_count: int,
        current_focus: str,
    ) -> dict[str, Any]:
        status = "online" if current_user_id and user.id == current_user_id else ("pending" if pending_count else "offline")
        return {
            "id": user.id,
            "name": self._user_name(user),
            "email": user.email,
            "role": role,
            "status": status,
            "pending_count": pending_count,
            "current_focus": current_focus,
        }

    def _review_item_response(
        self,
        *,
        document: Document,
        project: Project | None,
        owner: User | None,
        owner_role: str,
        pending_comments: int,
        snapshot_count: int,
        baseline_count: int,
    ) -> dict[str, Any]:
        status = self._review_status(document.status, pending_comments)
        priority = self._review_priority(document.status, pending_comments)
        project_name = project.name if project else "未关联项目"
        return {
            "id": document.id,
            "document_id": document.id,
            "project_id": document.project_id,
            "title": document.title,
            "document_type": DOCUMENT_TYPE_LABELS.get(document.doc_type, document.doc_type.upper()),
            "owner": self._user_name(owner),
            "role": owner_role,
            "status": status,
            "priority": priority,
            "pending_comments": pending_comments,
            "snapshot_count": snapshot_count,
            "baseline_count": baseline_count,
            "updated_at": document.updated_at,
            "summary": self._review_summary(document, project_name, pending_comments, snapshot_count, baseline_count),
            "acceptance_decision": REVIEW_STATUS_LABELS[status],
            "action_href": f"/projects/{document.project_id}/documents/{document.id}",
        }

    def _review_status(self, document_status: str, pending_comments: int) -> str:
        if document_status == DocumentStatus.REVISION_REQUIRED.value:
            return "BLOCKED"
        if document_status in {DocumentStatus.APPROVED.value, DocumentStatus.PUBLISHED.value}:
            return "PASSED" if pending_comments == 0 else "PASSED_WITH_FOLLOW_UPS"
        if pending_comments >= 5:
            return "BLOCKED"
        return "PASSED_WITH_FOLLOW_UPS"

    def _review_priority(self, document_status: str, pending_comments: int) -> str:
        if document_status == DocumentStatus.REVISION_REQUIRED.value or pending_comments >= 5:
            return "critical"
        if pending_comments >= 2:
            return "high"
        if pending_comments == 1:
            return "medium"
        return "low"

    def _review_summary(
        self,
        document: Document,
        project_name: str,
        pending_comments: int,
        snapshot_count: int,
        baseline_count: int,
    ) -> str:
        evidence = f"{snapshot_count} 个快照，{baseline_count} 条基线"
        if document.status == DocumentStatus.REVISION_REQUIRED.value:
            return f"{project_name} 的 {document.title} 已退回修订，仍有 {pending_comments} 条评论需要关闭，当前证据为 {evidence}。"
        if pending_comments:
            return f"{project_name} 的 {document.title} 还有 {pending_comments} 条未解决评论，验收前需要确认跟进项，当前证据为 {evidence}。"
        return f"{project_name} 的 {document.title} 已具备验收条件，当前证据为 {evidence}。"

    def _comment_todos(self, review_queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
        todos = []
        for item in review_queue:
            if item["pending_comments"] <= 0:
                continue
            due = "今天 18:00" if item["priority"] in {"critical", "high"} else "明天 12:00"
            todos.append(
                {
                    "id": f"comment-todo-{item['document_id']}",
                    "document_id": item["document_id"],
                    "document_title": item["title"],
                    "assignee": item["owner"],
                    "count": item["pending_comments"],
                    "due": due,
                    "action_href": item["action_href"],
                }
            )
        return todos

    def _acceptance_decisions(self, review_queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts = {status: 0 for status in REVIEW_STATUS_LABELS}
        for item in review_queue:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        return [
            {"id": f"decision-{status.lower()}", "label": label, "status": status, "count": counts.get(status, 0)}
            for status, label in REVIEW_STATUS_LABELS.items()
        ]

    def _user_name(self, user: User | None) -> str:
        if user is None:
            return "未分配"
        return user.full_name or user.email

    def _activity_label(self, action: str) -> str:
        labels = {
            "collaboration.review.assign-me": "领取评审",
            "collaboration.review.mark-read": "标记评论已读",
            "collaboration.review.pass-acceptance": "通过验收",
            "collaboration.review.return-revision": "退回修订",
            "collaboration.comments.bulk_resolve_for_acceptance": "关闭验收评论",
            "document.approved": "通过文档评审",
            "document.published": "发布交付文档",
            "document.revision_required": "等待修订",
        }
        return labels.get(action, action)

    # Lock operations
    async def acquire_lock(
        self,
        tenant_id: UUID,
        resource_type: str,
        resource_id: UUID,
        user_id: UUID,
        lock_type: str = "exclusive",
        ttl_seconds: int = 300,
    ) -> CollaborationLock:
        """Acquire a lock on a resource.

        Args:
            tenant_id: Tenant UUID
            resource_type: Type of resource
            resource_id: UUID of the resource
            user_id: UUID of the user
            lock_type: "exclusive" or "shared"
            ttl_seconds: TTL in seconds

        Returns:
            Created CollaborationLock
        """
        lock = await self.lock_manager.acquire_lock(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            lock_type=lock_type,
            ttl_seconds=ttl_seconds,
        )

        # Audit log
        await self.audit_service.log_action(
            tenant_id=tenant_id,
            user_id=user_id,
            action="collaboration.lock_acquire",
            resource_type=resource_type,
            resource_id=resource_id,
            metadata={
                "lock_id": str(lock.id),
                "lock_type": lock_type,
                "ttl_seconds": ttl_seconds,
            },
        )

        return lock

    async def release_lock(
        self,
        lock_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Release a lock.

        Args:
            lock_id: UUID of the lock
            tenant_id: Tenant UUID
            user_id: UUID of the user

        Returns:
            True if released
        """
        result = await self.lock_manager.release_lock(lock_id, tenant_id, user_id)

        # Audit log
        await self.audit_service.log_action(
            tenant_id=tenant_id,
            user_id=user_id,
            action="collaboration.lock_release",
            resource_type="collaboration_lock",
            resource_id=lock_id,
        )

        return result

    async def refresh_lock(
        self,
        lock_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        ttl_seconds: int = 300,
    ) -> CollaborationLock:
        """Refresh a lock TTL.

        Args:
            lock_id: UUID of the lock
            tenant_id: Tenant UUID
            user_id: UUID of the user
            ttl_seconds: New TTL

        Returns:
            Updated CollaborationLock
        """
        return await self.lock_manager.refresh_lock(lock_id, tenant_id, user_id, ttl_seconds)

    async def get_active_locks(
        self,
        tenant_id: UUID,
        resource_type: str,
        resource_id: UUID,
    ) -> list[CollaborationLock]:
        """Get active locks on a resource.

        Args:
            tenant_id: Tenant UUID
            resource_type: Type of resource
            resource_id: UUID of the resource

        Returns:
            List of active locks
        """
        return await self.lock_manager.get_active_locks(tenant_id, resource_type, resource_id)

    # Snapshot operations
    async def create_snapshot(
        self,
        tenant_id: UUID,
        document_id: UUID,
        user_id: UUID,
        snapshot_type: str = "manual",
        version: int | None = None,
        draft_data: dict[str, Any] | None = None,
    ) -> DocumentSnapshot:
        """Create a document snapshot.

        Args:
            tenant_id: Tenant UUID
            document_id: UUID of the document
            user_id: UUID of the user creating the snapshot
            snapshot_type: "auto" or "manual"
            version: Optional specific version number (defaults to current)
            draft_data: Optional unsaved title and content captured by editor autosave

        Returns:
            Created DocumentSnapshot
        """
        # Get document for snapshot data
        from app.domains.documents.models import Document

        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
            )
        )
        document = result.scalar_one_or_none()

        if not document:
            raise ValueError(f"Document not found")

        # Build snapshot data
        snapshot_data = {
            "title": document.title,
            "content": document.content,
            "doc_type": document.doc_type,
            "status": document.status,
            "version": version or document.version,
            "metadata": document.metadata_json,
        }
        if draft_data:
            snapshot_data.update(
                {
                    key: draft_data[key]
                    for key in ("title", "content")
                    if key in draft_data
                }
            )

        if snapshot_type == SnapshotType.AUTO.value:
            latest_auto_result = await self.db.execute(
                select(DocumentSnapshot)
                .where(
                    DocumentSnapshot.tenant_id == tenant_id,
                    DocumentSnapshot.document_id == document_id,
                    DocumentSnapshot.snapshot_type == SnapshotType.AUTO.value,
                )
                .order_by(DocumentSnapshot.created_at.desc())
                .limit(1)
            )
            latest_auto = latest_auto_result.scalar_one_or_none()
            if latest_auto and latest_auto.snapshot_data == snapshot_data:
                return latest_auto

        snapshot = DocumentSnapshot(
            tenant_id=tenant_id,
            document_id=document_id,
            user_id=user_id,
            snapshot_data=snapshot_data,
            snapshot_type=snapshot_type,
            version=version or document.version,
        )
        self.db.add(snapshot)
        await self.db.flush()
        await self.db.refresh(snapshot)

        # Audit log
        await self.audit_service.log_action(
            tenant_id=tenant_id,
            user_id=user_id,
            action="collaboration.snapshot_create",
            resource_type="document",
            resource_id=document_id,
            metadata={
                "snapshot_id": str(snapshot.id),
                "snapshot_type": snapshot_type,
                "version": snapshot.version,
            },
        )

        return snapshot

    async def get_snapshots(
        self,
        tenant_id: UUID,
        document_id: UUID,
    ) -> list[DocumentSnapshot]:
        """Get all snapshots for a document.

        Args:
            tenant_id: Tenant UUID
            document_id: UUID of the document

        Returns:
            List of DocumentSnapshots
        """
        result = await self.db.execute(
            select(DocumentSnapshot)
            .where(
                DocumentSnapshot.tenant_id == tenant_id,
                DocumentSnapshot.document_id == document_id,
            )
            .order_by(DocumentSnapshot.created_at.desc())
        )
        return list(result.scalars().all())

    async def restore_snapshot(
        self,
        snapshot_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
    ) -> DocumentSnapshot:
        """Restore a document from a snapshot.

        Args:
            snapshot_id: UUID of the snapshot
            tenant_id: Tenant UUID
            user_id: UUID of the user

        Returns:
            Restored DocumentSnapshot
        """
        result = await self.db.execute(
            select(DocumentSnapshot).where(
                DocumentSnapshot.id == snapshot_id,
                DocumentSnapshot.tenant_id == tenant_id,
            )
        )
        snapshot = result.scalar_one_or_none()

        if not snapshot:
            raise ValueError(f"Snapshot not found")

        # Restore document from snapshot
        from app.domains.documents.models import Document

        doc_result = await self.db.execute(
            select(Document).where(
                Document.id == snapshot.document_id,
                Document.tenant_id == tenant_id,
            )
        )
        document = doc_result.scalar_one_or_none()

        if not document:
            raise ValueError(f"Document not found")

        # Preserve the pre-restore state as a formal version audit record.
        snapshot_data = snapshot.snapshot_data
        previous_version = document.version
        self.db.add(
            DocumentVersion(
                tenant_id=tenant_id,
                document_id=document.id,
                version=previous_version,
                content=document.content,
                changes_summary=f"Before restore from snapshot {snapshot.id}",
                created_by=user_id,
            )
        )

        # Restore editable document data without restoring workflow status.
        document.title = snapshot_data.get("title", document.title)
        document.content = snapshot_data.get("content", document.content)
        document.version = previous_version + 1

        await self.db.flush()

        # Audit log
        await self.audit_service.log_action(
            tenant_id=tenant_id,
            user_id=user_id,
            action="collaboration.snapshot_restore",
            resource_type="document",
            resource_id=snapshot.document_id,
            metadata={
                "snapshot_id": str(snapshot_id),
                "restored_version": document.version,
            },
        )

        return snapshot

    # Comment operations
    async def create_comment(
        self,
        tenant_id: UUID,
        document_id: UUID,
        entity_id: UUID | None,
        user_id: UUID,
        content: str,
        anchor: str | None = None,
        parent_id: UUID | None = None,
    ) -> DocumentComment:
        """Create a document comment.

        Args:
            tenant_id: Tenant UUID
            document_id: UUID of the document
            entity_id: UUID of the entity (null for general comments)
            user_id: UUID of the user
            content: Comment content
            anchor: Human-readable section or paragraph location
            parent_id: UUID of parent comment (for replies)

        Returns:
            Created DocumentComment
        """
        document_result = await self.db.execute(
            select(Document.id).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        if document_result.scalar_one_or_none() is None:
            raise ValueError("Document not found")

        if entity_id is not None:
            entity_result = await self.db.execute(
                select(DocumentEntity).where(
                    DocumentEntity.id == entity_id,
                    DocumentEntity.document_id == document_id,
                    DocumentEntity.tenant_id == tenant_id,
                )
            )
            if entity_result.scalar_one_or_none() is None:
                raise ValueError("Document entity not found")

        normalized_parent_id = parent_id
        if parent_id is not None:
            parent_result = await self.db.execute(
                select(DocumentComment).where(
                    DocumentComment.id == parent_id,
                    DocumentComment.tenant_id == tenant_id,
                    DocumentComment.document_id == document_id,
                    DocumentComment.deleted_at.is_(None),
                )
            )
            parent = parent_result.scalar_one_or_none()
            if parent is None:
                raise ValueError("Parent comment not found")
            thread_root = parent
            if parent.parent_comment_id is not None:
                root_result = await self.db.execute(
                    select(DocumentComment).where(
                        DocumentComment.id == parent.parent_comment_id,
                        DocumentComment.tenant_id == tenant_id,
                        DocumentComment.document_id == document_id,
                        DocumentComment.deleted_at.is_(None),
                    )
                )
                thread_root = root_result.scalar_one_or_none()
                if thread_root is None:
                    raise ValueError("Parent comment thread not found")
            normalized_parent_id = thread_root.id
            entity_id = thread_root.entity_id
            anchor = thread_root.anchor
            thread_root.resolved = False

        comment = DocumentComment(
            tenant_id=tenant_id,
            document_id=document_id,
            entity_id=entity_id,
            user_id=user_id,
            content=content,
            anchor=anchor,
            parent_comment_id=normalized_parent_id,
        )
        self.db.add(comment)
        await self.db.flush()
        await self.db.refresh(comment)

        # Audit log
        await self.audit_service.log_action(
            tenant_id=tenant_id,
            user_id=user_id,
            action="collaboration.comment_create",
            resource_type="document",
            resource_id=document_id,
            metadata={
                "comment_id": str(comment.id),
                "entity_id": str(entity_id) if entity_id else None,
                "anchor": anchor,
                "parent_id": str(normalized_parent_id) if normalized_parent_id else None,
            },
        )
        await CollaborationWorkItemService(self.db).create_from_comment(
            tenant_id=tenant_id,
            comment_id=comment.id,
            actor_id=user_id,
        )

        return comment

    async def update_comment(
        self,
        comment_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        content: str,
    ) -> DocumentComment:
        """Update a document comment.

        Args:
            comment_id: UUID of the comment
            tenant_id: Tenant UUID
            user_id: UUID of the user (must be comment owner)
            content: Updated content

        Returns:
            Updated DocumentComment

        Raises:
            ValueError: If comment not found or user not owner
        """
        result = await self.db.execute(
            select(DocumentComment).where(
                DocumentComment.id == comment_id,
                DocumentComment.tenant_id == tenant_id,
                DocumentComment.deleted_at.is_(None),
            )
        )
        comment = result.scalar_one_or_none()

        if not comment:
            raise ValueError(f"Comment not found")

        if comment.user_id != user_id:
            raise ValueError(f"User not authorized to update this comment")

        comment.content = content
        await self.db.flush()
        await self.db.refresh(comment)

        # Audit log
        await self.audit_service.log_action(
            tenant_id=tenant_id,
            user_id=user_id,
            action="collaboration.comment_update",
            resource_type="document",
            resource_id=comment.document_id,
            metadata={"comment_id": str(comment_id)},
        )

        return comment

    async def resolve_comment(
        self,
        comment_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
    ) -> DocumentComment:
        """Resolve a document comment.

        Args:
            comment_id: UUID of the comment
            tenant_id: Tenant UUID
            user_id: UUID of the user

        Returns:
            Updated DocumentComment

        Raises:
            ValueError: If comment not found
        """
        result = await self.db.execute(
            select(DocumentComment).where(
                DocumentComment.id == comment_id,
                DocumentComment.tenant_id == tenant_id,
                DocumentComment.deleted_at.is_(None),
            )
        )
        comment = result.scalar_one_or_none()

        if not comment:
            raise ValueError(f"Comment not found")

        comment.resolved = True
        replies_result = await self.db.execute(
            select(DocumentComment).where(
                DocumentComment.parent_comment_id == comment.id,
                DocumentComment.tenant_id == tenant_id,
                DocumentComment.deleted_at.is_(None),
            )
        )
        replies = list(replies_result.scalars().all())
        for reply in replies:
            reply.resolved = True
        await self.db.flush()
        await self.db.refresh(comment)

        # Audit log
        await self.audit_service.log_action(
            tenant_id=tenant_id,
            user_id=user_id,
            action="collaboration.comment_resolve",
            resource_type="document",
            resource_id=comment.document_id,
            metadata={"comment_id": str(comment_id), "resolved_reply_count": len(replies)},
        )
        work_items = CollaborationWorkItemService(self.db)
        await work_items.complete_for_comment(tenant_id=tenant_id, comment_id=comment.id)
        for reply in replies:
            await work_items.complete_for_comment(tenant_id=tenant_id, comment_id=reply.id)

        return comment

    async def delete_comment(
        self,
        comment_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Soft delete a document comment.

        Args:
            comment_id: UUID of the comment
            tenant_id: Tenant UUID
            user_id: UUID of the user (must be comment owner)

        Returns:
            True if deleted

        Raises:
            ValueError: If comment not found or user not owner
        """
        result = await self.db.execute(
            select(DocumentComment).where(
                DocumentComment.id == comment_id,
                DocumentComment.tenant_id == tenant_id,
                DocumentComment.deleted_at.is_(None),
            )
        )
        comment = result.scalar_one_or_none()

        if not comment:
            raise ValueError(f"Comment not found")

        if comment.user_id != user_id:
            raise ValueError(f"User not authorized to delete this comment")

        # Soft delete
        comment.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()

        # Audit log
        await self.audit_service.log_action(
            tenant_id=tenant_id,
            user_id=user_id,
            action="collaboration.comment_delete",
            resource_type="document",
            resource_id=comment.document_id,
            metadata={"comment_id": str(comment_id)},
        )

        return True

    async def get_comments(
        self,
        tenant_id: UUID,
        document_id: UUID,
        entity_id: UUID | None = None,
    ) -> list[DocumentComment]:
        """Get comments for a document or entity.

        Args:
            tenant_id: Tenant UUID
            document_id: UUID of the document
            entity_id: Optional UUID of the entity (null for all comments)

        Returns:
            List of DocumentComments
        """
        query = select(DocumentComment).where(
            DocumentComment.tenant_id == tenant_id,
            DocumentComment.document_id == document_id,
            DocumentComment.deleted_at.is_(None),
        )

        if entity_id is not None:
            query = query.where(DocumentComment.entity_id == entity_id)

        query = query.order_by(DocumentComment.created_at.asc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    # Thread operations
    async def create_thread(
        self,
        tenant_id: UUID,
        document_id: UUID,
        thread_type: str = "general",
    ) -> CommentThread:
        """Create a comment thread.

        Args:
            tenant_id: Tenant UUID
            document_id: UUID of the document
            thread_type: "general" or "entity"

        Returns:
            Created CommentThread
        """
        thread = CommentThread(
            tenant_id=tenant_id,
            document_id=document_id,
            thread_type=thread_type,
        )
        self.db.add(thread)
        await self.db.flush()
        await self.db.refresh(thread)
        return thread

    async def get_threads(
        self,
        tenant_id: UUID,
        document_id: UUID,
    ) -> list[CommentThread]:
        """Get all threads for a document.

        Args:
            tenant_id: Tenant UUID
            document_id: UUID of the document

        Returns:
            List of CommentThreads
        """
        result = await self.db.execute(
            select(CommentThread)
            .where(
                CommentThread.tenant_id == tenant_id,
                CommentThread.document_id == document_id,
            )
            .order_by(CommentThread.created_at.asc())
        )
        return list(result.scalars().all())


def create_collaboration_service(db: AsyncSession, audit_service: AuditService) -> CollaborationService:
    """Factory function to create CollaborationService instance.

    Args:
        db: Async SQLAlchemy session
        audit_service: AuditService instance

    Returns:
        CollaborationService instance
    """
    return CollaborationService(db, audit_service)
