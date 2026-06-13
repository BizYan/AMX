"""Config Domain Schemas

Pydantic v2 schemas for ConfigUnit CRUD operations.
"""

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# Generic type for paginated responses
T = TypeVar("T")


class PaginationParams(BaseModel):
    """Pagination parameters for list endpoints."""

    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response schema."""

    items: list[T]
    total: int
    page: int
    page_size: int
    has_more: bool


# Document Type Enum
class DocType(str):
    URS = "urs"
    BRD = "brd"
    PRD = "prd"
    USER_STORY = "story"
    DETAILED_DESIGN = "design"
    INTERFACE = "interface"
    DATA_DICTIONARY = "data_dict"
    TEST_CASE = "test_case"


# ConfigUnit Schemas
class ConfigUnitBase(BaseModel):
    """Base ConfigUnit schema."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    doc_type: str = Field(..., pattern="^(urs|brd|prd|story|design|interface|data_dict|test_case)$")
    entity_schema: dict[str, Any] = Field(default_factory=dict)
    document_structure: dict[str, Any] = Field(default_factory=dict)
    generation_prompt: dict[str, Any] = Field(default_factory=dict)
    quality_rules: dict[str, Any] = Field(default_factory=dict)
    bound_skills: list[str] = Field(default_factory=list)
    node_flow: dict[str, Any] = Field(default_factory=dict)


class ConfigUnitCreate(ConfigUnitBase):
    """Schema for creating a ConfigUnit."""

    pass


class ConfigUnitUpdate(BaseModel):
    """Schema for updating a ConfigUnit."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    entity_schema: dict[str, Any] | None = None
    document_structure: dict[str, Any] | None = None
    generation_prompt: dict[str, Any] | None = None
    quality_rules: dict[str, Any] | None = None
    bound_skills: list[str] | None = None
    node_flow: dict[str, Any] | None = None
    is_active: bool | None = None


class ConfigUnitResponse(ConfigUnitBase):
    """Schema for ConfigUnit response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    is_active: bool
    version: int
    released_at: datetime | None
    released_by: UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ConfigUnitListResponse(PaginatedResponse[ConfigUnitResponse]):
    """Schema for paginated ConfigUnit list response."""

    pass


class ConfigUnitPublishResponse(BaseModel):
    """Schema for publish response."""

    id: UUID
    version: int
    is_active: bool
    released_at: datetime
    released_by: UUID | None


class ConfigUnitTestRequest(BaseModel):
    """Schema for test request."""

    test_data: dict[str, Any] = Field(..., description="Test input data")
    mode: str = Field(default="validate", pattern="^(validate|generate)$")


class ConfigUnitTestResponse(BaseModel):
    """Schema for test response."""

    success: bool
    output: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    quality_score: float | None = None