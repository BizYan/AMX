"""Template Domain Models

Database models for document templates with versioning support.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UuidMixin,
)

if TYPE_CHECKING:
    pass


class DocType(str, Enum):
    """Document type enumeration for templates."""

    URS = "urs"
    BRD = "brd"
    PRD = "prd"
    USER_STORY = "user_story"
    DETAILED_DESIGN = "detailed_design"
    INTERFACE = "interface"
    DATA_DICTIONARY = "data_dictionary"
    TEST_CASE = "test_case"


class Template(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Template model for storing document templates.

    Templates are used to generate documents with consistent structure
    and can be versioned for tracking changes.
    """

    __tablename__ = "templates"

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    doc_type = Column(String(50), nullable=False, default=DocType.URS.value)
    version_count = Column(Integer, nullable=False, default=0)
    is_active = Column(String(10), nullable=False, default="true")
    created_by = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # Relations
    versions = relationship(
        "TemplateVersion",
        back_populates="template",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="TemplateVersion.version.desc()",
    )

    __table_args__ = (
        Index("ix_templates_tenant_id", "tenant_id"),
        Index("ix_templates_doc_type", "doc_type"),
        Index("ix_templates_created_by", "created_by"),
    )


class TemplateVersion(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Template version model for version history tracking.

    Stores template content snapshots with placeholder schemas for
    variable substitution during document generation.
    """

    __tablename__ = "template_versions"

    template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False)
    content = Column(LargeBinary, nullable=True)
    file_hash = Column(String(64), nullable=True)
    placeholder_schema = Column(JSONB, nullable=True)
    page_types = Column(JSONB, nullable=True)
    is_active = Column(String(10), nullable=False, default="true")
    created_by = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # Relations
    template = relationship("Template", back_populates="versions")
    sections = relationship(
        "TemplateSection",
        back_populates="template_version",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="TemplateSection.position",
    )

    __table_args__ = (
        Index("ix_template_versions_template_id", "template_id"),
        Index("ix_template_versions_version", "template_id", "version"),
    )


class TemplateSection(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Structured section definition for a template version.

    Sections turn a binary template version into an editable consulting
    deliverable structure with prompts, required inputs, and quality rules.
    """

    __tablename__ = "template_sections"

    template_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("template_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_section_id = Column(
        UUID(as_uuid=True),
        ForeignKey("template_sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    section_key = Column(String(120), nullable=False)
    title = Column(String(255), nullable=False)
    level = Column(Integer, nullable=False, default=1)
    position = Column(Integer, nullable=False, default=0)
    content_requirement = Column(Text, nullable=False, default="")
    prompt = Column(Text, nullable=False, default="")
    required_inputs = Column(JSONB, nullable=False, default=list)
    quality_rules = Column(JSONB, nullable=False, default=list)
    created_by = Column(UUID(as_uuid=True), nullable=False, index=True)

    template_version = relationship("TemplateVersion", back_populates="sections")
    parent = relationship("TemplateSection", remote_side="TemplateSection.id", lazy="selectin")
    skill_bindings = relationship(
        "TemplateSectionSkillBinding",
        back_populates="section",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="TemplateSectionSkillBinding.order_index",
    )

    __table_args__ = (
        Index("ix_template_sections_tenant_id", "tenant_id"),
        Index("ix_template_sections_version_id", "template_version_id"),
        Index("ix_template_sections_parent_id", "parent_section_id"),
        Index("ix_template_sections_section_key", "template_version_id", "section_key"),
        Index("ix_template_sections_order", "template_version_id", "position"),
    )


class TemplateSectionSkillBinding(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Ordered skill binding for a template section."""

    __tablename__ = "template_section_skill_bindings"

    section_id = Column(
        UUID(as_uuid=True),
        ForeignKey("template_sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_index = Column(Integer, nullable=False, default=0)
    is_required = Column(Integer, nullable=False, default=1)
    prompt_override = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=False, index=True)

    section = relationship("TemplateSection", back_populates="skill_bindings")
    skill = relationship("AgentSkill", lazy="selectin")

    __table_args__ = (
        Index("ix_template_section_skill_bindings_tenant_id", "tenant_id"),
        Index("ix_template_section_skill_bindings_section_id", "section_id"),
        Index("ix_template_section_skill_bindings_skill_id", "skill_id"),
        Index("ix_template_section_skill_bindings_order", "section_id", "order_index"),
    )
