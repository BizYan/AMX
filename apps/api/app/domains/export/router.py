"""Export Domain API Router

FastAPI endpoints for document export to Word, Markdown, and PPTX formats.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.security import decode_token
from app.models.identity import User
from app.domains.export.models import ExportStatus
from app.domains.export.schemas import (
    WordExportRequest,
    MarkdownExportRequest,
    PPTXExportRequest,
    ProjectPackageExportRequest,
    ExportJobResponse,
    ExportJobWithArtifactsResponse,
    ExportJobCreatedResponse,
    ExportStatusResponse,
    ExportArtifactResponse,
    ExportArtifactDownloadResponse,
    ExportReadinessResponse,
    ExportReleaseEvidenceResponse,
)
from app.domains.export.service import ExportService
from app.services.storage import get_storage_provider


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


async def check_document_access(
    document_id: UUID,
    user_id: UUID,
    db: AsyncSession,
    tenant_id: UUID,
) -> bool:
    """Check if user has access to document.

    Args:
        document_id: Document UUID
        user_id: User UUID
        db: Database session
        tenant_id: Tenant UUID

    Returns:
        True if access allowed

    Raises:
        HTTPException: If access denied or document not found
    """
    from sqlalchemy import select
    from app.domains.documents.models import Document
    from app.models.projects import Project, ProjectMember

    # Get document
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
        )
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check if user is the document creator
    if document.created_by == user_id:
        return True

    # Check if user is project owner
    result = await db.execute(
        select(Project).where(
            Project.id == document.project_id,
            Project.owner_id == user_id,
            Project.tenant_id == tenant_id,
            Project.deleted_at.is_(None),
        )
    )
    if result.scalar_one_or_none():
        return True

    # Check if user is a project member
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == document.project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if result.scalar_one_or_none():
        return True

    raise HTTPException(status_code=403, detail="Access denied")


async def check_project_access(
    project_id: UUID,
    user_id: UUID,
    db: AsyncSession,
    tenant_id: UUID,
) -> bool:
    """Check if user can export a project delivery package."""
    from sqlalchemy import select
    from app.models.projects import Project, ProjectMember

    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == user_id,
            Project.tenant_id == tenant_id,
            Project.deleted_at.is_(None),
        )
    )
    if result.scalar_one_or_none():
        return True

    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if result.scalar_one_or_none():
        return True

    raise HTTPException(status_code=403, detail="Access denied")


@router.get("", response_model=list[ExportJobWithArtifactsResponse])
async def list_exports(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all export jobs for the tenant."""
    service = ExportService(db)
    jobs = await service.list_jobs(current_user.tenant_id)
    return [ExportJobWithArtifactsResponse.model_validate(j) for j in jobs]


