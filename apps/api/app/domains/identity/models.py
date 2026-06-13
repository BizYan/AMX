"""Identity Domain Models

Extends base models with Policy, FieldPermission, and AuditLog for RBAC/ABAC.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UuidMixin,
)
from app.models.identity import Role, Tenant, User, UserRole

if TYPE_CHECKING:
    pass


class Policy(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Policy model for ABAC (Attribute-Based Access Control).

    Policies define allow/deny rules based on actions, resources, and conditions.
    """

    __tablename__ = "policies"

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    effect = Column(String(20), nullable=False)  # "allow" or "deny"
    actions = Column(JSONB, nullable=False, default=list)  # ["read", "write", "delete"]
    resources = Column(JSONB, nullable=False, default=list)  # ["projects:*", "documents:read"]
    conditions = Column(JSONB, nullable=True, default=dict)  # {"tenant_id": "{{tenant_id}}"}

    # Relations
    tenant = relationship("Tenant", lazy="selectin")


class FieldPermission(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Field-level permission model for granular access control.

    Controls which fields a role can read/write on specific resource types.
    """

    __tablename__ = "field_permissions"

    role_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    resource_type = Column(String(100), nullable=False)  # "project", "document", etc.
    field_name = Column(String(100), nullable=False)  # "name", "description", etc.
    permission = Column(String(20), nullable=False)  # "read", "write", "none"

    # Indexes for efficient lookup
    __table_args__ = (
        Index("ix_field_permissions_role_resource", "role_id", "resource_type"),
    )


class AuditLog(Base, UuidMixin):
    """Audit log model for tracking all security-relevant actions.

    Designed for monthly partitioning in production.
    """

    __tablename__ = "audit_logs"

    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(100), nullable=True)
    resource_id = Column(UUID(as_uuid=True), nullable=True)
    extra_data = Column("metadata", JSONB, nullable=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("ix_audit_logs_tenant_id_created", "tenant_id", "created_at"),
    )


class TenantApiKey(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Tenant-scoped API key metadata.

    The plaintext key is returned only once during creation. Persistent storage
    keeps a hash and prefix so operators can identify keys without exposing
    secrets in list responses, exports, or audit logs.
    """

    __tablename__ = "tenant_api_keys"

    name = Column(String(255), nullable=False)
    key_prefix = Column(String(32), nullable=False, index=True)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    permissions = Column(JSONB, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="active")
    created_by_id = Column(UUID(as_uuid=True), nullable=True)
    revoked_by_id = Column(UUID(as_uuid=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_tenant_api_keys_tenant_status", "tenant_id", "status"),
        Index("ix_tenant_api_keys_created_by", "created_by_id"),
    )
