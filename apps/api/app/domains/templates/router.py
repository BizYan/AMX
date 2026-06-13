"""Templates Domain API Router

Endpoints for template management, upload, parsing, and versioning.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.security import decode_token
from app.domains.templates.models import Template, TemplateVersion
from app.domains.templates.schemas import (
    TemplateCreate,
    TemplateUpdate,
    TemplateResponse,
    TemplateDetailResponse,
    TemplateVersionCreate,
    TemplateVersionResponse,
    TemplateUploadRequest,
    TemplateParseRequest,
    ParsedTemplate,
    PlaceholderSchema,
    PageTypeSchema,
    TemplateSectionCreate,
    TemplateSectionUpdate,
    TemplateSectionResponse,
    TemplateSectionSkillBindingResponse,
    TemplateSectionSkillBindingUpdate,
)
from app.domains.templates.service import TemplateService, TemplateSectionService
from app.models.identity import User


router = APIRouter()


async def get_current_user(
    authorization: str = Header(..., description="Bearer token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency to get current authenticated user."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization[7:]

    try:
        from app.domains.identity.service import AuthService

        auth_service = AuthService(db)
        user = await auth_service.get_current_user(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_template_service(db: AsyncSession = Depends(get_db)) -> TemplateService:
    """Dependency to get template service."""
    return TemplateService(db)


async def get_template_section_service(db: AsyncSession = Depends(get_db)) -> TemplateSectionService:
    """Dependency to get template section service."""
    return TemplateSectionService(db)


# Template CRUD Endpoints
@router.post("/", response_model=TemplateResponse, status_code=201)
async def create_template(
    template_data: TemplateCreate,
    service: TemplateService = Depends(get_template_service),
    current_user: User = Depends(get_current_user),
):
    """Create a new template."""
    template = await service.create_template(
        tenant_id=current_user.tenant_id,
        template_data=template_data,
        created_by=current_user.id,
    )
    return template


@router.get("/", response_model=list[TemplateResponse])
async def list_templates(
    doc_type: str | None = Query(None, description="Filter by document type"),
    service: TemplateService = Depends(get_template_service),
    current_user: User = Depends(get_current_user),
):
    """List templates for the current tenant."""
    templates, _ = await service.list_templates(
        tenant_id=current_user.tenant_id,
        doc_type=doc_type,
    )
    return templates


@router.get("/{template_id}", response_model=TemplateDetailResponse)
async def get_template(
    template_id: UUID,
    service: TemplateService = Depends(get_template_service),
    current_user: User = Depends(get_current_user),
):
    """Get template details with all versions."""
    template = await service.get_template_with_versions(
        tenant_id=current_user.tenant_id,
        template_id=template_id,
    )
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.patch("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: UUID,
    update_data: TemplateUpdate,
    service: TemplateService = Depends(get_template_service),
    current_user: User = Depends(get_current_user),
):
    """Update template metadata."""
    template = await service.update_template(
        tenant_id=current_user.tenant_id,
        template_id=template_id,
        update_data=update_data,
    )
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: UUID,
    service: TemplateService = Depends(get_template_service),
    current_user: User = Depends(get_current_user),
):
    """Soft-delete a template."""
    await service.soft_delete_template(
        tenant_id=current_user.tenant_id,
        template_id=template_id,
    )


# Template Version Endpoints
@router.post("/{template_id}/versions", response_model=TemplateVersionResponse, status_code=201)
async def create_template_version(
    template_id: UUID,
    version_data: TemplateVersionCreate,
    service: TemplateService = Depends(get_template_service),
    current_user: User = Depends(get_current_user),
):
    """Create a new version for an existing template."""
    version = await service.create_template_version(
        tenant_id=current_user.tenant_id,
        template_id=template_id,
        version_data=version_data,
        created_by=current_user.id,
    )
    if not version:
        raise HTTPException(status_code=404, detail="Template not found")
    return version


@router.get("/{template_id}/versions", response_model=list[TemplateVersionResponse])
async def list_template_versions(
    template_id: UUID,
    service: TemplateService = Depends(get_template_service),
    current_user: User = Depends(get_current_user),
):
    """List all versions of a template."""
    versions = await service.list_template_versions(
        tenant_id=current_user.tenant_id,
        template_id=template_id,
    )
    return versions


@router.get("/{template_id}/versions/{version_id}", response_model=TemplateVersionResponse)
async def get_template_version(
    template_id: UUID,
    version_id: UUID,
    service: TemplateService = Depends(get_template_service),
    current_user: User = Depends(get_current_user),
):
    """Get a specific version of a template."""
    version = await service.get_template_version(
        tenant_id=current_user.tenant_id,
        template_id=template_id,
        version_id=version_id,
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    return version


@router.get("/{template_id}/sections", response_model=list[TemplateSectionResponse])
async def list_template_sections(
    template_id: UUID,
    version_id: UUID | None = Query(None, description="Optional template version filter"),
    service: TemplateSectionService = Depends(get_template_section_service),
    current_user: User = Depends(get_current_user),
):
    """List structured sections for a template."""
    return await service.list_template_sections(
        tenant_id=current_user.tenant_id,
        template_id=template_id,
        version_id=version_id,
    )


@router.post("/{template_id}/versions/{version_id}/activate", response_model=TemplateVersionResponse)
async def activate_template_version(
    template_id: UUID,
    version_id: UUID,
    service: TemplateService = Depends(get_template_service),
    current_user: User = Depends(get_current_user),
):
    """Set a template version as the active version for generation and export."""
    version = await service.activate_template_version(
        tenant_id=current_user.tenant_id,
        template_id=template_id,
        version_id=version_id,
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    return version


@router.post("/{template_id}/sections/seed", response_model=list[TemplateSectionResponse], status_code=201)
async def seed_template_sections(
    template_id: UUID,
    version_id: UUID | None = Query(None, description="Optional template version"),
    template_service: TemplateService = Depends(get_template_service),
    section_service: TemplateSectionService = Depends(get_template_section_service),
    current_user: User = Depends(get_current_user),
):
    """Seed standard sections for the template document type."""
    template = await template_service.get_template(
        tenant_id=current_user.tenant_id,
        template_id=template_id,
    )
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    template_version = None
    if version_id:
        template_version = await template_service.get_template_version(
            tenant_id=current_user.tenant_id,
            template_id=template_id,
            version_id=version_id,
        )
    else:
        template_version = await section_service.get_active_template_version(
            tenant_id=current_user.tenant_id,
            template_id=template_id,
        )

    if not template_version:
        raise HTTPException(status_code=404, detail="Template version not found")

    try:
        return await section_service.seed_standard_sections(
            tenant_id=current_user.tenant_id,
            template_version_id=template_version.id,
            doc_type=template.doc_type,
            created_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{template_id}/sections", response_model=TemplateSectionResponse, status_code=201)
async def create_template_section(
    template_id: UUID,
    data: TemplateSectionCreate,
    template_service: TemplateService = Depends(get_template_service),
    section_service: TemplateSectionService = Depends(get_template_section_service),
    current_user: User = Depends(get_current_user),
):
    """Create a structured section for a template."""
    template_version_id = data.template_version_id
    if not template_version_id:
        template_version = await section_service.get_active_template_version(
            tenant_id=current_user.tenant_id,
            template_id=template_id,
        )
        if not template_version:
            raise HTTPException(status_code=404, detail="Template version not found")
        template_version_id = template_version.id
    else:
        template_version = await template_service.get_template_version(
            tenant_id=current_user.tenant_id,
            template_id=template_id,
            version_id=template_version_id,
        )
        if not template_version:
            raise HTTPException(status_code=404, detail="Template version not found")

    try:
        return await section_service.create_template_section(
            tenant_id=current_user.tenant_id,
            template_version_id=template_version_id,
            data=data,
            created_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/sections/{section_id}", response_model=TemplateSectionResponse)
async def update_template_section(
    section_id: UUID,
    data: TemplateSectionUpdate,
    service: TemplateSectionService = Depends(get_template_section_service),
    current_user: User = Depends(get_current_user),
):
    """Update a structured template section."""
    try:
        section = await service.update_template_section(
            tenant_id=current_user.tenant_id,
            section_id=section_id,
            data=data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not section:
        raise HTTPException(status_code=404, detail="Template section not found")
    return section


@router.delete("/sections/{section_id}", status_code=204)
async def delete_template_section(
    section_id: UUID,
    service: TemplateSectionService = Depends(get_template_section_service),
    current_user: User = Depends(get_current_user),
):
    """Soft-delete a structured template section."""
    deleted = await service.delete_template_section(
        tenant_id=current_user.tenant_id,
        section_id=section_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Template section not found")


@router.put(
    "/sections/{section_id}/skills",
    response_model=list[TemplateSectionSkillBindingResponse],
)
async def replace_template_section_skills(
    section_id: UUID,
    data: TemplateSectionSkillBindingUpdate,
    service: TemplateSectionService = Depends(get_template_section_service),
    current_user: User = Depends(get_current_user),
):
    """Replace ordered skill bindings for a template section."""
    try:
        return await service.replace_section_skill_bindings(
            tenant_id=current_user.tenant_id,
            section_id=section_id,
            skill_ids=data.skill_ids,
            created_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Template Parse Endpoint
@router.post("/parse", response_model=ParsedTemplate)
async def parse_template(
    request: TemplateParseRequest,
    service: TemplateService = Depends(get_template_service),
    current_user: User = Depends(get_current_user),
):
    """Parse a template file to extract placeholders and page types."""
    parsed = await service.parse_template(
        tenant_id=current_user.tenant_id,
        file_content=request.file_content,
        doc_type=request.doc_type,
    )
    return parsed


@router.post("/parse-upload", response_model=ParsedTemplate)
async def parse_uploaded_template(
    file: UploadFile = File(...),
    doc_type: str = Query(..., description="Document type hint"),
    service: TemplateService = Depends(get_template_service),
    current_user: User = Depends(get_current_user),
):
    """Parse an uploaded DOCX/PPTX/text template before saving it as a version."""
    content = await file.read()
    parsed = await service.parse_template(
        tenant_id=current_user.tenant_id,
        file_content=content,
        doc_type=doc_type,
    )
    return parsed


# Template Upload Endpoint
@router.post("/upload", response_model=TemplateVersionResponse, status_code=201)
async def upload_template(
    template_id: UUID,
    file: UploadFile = File(...),
    description: str | None = Query(None, description="Version description"),
    service: TemplateService = Depends(get_template_service),
    current_user: User = Depends(get_current_user),
):
    """Upload a new template file and create a version."""
    content = await file.read()

    version = await service.upload_template_version(
        tenant_id=current_user.tenant_id,
        template_id=template_id,
        file_content=content,
        description=description,
        created_by=current_user.id,
    )
    if not version:
        raise HTTPException(status_code=404, detail="Template not found")
    return version
