"""Authenticated API endpoints for the user notification center."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.domains.notifications.schemas import (
    NotificationMutationResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
    UserNotificationListResponse,
    UserNotificationResponse,
    UserNotificationSummaryResponse,
)
from app.domains.notifications.service import UserNotificationService
from app.models.identity import User
from app.services.audit_service import AuditService


router = APIRouter()


async def get_current_user(
    authorization: str = Header(..., description="Bearer token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    from app.domains.identity.service import AuthService

    user = await AuthService(db).get_current_user(authorization[7:])
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


@router.get("", response_model=UserNotificationListResponse)
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    unread_only: bool = False,
    include_archived: bool = False,
    archived_only: bool = False,
    category: str | None = None,
    priority: str | None = None,
    search: str | None = None,
    acknowledgement: str | None = None,
    escalated: bool | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await UserNotificationService(db).list_notifications(
        current_user.tenant_id,
        current_user.id,
        page=page,
        page_size=page_size,
        unread_only=unread_only,
        include_archived=include_archived,
        archived_only=archived_only,
        category=category,
        priority=priority,
        search=search,
        acknowledgement=acknowledgement,
        escalated=escalated,
    )


@router.get("/summary", response_model=UserNotificationSummaryResponse)
async def get_notification_summary(
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await UserNotificationService(db).get_summary(current_user.tenant_id, current_user.id, limit)


@router.get("/preferences", response_model=NotificationPreferenceResponse)
async def get_notification_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    preference = await UserNotificationService(db).get_preferences(current_user.tenant_id, current_user.id)
    return NotificationPreferenceResponse.model_validate(preference)


@router.patch("/preferences", response_model=NotificationPreferenceResponse)
async def update_notification_preferences(
    data: NotificationPreferenceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        preference = await UserNotificationService(db).update_preferences(
            current_user.tenant_id,
            current_user.id,
            data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="notification.preferences_update",
        resource_type="notification_preference",
        resource_id=preference.id,
        metadata=data.model_dump(exclude_unset=True),
    )
    return NotificationPreferenceResponse.model_validate(preference)


@router.post("/read-all", response_model=NotificationMutationResponse)
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    changed = await UserNotificationService(db).mark_all_read(current_user.tenant_id, current_user.id)
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="notification.read_all",
        resource_type="notification",
        metadata={"changed": changed},
    )
    return NotificationMutationResponse(changed=changed)


@router.post("/{notification_id}/read", response_model=UserNotificationResponse)
async def mark_notification_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = await UserNotificationService(db).mark_read(
        notification_id, current_user.tenant_id, current_user.id
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="notification.read",
        resource_type="notification",
        resource_id=notification.id,
    )
    return UserNotificationResponse.model_validate(notification)


@router.post("/{notification_id}/archive", response_model=UserNotificationResponse)
async def archive_notification(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = await UserNotificationService(db).archive(
        notification_id, current_user.tenant_id, current_user.id
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="notification.archive",
        resource_type="notification",
        resource_id=notification.id,
    )
    return UserNotificationResponse.model_validate(notification)


@router.post("/{notification_id}/acknowledge", response_model=UserNotificationResponse)
async def acknowledge_notification(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = await UserNotificationService(db).acknowledge(
        notification_id,
        current_user.tenant_id,
        current_user.id,
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="notification.acknowledge",
        resource_type="notification",
        resource_id=notification.id,
    )
    return UserNotificationResponse.model_validate(notification)
