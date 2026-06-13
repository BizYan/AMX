"""Notification Service

Service for sending notifications via various channels:
- Email
- Webhook
- System notifications
- SMS (future)
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

import httpx

from app.core.settings import settings


logger = logging.getLogger(__name__)


class NotificationChannel(str, Enum):
    """Supported notification channels."""

    EMAIL = "email"
    WEBHOOK = "webhook"
    SYSTEM = "system"
    SMS = "sms"


class NotificationPriority(str, Enum):
    """Notification priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class NotificationMessage:
    """Notification message structure."""

    title: str
    body: str
    channel: NotificationChannel
    priority: NotificationPriority = NotificationPriority.NORMAL
    metadata: dict[str, Any] = field(default_factory=dict)
    recipient: str = ""  # email address or webhook URL
    sender: str = "Consultant AI Workbench"


@dataclass
class NotificationResult:
    """Result of sending a notification."""

    success: bool
    channel: NotificationChannel
    message: NotificationMessage
    error: str | None = None
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseNotificationHandler(ABC):
    """Abstract base class for notification handlers."""

    def __init__(self, channel: NotificationChannel):
        self.channel = channel

    @abstractmethod
    async def send(self, message: NotificationMessage) -> NotificationResult:
        """Send a notification.

        Args:
            message: Notification message to send

        Returns:
            NotificationResult with send status
        """
        pass


