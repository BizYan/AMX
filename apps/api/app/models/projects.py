"""Project Domain Models

Project and ProjectMember models.
"""

from sqlalchemy import (
    Column,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UuidMixin,
)


class Project(Base, UuidMixin, TimestampMixin, SoftDeleteMixin, TenantMixin):
    """Project model."""

    __tablename__ = "projects"

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    slug = Column(String(100), nullable=False, index=True)
    owner_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(String(20), nullable=False, default="active", server_default="active")

    # Relations - use string reference to avoid circular imports
    owner = relationship("User", back_populates="owned_projects", lazy="selectin")
    members = relationship("ProjectMember", back_populates="project", lazy="selectin")


class ProjectMember(Base, UuidMixin):
    """Project member association table."""

    __tablename__ = "project_members"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relations - use string reference to avoid circular imports
    project = relationship("Project", back_populates="members", lazy="selectin")
