"""Background jobs for acknowledgement escalation."""

from app.db.session import AsyncSessionLocal
from app.domains.notifications.service import UserNotificationService
from app.domains.ops.models import NotificationEvent
from app.domains.ops.notification_delivery_service import NotificationDeliveryService
from sqlalchemy import select


async def escalate_overdue_notifications(ctx: dict) -> dict:
    """Escalate overdue acknowledgement-required notifications once."""
    async with AsyncSessionLocal() as db:
        escalated = await UserNotificationService(db).escalate_overdue()
        if escalated:
            await db.commit()
        return {
            "success": True,
            "escalated_count": len(escalated),
            "notification_ids": [str(item.id) for item in escalated],
        }


async def process_pending_notification_deliveries(ctx: dict) -> dict:
    """Deliver queued preference-driven channel notifications."""
    async with AsyncSessionLocal() as db:
        events = list(
            (
                await db.scalars(
                    select(NotificationEvent)
                    .where(NotificationEvent.status == "pending")
                    .order_by(NotificationEvent.created_at.asc())
                    .limit(100)
                )
            ).all()
        )
        service = NotificationDeliveryService(db)
        for event in events:
            if event.tenant_id:
                await service.retry_delivery(event.id, event.tenant_id)
        if events:
            await db.commit()
        return {"success": True, "processed_count": len(events)}
