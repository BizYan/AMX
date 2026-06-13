"""Operational evidence and manual retry for notification channel deliveries."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.ops.models import NotificationEvent
from app.domains.ops.schemas import NotificationDeliveryListResponse, NotificationDeliveryResponse
from app.services.notification_service import NotificationChannel, NotificationPriority, NotificationService


class NotificationDeliveryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_deliveries(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        channel: str | None = None,
        limit: int = 50,
    ) -> NotificationDeliveryListResponse:
        filters = [NotificationEvent.tenant_id == tenant_id]
        if status:
            filters.append(NotificationEvent.status == status)
        if channel:
            filters.append(NotificationEvent.channel == channel)
        items = list(
            (
                await self.db.scalars(
                    select(NotificationEvent)
                    .where(*filters)
                    .order_by(NotificationEvent.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )

        async def count_for(delivery_status: str | None = None) -> int:
            count_filters = [NotificationEvent.tenant_id == tenant_id]
            if delivery_status:
                count_filters.append(NotificationEvent.status == delivery_status)
            return int(
                await self.db.scalar(
                    select(func.count()).select_from(NotificationEvent).where(*count_filters)
                )
                or 0
            )

        return NotificationDeliveryListResponse(
            items=[NotificationDeliveryResponse.model_validate(item) for item in items],
            total=await count_for(),
            sent_count=await count_for("sent"),
            failed_count=await count_for("failed"),
            pending_count=(await count_for("pending")) + (await count_for("retrying")),
        )

    async def retry_delivery(self, event_id: UUID, tenant_id: UUID) -> NotificationEvent | None:
        event = await self.db.scalar(
            select(NotificationEvent).where(
                NotificationEvent.id == event_id,
                NotificationEvent.tenant_id == tenant_id,
            )
        )
        if not event:
            return None
        try:
            channel = NotificationChannel(event.channel)
        except ValueError:
            event.error_message = f"Unsupported notification channel: {event.channel}"
            event.status = "failed"
            await self.db.flush()
            return event

        event.status = "retrying"
        event.retry_count = str(int(event.retry_count or "0") + 1)
        result = await NotificationService().send(
            title=event.title,
            body=event.body,
            channel=channel,
            recipient=event.recipient or "",
            priority=NotificationPriority.HIGH,
            metadata=event.metadata_json or {},
        )
        if result.success:
            event.status = "sent"
            event.error_message = None
            event.sent_at = result.sent_at or datetime.now(timezone.utc)
            event.next_retry_at = None
        else:
            event.status = "failed"
            event.error_message = (result.error or "Notification retry failed")[:1000]
        await self.db.flush()
        return event
