"""Providers Domain Schemas

Pydantic v2 schemas for provider request/response validation.
"""

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.providers.models import ProviderType, ProviderStatus, RunStatus, HealthStatus
from app.domains.providers.credential_boundary import (
    redact_secrets,
    sanitize_error_message,
    validate_provider_config_boundary,
)


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response schema."""
    items: list[T]
    total: int
    page: int
    page_size: int
    has_more: bool


class ProviderBase(BaseModel):
    """Base provider schema."""
    name: str = Field(..., min_length=1, max_length=255)
    provider_type: ProviderType
    config: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] | None = None

    @field_validator("config")
    @classmethod
    def validate_credential_boundary(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_provider_config_boundary(value)


class ProviderCreate(ProviderBase):
    """Schema for creating a provider."""
    pass


class ProviderUpdate(BaseModel):
    """Schema for updating a provider."""
    name: str | None = Field(None, min_length=1, max_length=255)
    config: dict[str, Any] | None = None
    status: ProviderStatus | None = None

    @field_validator("config")
    @classmethod
    def validate_credential_boundary(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return value
        return validate_provider_config_boundary(value)


class ProviderResponse(BaseModel):
    """Schema for provider response."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    name: str
    provider_type: str
    config_json: dict[str, Any]
    capabilities_json: dict[str, Any] | None
    status: str
    current_version_id: UUID | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def redact_config(self) -> "ProviderResponse":
        self.config_json = redact_secrets(self.config_json)
        return self


class ProviderVersionBase(BaseModel):
    """Base provider version schema."""
    version: str
    config: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] | None = None

    @field_validator("config")
    @classmethod
    def validate_credential_boundary(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_provider_config_boundary(value)


class ProviderVersionCreate(ProviderVersionBase):
    """Schema for creating a provider version."""
    set_active: bool = True


class ProviderVersionResponse(BaseModel):
    """Schema for provider version response."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: UUID
    version: str
    config_json: dict[str, Any]
    capabilities_json: dict[str, Any] | None
    is_active: bool
    created_at: datetime

    @model_validator(mode="after")
    def redact_config(self) -> "ProviderVersionResponse":
        self.config_json = redact_secrets(self.config_json)
        return self


class ProviderCapabilityResponse(BaseModel):
    """Schema for provider capability response."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: UUID
    capability_type: str
    endpoint: str | None
    rate_limit: int | None
    timeout: int | None
    created_at: datetime


class ProviderRunResponse(BaseModel):
    """Schema for provider run response."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    provider_id: UUID
    version_id: UUID | None
    capability_type: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    status: str
    error_message: str | None
    created_at: datetime

    @model_validator(mode="after")
    def redact_error(self) -> "ProviderRunResponse":
        self.error_message = sanitize_error_message(self.error_message)
        return self


class ProviderHealthResponse(BaseModel):
    """Schema for provider health response."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: UUID
    status: str
    response_time_ms: int | None
    success_rate: float | None
    last_check_at: datetime
    created_at: datetime


class ProviderRollbackRequest(BaseModel):
    """Schema for rollback request."""
    version_id: UUID = Field(..., description="Version ID to rollback to")


class ProviderTestRequest(BaseModel):
    """Schema for provider test request."""
    capability_type: str = Field(..., description="Capability to test")
    params: dict[str, Any] = Field(default_factory=dict, description="Test parameters")
    allow_sandbox: bool = Field(
        default=False,
        description="Run an explicit sandbox probe instead of requiring live credentials",
    )


class ProviderTestResponse(BaseModel):
    """Schema for provider test response."""
    success: bool
    message: str
    latency_ms: int | None = None
    output: dict[str, Any] | None = None
    status: str = "unknown"
    mode: str = "unknown"
    capability_type: str | None = None
    configured: bool = False
    production_ready: bool = False
    sandbox_fallback: bool = False

    @model_validator(mode="after")
    def redact_provider_output(self) -> "ProviderTestResponse":
        self.message = sanitize_error_message(self.message) or ""
        self.output = redact_secrets(self.output)
        return self


class ProviderReadinessItem(BaseModel):
    """Production readiness state for a single provider."""

    provider_id: UUID
    name: str
    provider_type: str
    status: str
    readiness: str
    reason: str
    recommended_action: str


class ProviderRequiredTypeReadiness(BaseModel):
    """Readiness state for a required provider capability type."""

    provider_type: str
    label: str
    live_count: int
    sandbox_count: int
    unconfigured_count: int
    status: str


class ProviderReadinessSummary(BaseModel):
    """Tenant-level provider production readiness summary."""

    tenant_id: UUID
    total_providers: int
    live_providers: int
    sandbox_providers: int
    mock_providers: int = 0
    unconfigured_providers: int
    inactive_providers: int
    degraded_providers: int = 0
    failed_providers: int = 0
    readiness_score: int
    production_ready: bool
    missing_required_types: list[str] = Field(default_factory=list)
    required_types: list[ProviderRequiredTypeReadiness] = Field(default_factory=list)
    items: list[ProviderReadinessItem] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
