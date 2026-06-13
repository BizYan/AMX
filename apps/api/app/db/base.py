"""Database Base Module

Declarative base class and mixins for all domain models.
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase

if TYPE_CHECKING:
    pass


class Base(DeclarativeBase):
    """Base class for all domain models."""
    pass


class UuidMixin:
    """Mixin that adds a UUID primary key as 'id'."""

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )


class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamps."""

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class SoftDeleteMixin:
    """Mixin that adds soft delete capability via deleted_at."""

    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )


class TenantMixin:
    """Mixin that adds tenant_id column for multi-tenancy."""

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
