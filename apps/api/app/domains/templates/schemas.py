"""Template Domain Schemas

Pydantic v2 schemas for template request/response validation.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.agent.schemas import SkillCatalogResponse


class PlaceholderSchema(BaseModel):
    """Schema for template placeholder definition."""

    name: str = Field(..., description="Placeholder variable name")
    description: str | None = Field(None, description="Description of the placeholder")
    default_value: str | None = Field(None, description="Default value if not provided")
    field_type: str = Field(default="text", description="Type of field (text, number, date, etc.)")
    required: bool = Field(default=True, description="Whether placeholder is required")
    occurrence_count: int = Field(default=1, ge=1, description="How many times the placeholder appears")


class PageTypeSchema(BaseModel):
    """Schema for template page type definition."""

    page_number: int = Field(..., description="Page number (1-indexed)")
    page_type: str = Field(..., description="Page type (title, content, chart, table)")
    title_placeholder: str | None = Field(None, description="Placeholder for slide/title text")
    content_placeholders: list[str] = Field(default_factory=list, description="Placeholders in content area")


# Template Schemas
class TemplateBase(BaseModel):
    """Base template schema."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, description="Template description")
    doc_type: str = Field(..., description="Document type (urs, brd, prd, etc.)")


class TemplateCreate(TemplateBase):
    """Schema for creating a template."""

    created_by: UUID | None = Field(None, description="User ID of creator")


class TemplateUpdate(BaseModel):
    """Schema for updating a template."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    is_active: str | None = Field(None, description="Active status (true/false)")


class TemplateResponse(TemplateBase):
    """Schema for template response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    version_count: int
    is_active: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class TemplateDetailResponse(TemplateResponse):
    """Schema for template response with versions."""

    versions: list["TemplateVersionResponse"] = Field(default_factory=list)


# Template Version Schemas
class TemplateVersionBase(BaseModel):
    """Base template version schema."""

    version: int = Field(..., description="Version number")
    content: bytes | None = Field(None, description="Template file content")
    file_hash: str | None = Field(None, description="SHA256 hash of content")
    placeholder_schema: list[PlaceholderSchema] | None = Field(None, description="List of placeholders")
    page_types: list[PageTypeSchema] | None = Field(None, description="Page type definitions")
    is_active: str = Field(default="true", description="Whether this version is active")


class TemplateVersionCreate(TemplateVersionBase):
    """Schema for creating a template version."""

    created_by: UUID | None = Field(None, description="User ID of creator")


class TemplateVersionResponse(TemplateVersionBase):
    """Schema for template version response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    template_id: UUID
    created_by: UUID
    created_at: datetime


class TemplateSectionSkillBindingResponse(BaseModel):
    """Skill binding response for one template section."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    section_id: UUID
    skill_id: UUID
    order_index: int
    is_required: bool
    prompt_override: str | None = None
    created_by: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    skill: SkillCatalogResponse | None = None


class TemplateSectionBase(BaseModel):
    """Base schema for structured template sections."""

    template_version_id: UUID | None = None
    parent_section_id: UUID | None = None
    section_key: str = Field(..., min_length=1, max_length=120)
    title: str = Field(..., min_length=1, max_length=255)
    level: int = Field(default=1, ge=1, le=6)
    position: int = Field(default=0, ge=0)
    content_requirement: str = Field(default="")
    prompt: str = Field(default="")
    required_inputs: list[str] = Field(default_factory=list)
    quality_rules: list[dict[str, Any]] = Field(default_factory=list)


class TemplateSectionCreate(TemplateSectionBase):
    """Create a structured template section."""

    pass


class TemplateSectionUpdate(BaseModel):
    """Update a structured template section."""

    parent_section_id: UUID | None = None
    section_key: str | None = Field(None, min_length=1, max_length=120)
    title: str | None = Field(None, min_length=1, max_length=255)
    level: int | None = Field(None, ge=1, le=6)
    position: int | None = Field(None, ge=0)
    content_requirement: str | None = None
    prompt: str | None = None
    required_inputs: list[str] | None = None
    quality_rules: list[dict[str, Any]] | None = None


class TemplateSectionSkillBindingUpdate(BaseModel):
    """Replace the ordered skill bindings for one section."""

    skill_ids: list[UUID] = Field(default_factory=list)


class TemplateSectionResponse(TemplateSectionBase):
    """Structured template section response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    template_version_id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    skill_bindings: list[TemplateSectionSkillBindingResponse] = Field(default_factory=list)


# Template Upload and Parse Schemas
class TemplateUploadRequest(BaseModel):
    """Schema for uploading a new template version."""

    file_content: bytes = Field(..., description="Template file content as bytes")
    file_hash: str | None = Field(None, description="SHA256 hash of file content")
    description: str | None = Field(None, description="Description of changes in this version")


class TemplateParseRequest(BaseModel):
    """Schema for requesting template parsing."""

    file_content: bytes = Field(..., description="Template file content to parse")
    doc_type: str = Field(..., description="Document type hint")


class ParsedTemplate(BaseModel):
    """Schema for parsed template result."""

    placeholders: list[PlaceholderSchema] = Field(default_factory=list, description="Extracted placeholders")
    page_types: list[PageTypeSchema] = Field(default_factory=list, description="Page type definitions")
    file_hash: str | None = Field(None, description="SHA256 hash of template")
    total_pages: int = Field(default=0, description="Total number of pages/slides")
    is_valid: bool = Field(default=True, description="Whether template is valid for processing")
    warnings: list[str] = Field(default_factory=list, description="Non-blocking template quality warnings")
    errors: list[str] = Field(default_factory=list, description="Blocking template parsing or governance errors")
    invalid_placeholders: list[str] = Field(default_factory=list, description="Placeholders that do not meet naming rules")
    duplicate_placeholders: list[str] = Field(default_factory=list, description="Placeholder names used more than once")
    content_format: str = Field(default="text", description="Detected template content format")


# Rebuild forward references
TemplateDetailResponse.model_rebuild()
