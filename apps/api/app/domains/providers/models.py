"""Provider Domain Models

Extends Provider, ProviderVersion, ProviderCapability, ProviderRun, and ProviderHealth.
"""

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, Boolean, Integer, Numeric
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UuidMixin,
)


class ProviderType(str, Enum):
    """Provider type enum."""
    LLM = "llm"
    GRAPHIFY = "graphify"
    GITNEXUS = "gitnexus"
    NATIVE_GRAPH = "native_graph"
    CUSTOM = "custom"


class ProviderStatus(str, Enum):
    """Provider status enum."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    GRAY = "gray"
    ROLLBACK = "rollback"


class RunStatus(str, Enum):
    """Provider run status enum."""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"


class HealthStatus(str, Enum):
    """Provider health status enum."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


class CapabilityType(str, Enum):
    """Provider capability type enum."""
    TEXT_GENERATION = "text_generation"
    EMBEDDING = "embedding"
    GRAPH_QUERY = "graph_query"
    CODE_GENERATION = "code_generation"
    IMAGE_GENERATION = "image_generation"


class Provider(Base, UuidMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """Provider model for LLM and external service providers.

    Supports multiple provider types (llm, graphify, gitnexus, native_graph, custom)
    with versioned configurations.
    """

    __tablename__ = "providers"

    name = Column(String(255), nullable=False, index=True)
    provider_type = Column(String(50), nullable=False, index=True)
    config_json = Column(JSONB, nullable=False, default=dict)
    capabilities_json = Column(JSONB, nullable=True)
    status = Column(String(20), nullable=False, default=ProviderStatus.ACTIVE.value, index=True)
    current_version_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    # Relations
    versions = relationship("ProviderVersion", back_populates="provider", lazy="selectin", cascade="all, delete-orphan")
    capabilities = relationship("ProviderCapability", back_populates="provider", lazy="selectin", cascade="all, delete-orphan")
    runs = relationship("ProviderRun", back_populates="provider", lazy="noload", cascade="all, delete-orphan")
    health_records = relationship("ProviderHealth", back_populates="provider", lazy="selectin", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_providers_tenant_type", "tenant_id", "provider_type"),
    )


class ProviderVersion(Base, UuidMixin, TimestampMixin):
    """Provider version model for versioned provider configurations.

    Each provider can have multiple versions; only one can be active at a time.
    """

    __tablename__ = "provider_versions"

    provider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(String(50), nullable=False)
    config_json = Column(JSONB, nullable=False, default=dict)
    capabilities_json = Column(JSONB, nullable=True)
    is_active = Column(Boolean, nullable=False, default=False, index=True)

    # Relations
    provider = relationship("Provider", back_populates="versions")

    __table_args__ = (
        Index("ix_provider_versions_provider_version", "provider_id", "version", unique=True),
    )


class ProviderCapability(Base, UuidMixin, TimestampMixin):
    """Provider capability model for tracking provider capabilities.

    Stores endpoint, rate limits, and timeouts for each capability.
    """

    __tablename__ = "provider_capabilities"

    provider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    capability_type = Column(String(50), nullable=False, index=True)
    endpoint = Column(Text, nullable=True)
    rate_limit = Column(Integer, nullable=True)  # requests per minute
    timeout = Column(Integer, nullable=True)  # seconds

    # Relations
    provider = relationship("Provider", back_populates="capabilities")

    __table_args__ = (
        Index("ix_provider_capabilities_provider_type", "provider_id", "capability_type", unique=True),
    )


class ProviderRun(Base, UuidMixin, TimestampMixin, TenantMixin):
    """Provider run model for tracking provider invocations.

    Records input/output tokens, latency, and status for each run.
    """

    __tablename__ = "provider_runs"

    provider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    capability_type = Column(String(50), nullable=False, index=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, index=True)
    error_message = Column(Text, nullable=True)

    # Relations
    provider = relationship("Provider", back_populates="runs")

    __table_args__ = (
        Index("ix_provider_runs_tenant_created", "tenant_id", "created_at"),
        Index("ix_provider_runs_provider_status", "provider_id", "status"),
    )


class ProviderHealth(Base, UuidMixin, TimestampMixin):
    """Provider health model for health monitoring.

    Tracks response time, success rate, and last check time.
    """

    __tablename__ = "provider_health"

    provider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(20), nullable=False, index=True)
    response_time_ms = Column(Integer, nullable=True)
    success_rate = Column(Numeric(5, 2), nullable=True)  # 0.00 to 100.00
    last_check_at = Column(DateTime(timezone=True), nullable=False)

    # Relations
    provider = relationship("Provider", back_populates="health_records")

    __table_args__ = (
        Index("ix_provider_health_provider_last_check", "provider_id", "last_check_at"),
    )
