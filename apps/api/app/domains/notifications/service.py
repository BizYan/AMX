"""Business service for user-facing in-app notifications."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.notifications.models import NotificationPreference, UserNotification
from app.domains.notifications.schemas import (
    NotificationPreferenceUpdate,
    UserNotificationListResponse,
    UserNotificationResponse,
    UserNotificationSummaryResponse,
)
from app.models.identity import User
from app.models.projects import Project, ProjectMember
from app.domains.documents.models import Document
from app.domains.collaboration.models import DocumentComment


VALID_PRIORITIES = {"low", "normal", "high", "urgent"}
PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "urgent": 3}


def safe_action_url(value: str | None) -> str | None:
    """Allow only local application routes in notifications."""
    if not value:
        return None
    if not value.startswith("/") or value.startswith("//"):
        raise ValueError("Notification action_url must be a local application path")
    return value


class UserNotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_preferences(self, tenant_id: UUID, user_id: UUID) -> NotificationPreference:
        preference = await self.db.scalar(
            select(NotificationPreference).where(
                NotificationPreference.tenant_id == tenant_id,
                NotificationPreference.user_id == user_id,
            )
        )
        if preference:
            return preference
        preference = NotificationPreference(tenant_id=tenant_id, user_id=user_id)
        self.db.add(preference)
        await self.db.flush()
        return preference

    async def update_preferences(
        self,
        tenant_id: UUID,
        user_id: UUID,
        data: NotificationPreferenceUpdate,
    ) -> NotificationPreference:
        preference = await self.get_preferences(tenant_id, user_id)
        changes = data.model_dump(exclude_unset=True)
        if "min_priority" in changes and changes["min_priority"] not in VALID_PRIORITIES:
            raise ValueError(f"Unsupported notification priority '{changes['min_priority']}'")
        if "enabled_categories" in changes:
            changes["enabled_categories"] = sorted(
                {str(category).strip() for category in changes["enabled_categories"] if str(category).strip()}
            )
        for field, value in changes.items():
            setattr(preference, field, value)
        await self.db.flush()
        return preference

    def _allows_preference(
        self,
        preference: NotificationPreference,
        category: str,
        priority: str,
    ) -> bool:
        if priority == "urgent":
            return True
        categories = preference.enabled_categories or []
        if categories and category not in categories:
            return False
        return PRIORITY_RANK[priority] >= PRIORITY_RANK.get(preference.min_priority, 0)

    async def _queue_email_event(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        title: str,
        body: str,
        category: str,
        priority: str,
        action_url: str | None,
        user_notification_id: UUID | None = None,
    ) -> None:
        user = await self.db.scalar(
            select(User).where(
                User.id == user_id,
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
            )
        )
        if not user or not user.email:
            return
        from app.domains.ops.models import NotificationEvent

        self.db.add(
            NotificationEvent(
                tenant_id=tenant_id,
                channel="email",
                recipient=user.email,
                title=title,
                body=body,
                status="pending",
                retry_count="0",
                metadata_json={
                    "user_notification_id": str(user_notification_id) if user_notification_id else None,
                    "category": category,
                    "priority": priority,
                    "action_url": action_url,
                },
            )
        )
        await self.db.flush()

    async def create_notification(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        title: str,
        body: str,
        category: str = "system",
        priority: str = "normal",
        actor_id: UUID | None = None,
        project_id: UUID | None = None,
        action_url: str | None = None,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        dedupe_key: str | None = None,
        metadata: dict | None = None,
        expires_at: datetime | None = None,
        ack_required: bool = False,
        ack_timeout_minutes: int | None = None,
    ) -> UserNotification | None:
        if priority not in VALID_PRIORITIES:
            raise ValueError(f"Unsupported notification priority '{priority}'")
        category = category.strip() or "system"
        preference = await self.get_preferences(tenant_id, user_id)
        if not self._allows_preference(preference, category, priority):
            return None
        if not preference.in_app_enabled and priority != "urgent":
            if preference.email_enabled:
                await self._queue_email_event(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    title=title.strip(),
                    body=body.strip(),
                    category=category,
                    priority=priority,
                    action_url=safe_action_url(action_url),
                )
            return None
        timeout_minutes = ack_timeout_minutes or preference.ack_timeout_minutes
        if dedupe_key:
            existing = await self.db.scalar(
                select(UserNotification).where(
                    UserNotification.tenant_id == tenant_id,
                    UserNotification.user_id == user_id,
                    UserNotification.dedupe_key == dedupe_key,
                )
            )
            if existing:
                return existing

        notification = UserNotification(
            tenant_id=tenant_id,
            user_id=user_id,
            actor_id=actor_id,
            project_id=project_id,
            category=category,
            priority=priority,
            title=title.strip(),
            body=body.strip(),
            action_url=safe_action_url(action_url),
            entity_type=entity_type,
            entity_id=entity_id,
            dedupe_key=dedupe_key,
            metadata_json=metadata or {},
            expires_at=expires_at,
            ack_required=ack_required,
            ack_deadline_at=(
                datetime.now(timezone.utc) + timedelta(minutes=timeout_minutes)
                if ack_required
                else None
            ),
        )
        if not dedupe_key:
            self.db.add(notification)
            await self.db.flush()
            if preference.email_enabled:
                await self._queue_email_event(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    title=notification.title,
                    body=notification.body,
                    category=notification.category,
                    priority=notification.priority,
                    action_url=notification.action_url,
                    user_notification_id=notification.id,
                )
            return notification

        try:
            async with self.db.begin_nested():
                self.db.add(notification)
                await self.db.flush()
        except IntegrityError:
            existing = await self.db.scalar(
                select(UserNotification).where(
                    UserNotification.tenant_id == tenant_id,
                    UserNotification.user_id == user_id,
                    UserNotification.dedupe_key == dedupe_key,
                )
            )
            if existing:
                return existing
            raise
        if preference.email_enabled:
            await self._queue_email_event(
                tenant_id=tenant_id,
                user_id=user_id,
                title=notification.title,
                body=notification.body,
                category=notification.category,
                priority=notification.priority,
                action_url=notification.action_url,
                user_notification_id=notification.id,
            )
        return notification

    async def broadcast_to_tenant(self, *, tenant_id: UUID, **data) -> list[UserNotification]:
        user_ids = list(
            (
                await self.db.scalars(
                    select(User.id).where(
                        User.tenant_id == tenant_id,
                        User.is_active.is_(True),
                        User.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        notifications = [
            await self.create_notification(tenant_id=tenant_id, user_id=user_id, **data)
            for user_id in user_ids
        ]
        return [notification for notification in notifications if notification is not None]

    async def notify_project_members(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_id: UUID | None,
        **data,
    ) -> list[UserNotification]:
        project = await self.db.scalar(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        if not project:
            return []
        members = list(
            (
                await self.db.scalars(
                    select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
                )
            ).all()
        )
        recipients = sorted(
            {recipient for recipient in [project.owner_id, *members] if recipient and recipient != actor_id},
            key=str,
        )
        notifications = [
            await self.create_notification(
                tenant_id=tenant_id,
                user_id=recipient,
                project_id=project_id,
                actor_id=actor_id,
                dedupe_key=f"{data.get('dedupe_key')}:{recipient}" if data.get("dedupe_key") else None,
                **{key: value for key, value in data.items() if key != "dedupe_key"},
            )
            for recipient in recipients
        ]
        return [notification for notification in notifications if notification is not None]

    async def notify_document_comment(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        comment_id: UUID,
        actor_id: UUID,
        parent_comment_id: UUID | None = None,
    ) -> list[UserNotification]:
        document = await self.db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        )
        if not document:
            return []
        recipients = {document.created_by}
        if parent_comment_id:
            parent_author = await self.db.scalar(
                select(DocumentComment.user_id).where(
                    DocumentComment.id == parent_comment_id,
                    DocumentComment.tenant_id == tenant_id,
                )
            )
            if parent_author:
                recipients.add(parent_author)
        recipients.discard(actor_id)
        notifications = [
            await self.create_notification(
                tenant_id=tenant_id,
                user_id=recipient,
                actor_id=actor_id,
                project_id=document.project_id,
                title="文档收到新的评审评论",
                body=f"《{document.title}》收到新的评论或回复，请及时处理。",
                category="comment",
                priority="high",
                action_url=f"/projects/{document.project_id}/documents/{document.id}",
                entity_type="document_comment",
                entity_id=comment_id,
                dedupe_key=f"comment:{comment_id}:{recipient}",
            )
            for recipient in sorted(recipients, key=str)
        ]
        return [notification for notification in notifications if notification is not None]

    async def notify_agent_run_terminal(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        user_id: UUID | None,
        status: str,
        project_id: UUID | None = None,
        run_name: str | None = None,
        error_message: str | None = None,
    ) -> UserNotification | None:
        if not user_id or status not in {"completed", "failed", "cancelled"}:
            return None
        failed = status != "completed"
        return await self.create_notification(
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id,
            title=f"{run_name or '智能编排运行'}{'失败' if failed else '已完成'}",
            body=error_message or ("运行需要人工处理，请查看执行记录。" if failed else "运行已完成，可查看输出和任务证据。"),
            category="agent_run",
            priority="urgent" if failed else "normal",
            action_url=f"/agent-ops?run_id={run_id}",
            entity_type="agent_run",
            entity_id=run_id,
            dedupe_key=f"agent-run:{run_id}:{status}",
        )

    def _inbox_filter(
        self,
        tenant_id: UUID,
        user_id: UUID,
        include_archived: bool = False,
        archived_only: bool = False,
    ):
        clauses = [
            UserNotification.tenant_id == tenant_id,
            UserNotification.user_id == user_id,
            or_(UserNotification.expires_at.is_(None), UserNotification.expires_at > datetime.now(timezone.utc)),
        ]
        if archived_only:
            clauses.append(UserNotification.archived_at.is_not(None))
        elif not include_archived:
            clauses.append(UserNotification.archived_at.is_(None))
        return and_(*clauses)

    async def list_notifications(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        page: int = 1,
        page_size: int = 25,
        unread_only: bool = False,
        include_archived: bool = False,
        archived_only: bool = False,
        category: str | None = None,
        priority: str | None = None,
        search: str | None = None,
        acknowledgement: str | None = None,
        escalated: bool | None = None,
    ) -> UserNotificationListResponse:
        filters = [self._inbox_filter(tenant_id, user_id, include_archived, archived_only)]
        if unread_only:
            filters.append(UserNotification.read_at.is_(None))
        if category:
            filters.append(UserNotification.category == category)
        if priority:
            filters.append(UserNotification.priority == priority)
        if search:
            pattern = f"%{search.strip()}%"
            filters.append(or_(UserNotification.title.ilike(pattern), UserNotification.body.ilike(pattern)))
        if acknowledgement == "required":
            filters.append(UserNotification.ack_required.is_(True))
            filters.append(UserNotification.acknowledged_at.is_(None))
        elif acknowledgement == "acknowledged":
            filters.append(UserNotification.acknowledged_at.is_not(None))
        if escalated is True:
            filters.append(UserNotification.escalation_level > 0)
        elif escalated is False:
            filters.append(UserNotification.escalation_level == 0)

        total = int(await self.db.scalar(select(func.count()).select_from(UserNotification).where(*filters)) or 0)
        rows = list(
            (
                await self.db.scalars(
                    select(UserNotification)
                    .where(*filters)
                    .order_by(UserNotification.created_at.desc(), UserNotification.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        unread_count = int(
            await self.db.scalar(
                select(func.count())
                .select_from(UserNotification)
                .where(self._inbox_filter(tenant_id, user_id), UserNotification.read_at.is_(None))
            )
            or 0
        )
        return UserNotificationListResponse(
            items=[UserNotificationResponse.model_validate(item) for item in rows],
            total=total,
            page=page,
            page_size=page_size,
            has_more=page * page_size < total,
            unread_count=unread_count,
        )

    async def get_summary(self, tenant_id: UUID, user_id: UUID, limit: int = 5) -> UserNotificationSummaryResponse:
        page = await self.list_notifications(tenant_id, user_id, page_size=limit)
        return UserNotificationSummaryResponse(unread_count=page.unread_count, recent=page.items)

    async def _get_owned(self, notification_id: UUID, tenant_id: UUID, user_id: UUID) -> UserNotification | None:
        return await self.db.scalar(
            select(UserNotification).where(
                UserNotification.id == notification_id,
                UserNotification.tenant_id == tenant_id,
                UserNotification.user_id == user_id,
            )
        )

    async def mark_read(self, notification_id: UUID, tenant_id: UUID, user_id: UUID) -> UserNotification | None:
        notification = await self._get_owned(notification_id, tenant_id, user_id)
        if not notification:
            return None
        if notification.read_at is None:
            notification.read_at = datetime.now(timezone.utc)
            await self.db.flush()
        return notification

    async def mark_all_read(self, tenant_id: UUID, user_id: UUID) -> int:
        rows = list(
            (
                await self.db.scalars(
                    select(UserNotification).where(
                        self._inbox_filter(tenant_id, user_id),
                        UserNotification.read_at.is_(None),
                    )
                )
            ).all()
        )
        now = datetime.now(timezone.utc)
        for item in rows:
            item.read_at = now
        await self.db.flush()
        return len(rows)

    async def archive(self, notification_id: UUID, tenant_id: UUID, user_id: UUID) -> UserNotification | None:
        notification = await self._get_owned(notification_id, tenant_id, user_id)
        if not notification:
            return None
        notification.archived_at = datetime.now(timezone.utc)
        if notification.read_at is None:
            notification.read_at = notification.archived_at
        await self.db.flush()
        return notification

    async def acknowledge(
        self,
        notification_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
    ) -> UserNotification | None:
        notification = await self._get_owned(notification_id, tenant_id, user_id)
        if not notification:
            return None
        if notification.ack_required and notification.acknowledged_at is None:
            notification.acknowledged_at = datetime.now(timezone.utc)
            if notification.read_at is None:
                notification.read_at = notification.acknowledged_at
            await self.db.flush()
        return notification

    async def escalate_overdue(
        self,
        *,
        now: datetime | None = None,
        tenant_id: UUID | None = None,
    ) -> list[UserNotification]:
        current_time = now or datetime.now(timezone.utc)
        filters = [
            UserNotification.ack_required.is_(True),
            UserNotification.acknowledged_at.is_(None),
            UserNotification.archived_at.is_(None),
            UserNotification.ack_deadline_at.is_not(None),
            UserNotification.ack_deadline_at <= current_time,
            UserNotification.escalation_level == 0,
        ]
        if tenant_id:
            filters.append(UserNotification.tenant_id == tenant_id)
        notifications = list((await self.db.scalars(select(UserNotification).where(*filters))).all())
        for notification in notifications:
            notification.priority = "urgent"
            notification.escalation_level = 1
            notification.escalated_at = current_time
            notification.metadata_json = {
                **(notification.metadata_json or {}),
                "escalation_reason": "acknowledgement_overdue",
            }
        if notifications:
            await self.db.flush()
        return notifications
