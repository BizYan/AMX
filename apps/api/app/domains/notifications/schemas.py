"""Pydantic contracts for the in-app notification center."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserNotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: UUID
    actor_id: UUID | None = None
    project_id: UUID | None = None
    category: str
    priority: str
    title: str
    body: str
    action_url: str | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None
    metadata_json: dict = Field(default_factory=dict)
    read_at: datetime | None = None
    archived_at: datetime | None = None
    expires_at: datetime | None = None
    ack_required: bool = False
    acknowledged_at: datetime | None = None
    ack_deadline_at: datetime | None = None
    escalation_level: int = 0
    escalated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UserNotificationListResponse(BaseModel):
    items: list[UserNotificationResponse]
    total: int
    page: int
    page_size: int
    has_more: bool
    unread_count: int


class UserNotificationSummaryResponse(BaseModel):
    unread_count: int
    recent: list[UserNotificationResponse]


class NotificationMutationResponse(BaseModel):
    changed: int


class NotificationPreferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: UUID
    in_app_enabled: bool
    email_enabled: bool
    enabled_categories: list[str] = Field(default_factory=list)
    min_priority: str
    daily_digest: bool
    ack_timeout_minutes: int
    created_at: datetime
    updated_at: datetime


class NotificationPreferenceUpdate(BaseModel):
    in_app_enabled: bool | None = None
    email_enabled: bool | None = None
    enabled_categories: list[str] | None = None
    min_priority: str | None = None
    daily_digest: bool | None = None
    ack_timeout_minutes: int | None = Field(default=None, ge=5, le=10080)
