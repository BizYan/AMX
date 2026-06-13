"""Raw Artifact Store API Router

Endpoints for raw artifact management, retrieval, and replay.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.security import decode_token
from app.domains.providers.raw_artifact import RawArtifact
from app.domains.providers.raw_artifact_schemas import (
    RawArtifactCreate,
    RawArtifactUpdate,
    RawArtifactResponse,
    RawArtifactListItem,
    RawArtifactSearch,
    RawArtifactVersionSummary,
    RawArtifactReplayRequest,
    RawArtifactReplayResponse,
)
from app.domains.providers.raw_artifact_service import RawArtifactService
from app.domains.providers.schemas import PaginatedResponse
from app.models.identity import User


router = APIRouter(prefix="/providers/artifacts", tags=["provider-artifacts"])


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
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


def get_artifact_service(db: AsyncSession) -> RawArtifactService:
    """Dependency to get raw artifact service."""
    return RawArtifactService(db)


# Artifact Endpoints
@router.get("", response_model=PaginatedResponse[RawArtifactListItem])
async def list_artifacts(
    provider_id: UUID | None = Query(None, description="Filter by provider"),
    artifact_type: str | None = Query(None, description="Filter by artifact type"),
    project_id: UUID | None = Query(None, description="Filter by project"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List raw artifacts for the current tenant.

    Args:
        provider_id: Optional filter by provider UUID
        artifact_type: Optional filter by artifact type
        project_id: Optional filter by project UUID
        page: Page number (1-indexed)
        page_size: Number of items per page
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of raw artifacts
    """
    service = get_artifact_service(db)
    skip = (page - 1) * page_size

    artifacts, total = await service.list(
        tenant_id=current_user.tenant_id,
        provider_id=provider_id,
        artifact_type=artifact_type,
        project_id=project_id,
        skip=skip,
        limit=page_size,
    )

    has_more = (page * page_size) < total

    return PaginatedResponse(
        items=[RawArtifactListItem.model_validate(a) for a in artifacts],
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


@router.get("/{artifact_id}", response_model=RawArtifactResponse)
async def get_artifact(
    artifact_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a raw artifact by ID.

    Args:
        artifact_id: Artifact UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Raw artifact details

    Raises:
        HTTPException: If artifact not found or access denied
    """
    service = get_artifact_service(db)
    artifact = await service.get(artifact_id, current_user.tenant_id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return RawArtifactResponse.model_validate(artifact)


@router.get("/{artifact_id}/replay", response_model=RawArtifactReplayResponse)
async def replay_artifact(
    artifact_id: UUID,
    normalize_only: bool = Query(default=True, description="Only normalize without storing"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replay artifact to test normalization.

    This endpoint retrieves the raw artifact content and runs it through
    the normalization process to verify the output or generate a normalized
    graph for comparison.

    Args:
        artifact_id: Artifact UUID
        normalize_only: If True, only return normalized output without storing
        db: Database session
        current_user: Current authenticated user

    Returns:
        Replay results with normalized graph ID

    Raises:
        HTTPException: If artifact not found or replay fails
    """
    service = get_artifact_service(db)
    artifact = await service.get(artifact_id, current_user.tenant_id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    try:
        # Import normalizer based on artifact type
        if artifact.artifact_type == "graph":
            from app.integrations.graphify.normalizer import GraphifyNormalizer

            normalizer = GraphifyNormalizer()
            normalized = await normalizer.normalize(artifact.content)

            if not normalize_only:
                # Update artifact with normalized reference
                await service.update_normalized_reference(
                    artifact_id=artifact_id,
                    tenant_id=current_user.tenant_id,
                    normalized_graph_id=normalized.get("id"),
                )

            return RawArtifactReplayResponse(
                success=True,
                artifact_id=artifact_id,
                normalized_graph_id=normalized.get("id"),
                message="Graph normalization successful",
                replayed_at=datetime.now(timezone.utc),
            )

        elif artifact.artifact_type == "wiki":
            from app.integrations.gitnexus.normalizer import WikiNormalizer

            normalizer = WikiNormalizer()
            normalized = await normalizer.normalize(artifact.content)

            return RawArtifactReplayResponse(
                success=True,
                artifact_id=artifact_id,
                normalized_graph_id=normalized.get("id"),
                message="Wiki normalization successful",
                replayed_at=datetime.now(timezone.utc),
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported artifact type for replay: {artifact.artifact_type}",
            )

    except Exception as e:
        return RawArtifactReplayResponse(
            success=False,
            artifact_id=artifact_id,
            normalized_graph_id=None,
            message=f"Replay failed: {str(e)}",
            replayed_at=datetime.now(timezone.utc),
        )


@router.get("/by-provider/{provider_id}", response_model=PaginatedResponse[RawArtifactListItem])
async def list_artifacts_by_provider(
    provider_id: UUID,
    artifact_type: str | None = Query(None, description="Filter by artifact type"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all artifacts for a specific provider.

    Args:
        provider_id: Provider UUID
        artifact_type: Optional filter by artifact type
        page: Page number (1-indexed)
        page_size: Number of items per page
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of provider artifacts
    """
    service = get_artifact_service(db)
    skip = (page - 1) * page_size

    artifacts, total = await service.list(
        tenant_id=current_user.tenant_id,
        provider_id=provider_id,
        artifact_type=artifact_type,
        skip=skip,
        limit=page_size,
    )

    has_more = (page * page_size) < total

    return PaginatedResponse(
        items=[RawArtifactListItem.model_validate(a) for a in artifacts],
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


@router.get("/by-provider/{provider_id}/versions", response_model=list[RawArtifactVersionSummary])
async def get_provider_artifact_versions(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all artifact versions for provider comparison.

    Args:
        provider_id: Provider UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        List of version summaries with artifact counts
    """
    service = get_artifact_service(db)

    versions = await service.get_versions(
        provider_id=provider_id,
        tenant_id=current_user.tenant_id,
    )

    return [
        RawArtifactVersionSummary(
            provider_id=provider_id,
            provider_name="",  # Will be populated by caller if needed
            total_artifacts=v["artifact_count"],
            latest_version=v["version_id"],
            versions=versions,
        )
        for v in [versions]  # Wrap single version in list format
    ]


@router.post("", response_model=RawArtifactResponse, status_code=201)
async def create_artifact(
    data: RawArtifactCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Store a new raw artifact.

    Args:
        data: Artifact creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created raw artifact
    """
    service = get_artifact_service(db)

    # Check for duplicate by content hash
    content_hash = service.compute_content_hash(data.content)
    existing = await service.get_by_hash(content_hash, current_user.tenant_id)

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Artifact with identical content already exists",
        )

    artifact = await service.store(
        tenant_id=current_user.tenant_id,
        project_id=data.project_id,
        provider_id=data.provider_id,
        version_id=data.provider_version_id,
        run_id=data.provider_run_id,
        artifact_type=data.artifact_type,
        content=data.content,
        schema_version=data.schema_version,
        upstream_pin=data.upstream_pin,
        created_by=data.created_by or current_user.id,
    )

    return RawArtifactResponse.model_validate(artifact)


@router.patch("/{artifact_id}", response_model=RawArtifactResponse)
async def update_artifact(
    artifact_id: UUID,
    data: RawArtifactUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a raw artifact.

    Args:
        artifact_id: Artifact UUID
        data: Update data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated raw artifact

    Raises:
        HTTPException: If artifact not found
    """
    service = get_artifact_service(db)
    artifact = await service.get(artifact_id, current_user.tenant_id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if data.normalized_graph_id is not None:
        artifact.normalized_graph_id = data.normalized_graph_id

    if data.upstream_pin is not None:
        artifact.upstream_pin = data.upstream_pin

    await db.flush()
    await db.refresh(artifact)

    return RawArtifactResponse.model_validate(artifact)


@router.delete("/{artifact_id}", status_code=204)
async def delete_artifact(
    artifact_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a raw artifact (soft delete).

    Args:
        artifact_id: Artifact UUID
        db: Database session
        current_user: Current authenticated user

    Raises:
        HTTPException: If artifact not found
    """
    service = get_artifact_service(db)
    deleted = await service.delete(artifact_id, current_user.tenant_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Artifact not found")
