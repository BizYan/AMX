"""Project Domain Models

Extends Project/ProjectMember with settings, invitations, and source files.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UuidMixin,
)
from app.models.projects import Project, ProjectMember  # noqa: F401


class SourceFileStatus(str, Enum):
    """Source file processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ProjectSettings(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Project settings model for storing arbitrary configuration.

    Stores JSON configuration per project without polluting the Project model.
    """

    __tablename__ = "project_settings"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    settings_json = Column(JSONB, nullable=False, default=dict)

    # Relations
    project = relationship("Project", back_populates="settings", lazy="selectin")


class ProjectLaunchPlan(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Persistent, retryable initialization plan for a project."""

    __tablename__ = "project_launch_plans"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    blueprint_key = Column(String(100), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    config_json = Column(JSONB, nullable=False, default=dict)
    checks_json = Column(JSONB, nullable=False, default=list)
    results_json = Column(JSONB, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="launch_plan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_launch_plans_project"),
        Index("ix_project_launch_plans_tenant_status", "tenant_id", "status"),
    )


class ProjectDeliveryPlan(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Persistent execution plan for project delivery."""

    __tablename__ = "project_delivery_plans"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    blueprint_key = Column(String(100), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="active", index=True)
    summary_json = Column(JSONB, nullable=False, default=dict)
    settings_json = Column(JSONB, nullable=False, default=dict)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="delivery_plan", lazy="selectin")
    milestones = relationship(
        "ProjectMilestone",
        back_populates="plan",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="ProjectMilestone.order_index",
    )

    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_delivery_plans_project"),
        Index("ix_project_delivery_plans_tenant_status", "tenant_id", "status"),
    )


class ProjectMilestone(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Ordered project delivery milestone with executable gates."""

    __tablename__ = "project_milestones"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_id = Column(
        UUID(as_uuid=True),
        ForeignKey("project_delivery_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    key = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String(20), nullable=False, default="planned", index=True)
    priority = Column(String(20), nullable=False, default="medium", index=True)
    order_index = Column(Integer, nullable=False, default=0)
    planned_start_at = Column(DateTime(timezone=True), nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=True, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    required_document_types_json = Column(JSONB, nullable=False, default=list)
    required_workflow_template_ids_json = Column(JSONB, nullable=False, default=list)
    gate_results_json = Column(JSONB, nullable=False, default=list)
    metadata_json = Column(JSONB, nullable=False, default=dict)

    plan = relationship("ProjectDeliveryPlan", back_populates="milestones", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("plan_id", "key", name="uq_project_milestones_plan_key"),
        Index("ix_project_milestones_plan_order", "plan_id", "order_index"),
        Index("ix_project_milestones_tenant_status", "tenant_id", "status"),
    )


class ProjectInvitation(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Project invitation model for pending memberships.

    Invitations are email-based and expire after a set time.
    """

    __tablename__ = "project_invitations"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email = Column(String(255), nullable=False, index=True)
    token = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # Relations
    project = relationship("Project", back_populates="invitations", lazy="selectin")

    __table_args__ = (
        Index("ix_project_invitations_project_email", "project_id", "email"),
    )


class SourceFile(Base, UuidMixin, TimestampMixin, SoftDeleteMixin, TenantMixin):
    """Source file model for uploaded documents.

    Stores metadata about uploaded files; actual content goes through StorageProvider.
    """

    __tablename__ = "source_files"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    size = Column(String(50), nullable=False)  # Stored as string but represents bytes
    hash = Column(String(64), nullable=False)  # SHA256 hex string
    storage_path = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default=SourceFileStatus.PENDING.value)
    metadata_json = Column(JSONB, nullable=True)

    # Relations
    project = relationship("Project", back_populates="source_files", lazy="selectin")

    __table_args__ = (
        Index("ix_source_files_project_id", "project_id"),
        Index("ix_source_files_tenant_id", "tenant_id"),
        Index("ix_source_files_status", "status"),
        Index("ix_source_files_hash", "hash"),
    )


# Add relationships to existing Project model
Project.settings = relationship(
    "ProjectSettings",
    back_populates="project",
    lazy="selectin",
    cascade="all, delete-orphan",
)
Project.launch_plan = relationship(
    "ProjectLaunchPlan",
    back_populates="project",
    lazy="selectin",
    cascade="all, delete-orphan",
    uselist=False,
)
Project.delivery_plan = relationship(
    "ProjectDeliveryPlan",
    back_populates="project",
    lazy="selectin",
    cascade="all, delete-orphan",
    uselist=False,
)
Project.invitations = relationship(
    "ProjectInvitation",
    back_populates="project",
    lazy="selectin",
    cascade="all, delete-orphan",
)
Project.source_files = relationship(
    "SourceFile",
    back_populates="project",
    lazy="selectin",
    cascade="all, delete-orphan",
)
