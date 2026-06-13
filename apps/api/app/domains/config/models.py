"""Config Domain Models

Database models for configuration units that define document generation rules.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
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


class ConfigUnit(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Configuration unit for document types.

    Defines the schema, structure, prompts, and quality rules for generating
    documents of specific types (URS, BRD, PRD, user stories, etc.).
    """

    __tablename__ = "config_units"

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    doc_type = Column(String(50), nullable=False, index=True)  # urs/brd/prd/story/etc

    # JSON Schema for entity validation
    entity_schema = Column(JSONB, nullable=False, default=dict)

    # Chapter structure definition
    document_structure = Column(JSONB, nullable=False, default=dict)

    # Prompt rules for generation
    generation_prompt = Column(JSONB, nullable=False, default=dict)

    # Quality check rules (MECE, completeness, consistency)
    quality_rules = Column(JSONB, nullable=False, default=dict)

    # Skill IDs bound to this config
    bound_skills = Column(JSONB, nullable=False, default=list)

    # Node flow: generate -> review -> confirm -> export
    node_flow = Column(JSONB, nullable=False, default=dict)

    is_active = Column(Boolean, nullable=False, default=False)
    version = Column(Integer, nullable=False, default=1)

    released_at = Column(DateTime(timezone=True), nullable=True)
    released_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Relations
    tenant = relationship("Tenant", lazy="selectin")
    releaser = relationship("User", foreign_keys=[released_by], lazy="selectin")

    __table_args__ = (
        Index("ix_config_units_tenant_id", "tenant_id"),
        Index("ix_config_units_doc_type", "doc_type"),
        Index("ix_config_units_is_active", "is_active"),
    )


# Add relationship to Tenant model
from app.models.identity import Tenant  # noqa: PLC0415

Tenant.config_units = relationship(
    "ConfigUnit",
    back_populates="tenant",
    lazy="selectin",
    cascade="all, delete-orphan",
)