class EmailNotificationHandler(BaseNotificationHandler):
    """Handler for sending email notifications via SMTP."""

    def __init__(
        self,
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        smtp_from_email: str = "",
        smtp_from_name: str = "Consultant AI Workbench",
        use_tls: bool = True,
    ):
        super().__init__(NotificationChannel.EMAIL)
        self.smtp_host = smtp_host or settings.SMTP_HOST
        self.smtp_port = smtp_port or settings.SMTP_PORT
        self.smtp_user = smtp_user or settings.SMTP_USER
        self.smtp_password = smtp_password or settings.SMTP_PASSWORD
        self.smtp_from_email = smtp_from_email or settings.SMTP_FROM_EMAIL
        self.smtp_from_name = smtp_from_name or settings.SMTP_FROM_NAME
        self.use_tls = use_tls or settings.SMTP_USE_TLS

    async def send(self, message: NotificationMessage) -> NotificationResult:
        """Send email notification via SMTP.

        Args:
            message: Notification message

        Returns:
            NotificationResult
        """
        if not self.smtp_host or not self.smtp_from_email:
            logger.warning(
                f"SMTP not configured - email not sent to {message.recipient}"
            )
            return NotificationResult(
                success=False,
                channel=self.channel,
                message=message,
                error="SMTP not configured",
            )

        try:
            # Try to use aiosmtplib for async SMTP
            try:
                from aiosmtplib import SMTP
            except ImportError:
                logger.warning(
                    f"aiosmtplib not installed - email not sent to {message.recipient}"
                )
                return NotificationResult(
                    success=False,
                    channel=self.channel,
                    message=message,
                    error="aiosmtplib not installed",
                )

            # Build email message
            from email.message import EmailMessage

            email = EmailMessage()
            email["From"] = f"{self.smtp_from_name} <{self.smtp_from_email}>"
            email["To"] = message.recipient
            email["Subject"] = message.title
            email["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
            email.set_content(message.body)

            # Send via SMTP
            async with SMTP(
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user if self.smtp_user else None,
                password=self.smtp_password if self.smtp_password else None,
                start_tls=self.use_tls,
            ) as smtp:
                await smtp.send_message(email)

            logger.info(
                f"Email sent successfully: to={message.recipient}, "
                f"subject={message.title}"
            )

            return NotificationResult(
                success=True,
                channel=self.channel,
                message=message,
            )

        except Exception as e:
            logger.error(f"Failed to send email to {message.recipient}: {e}")
            return NotificationResult(
                success=False,
                channel=self.channel,
                message=message,
                error=str(e),
            )


class WebhookNotificationHandler(BaseNotificationHandler):
    """Handler for sending webhook notifications."""

    def __init__(self, timeout: int = 30):
        super().__init__(NotificationChannel.WEBHOOK)
        self.timeout = timeout

    async def send(self, message: NotificationMessage) -> NotificationResult:
        """Send webhook notification.

        Args:
            message: Notification message with webhook URL in recipient

        Returns:
            NotificationResult
        """
        try:
            payload = {
                "title": message.title,
                "body": message.body,
                "priority": message.priority.value,
                "metadata": message.metadata,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": message.sender,
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    message.recipient,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()

            return NotificationResult(
                success=True,
                channel=self.channel,
                message=message,
            )
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")
            return NotificationResult(
                success=False,
                channel=self.channel,
                message=message,
                error=str(e),
            )


class SystemNotificationHandler(BaseNotificationHandler):
    """Handler for system notifications (in-app)."""

    def __init__(self):
        super().__init__(NotificationChannel.SYSTEM)

    async def send(self, message: NotificationMessage) -> NotificationResult:
        """Send system notification.

        Args:
            message: Notification message

        Returns:
            NotificationResult
        """
        try:
            # In production, store in database for in-app notification retrieval
            logger.info(
                f"System notification: title={message.title}, "
                f"body={message.body[:100]}..., metadata={message.metadata}"
            )

            return NotificationResult(
                success=True,
                channel=self.channel,
                message=message,
            )
        except Exception as e:
            logger.error(f"Failed to send system notification: {e}")
            return NotificationResult(
                success=False,
                channel=self.channel,
                message=message,
                error=str(e),
            )


class NotificationService:
    """Service for managing and sending notifications.

    Supports multiple channels and provides a unified interface
    for sending notifications.
    """

    def __init__(self):
        """Initialize notification service."""
        self.handlers: dict[NotificationChannel, BaseNotificationHandler] = {
            NotificationChannel.EMAIL: EmailNotificationHandler(),
            NotificationChannel.WEBHOOK: WebhookNotificationHandler(),
            NotificationChannel.SYSTEM: SystemNotificationHandler(),
        }

    async def send(
        self,
        title: str,
        body: str,
        channel: NotificationChannel,
        recipient: str = "",
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
    ) -> NotificationResult:
        """Send a notification.

        Args:
            title: Notification title
            body: Notification body
            channel: Notification channel
            recipient: Recipient (email address or webhook URL)
            priority: Notification priority
            metadata: Additional metadata

        Returns:
            NotificationResult with send status
        """
        message = NotificationMessage(
            title=title,
            body=body,
            channel=channel,
            priority=priority,
            metadata=metadata or {},
            recipient=recipient,
        )

        handler = self.handlers.get(channel)
        if not handler:
            return NotificationResult(
                success=False,
                channel=channel,
                message=message,
                error=f"No handler for channel: {channel}",
            )

        return await handler.send(message)

    async def send_alert(
        self,
        alert_title: str,
        alert_body: str,
        recipient: str = "",
        priority: NotificationPriority = NotificationPriority.HIGH,
    ) -> NotificationResult:
        """Send an alert notification.

        Args:
            alert_title: Alert title
            alert_body: Alert body
            recipient: Recipient email or webhook URL
            priority: Alert priority

        Returns:
            NotificationResult
        """
        return await self.send(
            title=alert_title,
            body=alert_body,
            channel=NotificationChannel.SYSTEM,
            recipient=recipient,
            priority=priority,
            metadata={"type": "alert"},
        )

    async def send_workflow_notification(
        self,
        workflow_name: str,
        run_id: UUID,
        status: str,
        recipient: str = "",
    ) -> NotificationResult:
        """Send workflow status notification.

        Args:
            workflow_name: Name of the workflow
            run_id: Workflow run ID
            status: Status (completed, failed, etc.)
            recipient: Recipient email or webhook URL

        Returns:
            NotificationResult
        """
        status_emoji = {
            "completed": "✅",
            "failed": "❌",
            "running": "🔄",
            "cancelled": "⚠️",
        }.get(status, "📌")

        title = f"Workflow {status_emoji} {workflow_name}"
        body = f"Workflow '{workflow_name}' (run: {run_id}) is now {status}."

        return await self.send(
            title=title,
            body=body,
            channel=NotificationChannel.SYSTEM,
            recipient=recipient,
            metadata={"type": "workflow", "run_id": str(run_id), "status": status},
        )

    async def send_document_notification(
        self,
        document_title: str,
        document_id: UUID,
        action: str,
        recipient: str = "",
    ) -> NotificationResult:
        """Send document event notification.

        Args:
            document_title: Document title
            document_id: Document ID
            action: Action (created, updated, approved, etc.)
            recipient: Recipient email or webhook URL

        Returns:
            NotificationResult
        """
        title = f"Document 📄 {document_title}"
        body = f"Document '{document_title}' has been {action}."

        return await self.send(
            title=title,
            body=body,
            channel=NotificationChannel.SYSTEM,
            recipient=recipient,
            metadata={"type": "document", "document_id": str(document_id), "action": action},
        )

    def register_handler(
        self, channel: NotificationChannel, handler: BaseNotificationHandler
    ) -> None:
        """Register a custom notification handler.

        Args:
            channel: Notification channel
            handler: Handler to register
        """
        self.handlers[channel] = handler