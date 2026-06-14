"""Identity Domain Models

User, Role, Tenant and related models for authentication and authorization.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UuidMixin,
)


class Tenant(Base, UuidMixin, TimestampMixin, SoftDeleteMixin):
    """Tenant model for multi-tenancy.

    All domain resources belong to a tenant.
    """

    __tablename__ = "tenants"

    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)

    # Relations - use string reference to avoid circular imports
    users = relationship("User", back_populates="tenant", lazy="selectin")
    roles = relationship("Role", back_populates="tenant", lazy="selectin")


class User(Base, UuidMixin, TimestampMixin, SoftDeleteMixin, TenantMixin):
    """User model for authentication."""

    __tablename__ = "users"

    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    security_version = Column(Integer, default=1, nullable=False)
    password_changed_at = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # Override TenantMixin.tenant_id to add ForeignKey for proper relationship
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Relations - use string reference to avoid circular imports
    tenant = relationship("Tenant", back_populates="users", lazy="selectin")
    roles = relationship("UserRole", back_populates="user", lazy="selectin")
    owned_projects = relationship("Project", back_populates="owner", lazy="selectin")


class Role(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Role model for RBAC."""

    __tablename__ = "roles"

    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    permissions = Column(JSONB, nullable=True, default=dict)

    # Override TenantMixin.tenant_id to add ForeignKey for proper relationship
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Relations - use string reference to avoid circular imports
    tenant = relationship("Tenant", back_populates="roles", lazy="selectin")
    users = relationship("UserRole", back_populates="role", lazy="selectin")


class UserRole(Base):
    """User-Role association table."""

    __tablename__ = "user_roles"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Relations - use string reference to avoid circular imports
    user = relationship("User", back_populates="roles", lazy="selectin")
    role = relationship("Role", back_populates="users", lazy="selectin")