@router.get("/readiness", response_model=ExportReadinessResponse)
async def get_export_readiness(
    project_id: UUID = Query(..., description="Project UUID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get production delivery package readiness for a project."""
    await check_project_access(
        project_id, current_user.id, db, current_user.tenant_id
    )
    service = ExportService(db)
    try:
        return await service.get_project_export_readiness(
            project_id=project_id,
            tenant_id=current_user.tenant_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/release-evidence", response_model=ExportReleaseEvidenceResponse)
async def get_export_release_evidence(
    project_id: UUID = Query(..., description="Project UUID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get project delivery package release evidence and gate status."""
    await check_project_access(
        project_id, current_user.id, db, current_user.tenant_id
    )
    service = ExportService(db)
    try:
        return await service.get_project_release_evidence(
            project_id=project_id,
            tenant_id=current_user.tenant_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/project-package", response_model=ExportJobCreatedResponse, status_code=201)
async def export_project_package(
    data: ProjectPackageExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export a project-level Markdown delivery package."""
    await check_project_access(
        data.project_id, current_user.id, db, current_user.tenant_id
    )

    user_role_id = None
    if current_user.roles:
        user_role_id = current_user.roles[0].role_id

    service = ExportService(db)
    try:
        job = await service.export_project_package(
            project_id=data.project_id,
            tenant_id=current_user.tenant_id,
            document_ids=data.document_ids,
            title=data.title,
            include_drafts=data.include_drafts,
            include_manifest=data.include_manifest,
            formats=data.formats,
            include_audit=data.include_audit,
            watermark=data.watermark,
            variables=data.variables,
            created_by=current_user.id,
            user_role_id=user_role_id,
        )
        return ExportJobCreatedResponse(
            job_id=job.id,
            status=job.status,
            message="Project package export job created successfully",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/word", response_model=ExportJobCreatedResponse, status_code=201)
async def export_word(
    data: WordExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export document to Word format.

    Args:
        data: Word export parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Export job details

    Raises:
        HTTPException: If document not found or access denied
    """
    # Check document access
    await check_document_access(
        data.document_id, current_user.id, db, current_user.tenant_id
    )

    # Get user's primary role for field permission filtering
    user_role_id = None
    if current_user.roles:
        user_role_id = current_user.roles[0].role_id

    service = ExportService(db)
    try:
        job = await service.export_word(
            document_id=data.document_id,
            template_id=data.template_id,
            tenant_id=current_user.tenant_id,
            variables=data.variables,
            title=data.title,
            created_by=current_user.id,
            user_role_id=user_role_id,
        )
        return ExportJobCreatedResponse(
            job_id=job.id,
            status=job.status,
            message="Word export job created successfully",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/markdown", response_model=ExportJobCreatedResponse, status_code=201)
async def export_markdown(
    data: MarkdownExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export document to Markdown format.

    Args:
        data: Markdown export parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Export job details

    Raises:
        HTTPException: If document not found or access denied
    """
    # Check document access
    await check_document_access(
        data.document_id, current_user.id, db, current_user.tenant_id
    )

    # Get user's primary role for field permission filtering
    user_role_id = None
    if current_user.roles:
        user_role_id = current_user.roles[0].role_id

    service = ExportService(db)
    try:
        job = await service.export_markdown(
            document_id=data.document_id,
            tenant_id=current_user.tenant_id,
            variables=data.variables,
            title=data.title,
            created_by=current_user.id,
            user_role_id=user_role_id,
        )
        return ExportJobCreatedResponse(
            job_id=job.id,
            status=job.status,
            message="Markdown export job created successfully",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/pptx", response_model=ExportJobCreatedResponse, status_code=201)
async def export_pptx(
    data: PPTXExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export document to PowerPoint format.

    Args:
        data: PPTX export parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Export job details

    Raises:
        HTTPException: If document not found or access denied
    """
    # Check document access
    await check_document_access(
        data.document_id, current_user.id, db, current_user.tenant_id
    )

    # Get user's primary role for field permission filtering
    user_role_id = None
    if current_user.roles:
        user_role_id = current_user.roles[0].role_id

    service = ExportService(db)
    try:
        job = await service.export_pptx(
            document_id=data.document_id,
            template_id=data.template_id,
            tenant_id=current_user.tenant_id,
            variables=data.variables,
            title=data.title,
            created_by=current_user.id,
            user_role_id=user_role_id,
        )
        return ExportJobCreatedResponse(
            job_id=job.id,
            status=job.status,
            message="PPTX export job created successfully",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/jobs/{job_id}", response_model=ExportStatusResponse)
async def get_job_status(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get export job status.

    Args:
        job_id: Export job UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Export job status

    Raises:
        HTTPException: If job not found or access denied
    """
    service = ExportService(db)
    job = await service.get_job_status(job_id, current_user.tenant_id)

    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")

    # Calculate progress
    progress = 0
    if job.status == ExportStatus.PROCESSING.value:
        progress = 50
    elif job.status == ExportStatus.COMPLETED.value:
        progress = 100

    return ExportStatusResponse(
        job_id=job.id,
        status=job.status,
        progress_percent=progress,
        message=job.error_message,
        completed_at=job.completed_at,
    )


@router.get("/jobs/{job_id}/artifacts", response_model=list[ExportArtifactResponse])
async def get_job_artifacts(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get artifacts for an export job.

    Args:
        job_id: Export job UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        List of export artifacts

    Raises:
        HTTPException: If job not found or access denied
    """
    service = ExportService(db)
    job = await service.get_job(job_id, current_user.tenant_id)

    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")

    artifacts = job.artifacts

    return [ExportArtifactResponse.model_validate(a) for a in artifacts]


@router.get("/artifacts/{artifact_id}", response_model=ExportArtifactDownloadResponse)
async def get_artifact(
    artifact_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get export artifact download details.

    Args:
        artifact_id: Export artifact UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Artifact download details

    Raises:
        HTTPException: If artifact not found or access denied
    """
    service = ExportService(db)
    artifact = await service.get_artifact(artifact_id, current_user.tenant_id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Export artifact not found")

    # Get download URL from storage
    from app.services.storage import StorageHandle

    storage = get_storage_provider()
    handle = StorageHandle(
        path=artifact.storage_path,
        filename=artifact.filename,
        content_type=artifact.content_type,
        size=artifact.file_size,
        hash=artifact.file_hash or "",
        storage_backend="local",
    )
    download_url = await storage.get_url(handle)

    return ExportArtifactDownloadResponse(
        artifact_id=artifact.id,
        filename=artifact.filename,
        content_type=artifact.content_type,
        file_size=artifact.file_size,
        download_url=download_url,
    )


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download an export artifact.

    Args:
        artifact_id: Export artifact UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        File download response

    Raises:
        HTTPException: If artifact not found or access denied
    """
    from fastapi.responses import StreamingResponse
    from app.services.storage import StorageHandle

    service = ExportService(db)
    artifact = await service.get_artifact(artifact_id, current_user.tenant_id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Export artifact not found")

    storage = get_storage_provider()
    handle = StorageHandle(
        path=artifact.storage_path,
        filename=artifact.filename,
        content_type=artifact.content_type,
        size=artifact.file_size,
        hash=artifact.file_hash or "",
        storage_backend="local",
    )

    try:
        content = await storage.download(handle)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Export file not found")

    return StreamingResponse(
        iter([content]),
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "Content-Length": str(artifact.file_size),
        },
    )
