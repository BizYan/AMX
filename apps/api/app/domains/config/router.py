"""Config Domain API Router

FastAPI endpoints for ConfigUnit management.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.identity import User
from app.domains.config.models import ConfigUnit
from app.domains.config.schemas import (
    ConfigUnitCreate,
    ConfigUnitUpdate,
    ConfigUnitResponse,
    ConfigUnitListResponse,
    ConfigUnitPublishResponse,
    ConfigUnitTestRequest,
    ConfigUnitTestResponse,
    PaginationParams,
)
from app.domains.config.service import ConfigUnitService


router = APIRouter()


async def get_current_user(
    authorization: str = Header(..., description="Bearer token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency to get current authenticated user.

    Args:
        authorization: Bearer token header
        db: Database session

    Returns:
        User: Current authenticated user

    Raises:
        HTTPException: If token is invalid or user not found
    """
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
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


# ConfigUnit Endpoints

@router.get("", response_model=ConfigUnitListResponse)
async def list_config_units(
    doc_type: str | None = Query(None, description="Filter by document type"),
    pagination: PaginationParams = Query(default=PaginationParams()),
    include_inactive: bool = Query(False, description="Include inactive config units"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all ConfigUnits for the current tenant.

    Args:
        doc_type: Optional document type filter
        pagination: Pagination parameters
        include_inactive: Whether to include inactive units
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of ConfigUnits
    """
    service = ConfigUnitService(db)
    config_units, total = await service.list_config_units(
        tenant_id=current_user.tenant_id,
        doc_type=doc_type,
        page=pagination.page,
        page_size=pagination.page_size,
        include_inactive=include_inactive,
    )
    has_more = (pagination.page * pagination.page_size) < total

    return ConfigUnitListResponse(
        items=[ConfigUnitResponse.model_validate(c) for c in config_units],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=has_more,
    )


@router.post("", response_model=ConfigUnitResponse, status_code=201)
async def create_config_unit(
    data: ConfigUnitCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new ConfigUnit.

    Args:
        data: ConfigUnit creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created ConfigUnit
    """
    service = ConfigUnitService(db)
    config_unit = await service.create_config_unit(
        tenant_id=current_user.tenant_id,
        name=data.name,
        doc_type=data.doc_type,
        entity_schema=data.entity_schema,
        document_structure=data.document_structure,
        generation_prompt=data.generation_prompt,
        quality_rules=data.quality_rules,
        bound_skills=data.bound_skills,
        node_flow=data.node_flow,
        description=data.description,
    )
    return ConfigUnitResponse.model_validate(config_unit)


@router.get("/{config_unit_id}", response_model=ConfigUnitResponse)
async def get_config_unit(
    config_unit_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a ConfigUnit by ID.

    Args:
        config_unit_id: ConfigUnit UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        ConfigUnit

    Raises:
        HTTPException: If ConfigUnit not found
    """
    service = ConfigUnitService(db)
    config_unit = await service.get_config_unit(
        config_unit_id=config_unit_id,
        tenant_id=current_user.tenant_id,
    )

    if not config_unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ConfigUnit not found",
        )

    return ConfigUnitResponse.model_validate(config_unit)


@router.patch("/{config_unit_id}", response_model=ConfigUnitResponse)
async def update_config_unit(
    config_unit_id: UUID,
    data: ConfigUnitUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a ConfigUnit.

    Args:
        config_unit_id: ConfigUnit UUID
        data: Update data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated ConfigUnit

    Raises:
        HTTPException: If ConfigUnit not found
    """
    service = ConfigUnitService(db)
    config_unit = await service.update_config_unit(
        config_unit_id=config_unit_id,
        tenant_id=current_user.tenant_id,
        updates=data,
    )

    if not config_unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ConfigUnit not found",
        )

    return ConfigUnitResponse.model_validate(config_unit)


@router.delete("/{config_unit_id}", status_code=204)
async def delete_config_unit(
    config_unit_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a ConfigUnit (soft delete).

    Args:
        config_unit_id: ConfigUnit UUID
        db: Database session
        current_user: Current authenticated user

    Raises:
        HTTPException: If ConfigUnit not found
    """
    service = ConfigUnitService(db)
    deleted = await service.delete_config_unit(
        config_unit_id=config_unit_id,
        tenant_id=current_user.tenant_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ConfigUnit not found",
        )


@router.post("/{config_unit_id}/publish", response_model=ConfigUnitPublishResponse)
async def publish_config_unit(
    config_unit_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Publish a ConfigUnit (set is_active=True and bump version).

    Args:
        config_unit_id: ConfigUnit UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Publish response with new version

    Raises:
        HTTPException: If ConfigUnit not found
    """
    service = ConfigUnitService(db)
    config_unit = await service.publish_config_unit(
        config_unit_id=config_unit_id,
        tenant_id=current_user.tenant_id,
        released_by=current_user.id,
    )

    if not config_unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ConfigUnit not found",
        )

    return ConfigUnitPublishResponse(
        id=config_unit.id,
        version=config_unit.version,
        is_active=config_unit.is_active,
        released_at=config_unit.released_at,
        released_by=config_unit.released_by,
    )


@router.post("/{config_unit_id}/test", response_model=ConfigUnitTestResponse)
async def test_config_unit(
    config_unit_id: UUID,
    data: ConfigUnitTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test a ConfigUnit in sandbox mode.

    Args:
        config_unit_id: ConfigUnit UUID
        data: Test request with input data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Test response with results
    """
    service = ConfigUnitService(db)
    result = await service.test_config_unit(
        config_unit_id=config_unit_id,
        tenant_id=current_user.tenant_id,
        test_data=data.test_data,
        mode=data.mode,
    )

    return ConfigUnitTestResponse(
        success=result["success"],
        output=result["output"],
        errors=result["errors"],
        quality_score=result["quality_score"],
    )
