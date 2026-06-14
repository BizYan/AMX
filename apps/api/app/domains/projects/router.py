"""Projects Domain API Router

Endpoints for project management, members, and source files.
"""

from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import secrets
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Header
from fastapi.responses import StreamingResponse
from pydantic import EmailStr
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.security import decode_token
from app.domains.projects.models import ProjectInvitation
from app.domains.projects.schemas import (
    CustomerPortalAcceptanceSubmit,
    CustomerPortalLinkCreate,
    CustomerPortalLinkCreatedResponse,
    CustomerPortalLinkResponse,
    CustomerPortalSummaryResponse,
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectListResponse,
    ProjectLaunchBlueprint,
    ProjectLaunchCreate,
    ProjectLaunchPlanResponse,
    ProjectLaunchResponse,
    ProjectDeliveryPlanResponse,
    ProjectAcceptanceResponse,
    ProjectAcceptanceUpdate,
    ProjectMilestoneCreate,
    ProjectMilestoneUpdate,
    ProjectMilestoneReorder,
    ProjectMilestoneResponse,
    ProjectMemberCreate,
    ProjectMemberResponse,
    ProjectMemberListResponse,
    ProjectInvitationAcceptResponse,
    ProjectInvitationActivationRequest,
    ProjectInvitationActivationResponse,
    ProjectInvitationCreatedResponse,
    ProjectInvitationListResponse,
    ProjectInvitationPreviewResponse,
    ProjectInvitationResponse,
    ProjectSettingsUpdate,
    ProjectSettingsResponse,
    DocumentLifecyclePolicyResponse,
    DocumentLifecyclePolicyUpdate,
    ProjectDeliveryWorkbenchResponse,
    SystemDeliveryOverviewResponse,
    SystemDeliveryPortfolioResponse,
    SourceFileResponse,
    SourceFileListResponse,
    SourceFileCreate,
    SourceIngestionJobListResponse,
    SourceIngestionJobResponse,
    UploadUrlResponse,
    PaginationParams,
    MAX_FILE_SIZE,
    SUPPORTED_CONTENT_TYPES,
)
from app.domains.projects.service import (
    ProjectService,
    ProjectSettingsService,
    SourceFileService,
)
from app.domains.projects.lifecycle import ProjectDocumentLifecyclePolicyService
from app.domains.projects.launch_service import ProjectLaunchService
from app.domains.projects.delivery_plan_service import ProjectDeliveryPlanService
from app.domains.projects.invitation_service import InvitationError, ProjectInvitationService
from app.domains.projects.ingestion_service import SourceIngestionError, SourceIngestionService
from app.services.audit_service import AuditService
from app.services.storage import StorageHandle, StorageProvider, LocalStorageProvider, get_storage_provider
from app.models.identity import User
from app.models.projects import ProjectMember


router = APIRouter()


def _invitation_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _invitation_expired(expires_at: datetime) -> bool:
    normalized = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=timezone.utc)
    return normalized <= datetime.now(timezone.utc)


def _invitation_status(invitation: ProjectInvitation) -> str:
    if invitation.revoked_at is not None:
        return "revoked"
    if invitation.accepted_at is not None:
        return "accepted"
    if _invitation_expired(invitation.expires_at):
        return "expired"
    return "active"


def _invitation_response(invitation: ProjectInvitation) -> ProjectInvitationResponse:
    return ProjectInvitationResponse(
        id=invitation.id,
        project_id=invitation.project_id,
        email=invitation.email,
        status=_invitation_status(invitation),
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        revoked_at=invitation.revoked_at,
        created_at=invitation.created_at,
        updated_at=invitation.updated_at,
    )


async def _find_invitation_by_token(token: str, db: AsyncSession) -> ProjectInvitation | None:
    digest = _invitation_token_digest(token)
    result = await db.execute(
        select(ProjectInvitation).where(
            or_(ProjectInvitation.token == digest, ProjectInvitation.token == token),
            ProjectInvitation.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


@router.get("/customer-portal/{token}", response_model=CustomerPortalSummaryResponse)
async def get_customer_delivery_portal(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Open a token-scoped customer delivery portal without internal login."""
    try:
        return await ProjectDeliveryPlanService(db).get_customer_portal(token)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=410, detail=str(error)) from error


@router.post("/customer-portal/{token}/acceptance", response_model=CustomerPortalSummaryResponse)
async def submit_customer_delivery_acceptance(
    token: str,
    data: CustomerPortalAcceptanceSubmit,
    db: AsyncSession = Depends(get_db),
):
    """Submit a governed customer acceptance decision through a scoped link."""
    try:
        return await ProjectDeliveryPlanService(db).submit_customer_portal_acceptance(
            token, data
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@router.get("/customer-portal/{token}/artifacts/{artifact_id}/download")
async def download_customer_delivery_artifact(
    token: str,
    artifact_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Download a completed project-package artifact through an active portal link."""
    try:
        artifact = await ProjectDeliveryPlanService(db).get_customer_portal_artifact(
            token, artifact_id
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=410, detail=str(error)) from error
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
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Export file not found") from error
    return StreamingResponse(
        iter([content]),
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "Content-Length": str(artifact.file_size),
        },
    )


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

    token = authorization[7:]  # Strip "Bearer " prefix

    try:
        from app.domains.identity.service import AuthService

        auth_service = AuthService(db)
        user = await auth_service.get_current_user(token)

        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        return user
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


async def get_storage() -> StorageProvider:
    """Dependency to get storage provider.

    Returns:
        StorageProvider: Configured storage provider
    """
    return get_storage_provider()


async def check_project_membership(
    project_id: UUID,
    user_id: UUID,
    db: AsyncSession,
    tenant_id: UUID,
    require_owner: bool = False,
) -> bool:
    """Check if user is a member of the project.

    Args:
        project_id: Project UUID
        user_id: User UUID
        db: Database session
        tenant_id: Tenant UUID for multi-tenancy filtering
        require_owner: If True, user must be the project owner

    Returns:
        bool: True if user has access

    Raises:
        HTTPException: If user does not have access
    """
    from sqlalchemy import select
    from app.models.projects import Project, ProjectMember

    # Check if user is the project owner (with tenant filter)
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

    if require_owner:
        raise HTTPException(status_code=403, detail="Only project owner can perform this action")

    # Check if user is a project member (with tenant filter)
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if result.scalar_one_or_none():
        return True

    raise HTTPException(status_code=403, detail="Not a project member")


@router.post("/invitations/{token}/accept", response_model=ProjectInvitationAcceptResponse)
async def accept_project_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accept an active invitation when tenant and email match the signed-in user."""
    try:
        return await ProjectInvitationService(db).accept(token, current_user)
    except InvitationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.get("/invitations/{token}/preview", response_model=ProjectInvitationPreviewResponse)
async def preview_project_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Return only the public-safe context needed to evaluate an invitation."""
    try:
        return await ProjectInvitationService(db).preview(token)
    except InvitationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.post("/invitations/{token}/activate", response_model=ProjectInvitationActivationResponse)
async def activate_project_invitation(
    token: str,
    data: ProjectInvitationActivationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create the invited user's account and accept the invitation atomically."""
    try:
        return await ProjectInvitationService(db).activate(token, data)
    except InvitationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


# Project Endpoints
@router.get("", response_model=ProjectListResponse)
async def list_projects(
    pagination: PaginationParams = Query(default=PaginationParams()),
    status: str = Query(default="active", pattern="^(active|archived|all)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all projects for the current user.

    Args:
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of projects
    """
    service = ProjectService(db)
    projects, total = await service.list_projects(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
        status=None if status == "all" else status,
    )
    has_more = (pagination.page * pagination.page_size) < total

    return ProjectListResponse(
        items=[ProjectResponse.model_validate(p) for p in projects],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=has_more,
    )


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new project.

    Args:
        data: Project creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created project

    Raises:
        HTTPException: If slug already exists
    """
    service = ProjectService(db)
    try:
        project = await service.create_project(
            data=data,
            tenant_id=current_user.tenant_id,
            owner_id=current_user.id,
        )
        return ProjectResponse.model_validate(project)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/launch-blueprints", response_model=list[ProjectLaunchBlueprint])
async def list_project_launch_blueprints(
    current_user: User = Depends(get_current_user),
):
    """List platform project launch blueprints."""
    return ProjectLaunchService.list_blueprints()


@router.post("/launch", response_model=ProjectLaunchResponse, status_code=201)
async def launch_project(
    data: ProjectLaunchCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create and initialize a project from a delivery blueprint."""
    try:
        result = await ProjectLaunchService(db).launch(
            tenant_id=current_user.tenant_id,
            created_by=current_user.id,
            data=data,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.launch",
        resource_type="project",
        resource_id=result.project.id,
        metadata={
            "blueprint_key": result.plan.blueprint_key,
            "status": result.plan.status,
            "attempt_count": result.plan.attempt_count,
        },
    )
    return ProjectLaunchResponse(
        project=ProjectResponse.model_validate(result.project),
        plan=ProjectLaunchPlanResponse.model_validate(result.plan),
    )


@router.get("/delivery-overview", response_model=SystemDeliveryOverviewResponse)
async def get_system_delivery_overview(
    limit: int = Query(default=8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the system-level delivery command center for the current user."""
    service = ProjectService(db)
    overview = await service.get_system_delivery_overview(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        limit=limit,
    )
    return overview


@router.get("/delivery-portfolio", response_model=SystemDeliveryPortfolioResponse)
async def get_system_delivery_portfolio(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the complete visible cross-project milestone portfolio."""
    return await ProjectService(db).get_delivery_portfolio(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
    )


@router.get("/{project_id}/launch-plan", response_model=ProjectLaunchResponse)
async def get_project_launch_plan(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get project launch status, checks, and initialization evidence."""
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await ProjectLaunchService(db).get_result(project_id, current_user.tenant_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Project launch plan not found")
    return ProjectLaunchResponse(
        project=ProjectResponse.model_validate(result.project),
        plan=ProjectLaunchPlanResponse.model_validate(result.plan),
    )


@router.post("/{project_id}/launch-plan/retry", response_model=ProjectLaunchResponse)
async def retry_project_launch(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retry a project launch plan and idempotently repair missing assets."""
    try:
        await check_project_membership(
            project_id,
            current_user.id,
            db,
            current_user.tenant_id,
            require_owner=True,
        )
        result = await ProjectLaunchService(db).retry(
            project_id=project_id,
            tenant_id=current_user.tenant_id,
            requested_by=current_user.id,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except HTTPException:
        raise HTTPException(status_code=403, detail="Only owner can retry project launch")

    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.launch.retry",
        resource_type="project",
        resource_id=project_id,
        metadata={
            "blueprint_key": result.plan.blueprint_key,
            "status": result.plan.status,
            "attempt_count": result.plan.attempt_count,
        },
    )
    return ProjectLaunchResponse(
        project=ProjectResponse.model_validate(result.project),
        plan=ProjectLaunchPlanResponse.model_validate(result.plan),
    )


@router.get("/{project_id}/delivery-plan", response_model=ProjectDeliveryPlanResponse)
async def get_project_delivery_plan(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the executable project delivery plan."""
    await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    response = await ProjectDeliveryPlanService(db).build_response(project_id, current_user.tenant_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Project delivery plan not found")
    return response


@router.post("/{project_id}/delivery-plan/initialize", response_model=ProjectDeliveryPlanResponse)
async def initialize_project_delivery_plan(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Initialize a delivery plan for an existing project."""
    await check_project_membership(
        project_id, current_user.id, db, current_user.tenant_id, require_owner=True
    )
    launch_plan = await ProjectLaunchService(db).get_plan(project_id, current_user.tenant_id)
    blueprint_key = launch_plan.blueprint_key if launch_plan else "consulting-discovery"
    config = dict(launch_plan.config_json or {}) if launch_plan else {}
    await ProjectDeliveryPlanService(db).initialize(
        project_id=project_id,
        tenant_id=current_user.tenant_id,
        requested_by=current_user.id,
        blueprint_key=blueprint_key,
        document_types=list(config.get("document_types") or []),
        workflow_template_ids=list(config.get("workflow_template_ids") or []),
    )
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.delivery_plan.initialize",
        resource_type="project",
        resource_id=project_id,
        metadata={"blueprint_key": blueprint_key},
    )
    return await ProjectDeliveryPlanService(db).build_response(project_id, current_user.tenant_id)


@router.get("/{project_id}/acceptance", response_model=ProjectAcceptanceResponse)
async def get_project_acceptance(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get customer acceptance and formal delivery closure evidence."""
    await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    try:
        return await ProjectDeliveryPlanService(db).get_acceptance(
            project_id, current_user.tenant_id
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get(
    "/{project_id}/customer-portal-links",
    response_model=list[CustomerPortalLinkResponse],
)
async def list_customer_portal_links(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List safe customer portal link metadata for project owners."""
    await check_project_membership(
        project_id, current_user.id, db, current_user.tenant_id, require_owner=True
    )
    try:
        return await ProjectDeliveryPlanService(db).list_customer_portal_links(
            project_id, current_user.tenant_id
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/{project_id}/customer-portal-links",
    response_model=CustomerPortalLinkCreatedResponse,
    status_code=201,
)
async def create_customer_portal_link(
    project_id: UUID,
    data: CustomerPortalLinkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an expiring customer portal link and reveal its token once."""
    await check_project_membership(
        project_id, current_user.id, db, current_user.tenant_id, require_owner=True
    )
    try:
        response = await ProjectDeliveryPlanService(db).create_customer_portal_link(
            project_id, current_user.tenant_id, current_user.id, data
        )
    except (ValueError, PermissionError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.customer_portal_link.create",
        resource_type="project",
        resource_id=project_id,
        metadata={"link_id": str(response.id), "expires_at": str(response.expires_at)},
    )
    return response


@router.post(
    "/{project_id}/customer-portal-links/{link_id}/revoke",
    response_model=CustomerPortalLinkResponse,
)
async def revoke_customer_portal_link(
    project_id: UUID,
    link_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke a customer portal link immediately."""
    await check_project_membership(
        project_id, current_user.id, db, current_user.tenant_id, require_owner=True
    )
    try:
        response = await ProjectDeliveryPlanService(db).revoke_customer_portal_link(
            project_id, current_user.tenant_id, current_user.id, link_id
        )
    except (ValueError, PermissionError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.customer_portal_link.revoke",
        resource_type="project",
        resource_id=project_id,
        metadata={"link_id": str(link_id)},
    )
    return response


@router.put("/{project_id}/acceptance", response_model=ProjectAcceptanceResponse)
async def update_project_acceptance(
    project_id: UUID,
    data: ProjectAcceptanceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record the owner-verified customer acceptance decision and evidence."""
    await check_project_membership(
        project_id, current_user.id, db, current_user.tenant_id, require_owner=True
    )
    try:
        response = await ProjectDeliveryPlanService(db).update_acceptance(
            project_id, current_user.tenant_id, current_user.id, data
        )
    except (ValueError, PermissionError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.acceptance.update",
        resource_type="project",
        resource_id=project_id,
        metadata={"decision": response.decision, "item_count": len(response.items)},
    )
    return response


@router.post("/{project_id}/acceptance/close", response_model=ProjectAcceptanceResponse)
async def close_project_delivery(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Close formal delivery only after all customer and package gates pass."""
    await check_project_membership(
        project_id, current_user.id, db, current_user.tenant_id, require_owner=True
    )
    try:
        response = await ProjectDeliveryPlanService(db).close_delivery(
            project_id, current_user.tenant_id, current_user.id
        )
    except (ValueError, PermissionError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.acceptance.close",
        resource_type="project",
        resource_id=project_id,
        metadata={"decision": response.decision, "closed_at": str(response.closed_at)},
    )
    return response


@router.post("/{project_id}/acceptance/reopen", response_model=ProjectAcceptanceResponse)
async def reopen_project_delivery(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reopen formal delivery when customer follow-up requires more work."""
    await check_project_membership(
        project_id, current_user.id, db, current_user.tenant_id, require_owner=True
    )
    try:
        response = await ProjectDeliveryPlanService(db).reopen_delivery(
            project_id, current_user.tenant_id, current_user.id
        )
    except (ValueError, PermissionError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.acceptance.reopen",
        resource_type="project",
        resource_id=project_id,
        metadata={"decision": response.decision},
    )
    return response


@router.post("/{project_id}/milestones", response_model=ProjectMilestoneResponse, status_code=201)
async def create_project_milestone(
    project_id: UUID,
    data: ProjectMilestoneCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a project milestone."""
    await check_project_membership(
        project_id, current_user.id, db, current_user.tenant_id, require_owner=True
    )
    try:
        milestone = await ProjectDeliveryPlanService(db).create_milestone(
            project_id=project_id,
            tenant_id=current_user.tenant_id,
            requested_by=current_user.id,
            data=data,
        )
    except (ValueError, PermissionError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.milestone.create",
        resource_type="project_milestone",
        resource_id=milestone.id,
        metadata={"project_id": str(project_id), "key": milestone.key},
    )
    return ProjectMilestoneResponse.model_validate(milestone)


@router.patch("/{project_id}/milestones/{milestone_id}", response_model=ProjectMilestoneResponse)
async def update_project_milestone(
    project_id: UUID,
    milestone_id: UUID,
    data: ProjectMilestoneUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a project milestone."""
    await check_project_membership(
        project_id, current_user.id, db, current_user.tenant_id, require_owner=True
    )
    try:
        milestone = await ProjectDeliveryPlanService(db).update(
            milestone_id, current_user.tenant_id, current_user.id, data, project_id=project_id
        )
    except (ValueError, PermissionError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if milestone.project_id != project_id:
        raise HTTPException(status_code=404, detail="Project milestone not found")
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.milestone.update",
        resource_type="project_milestone",
        resource_id=milestone.id,
        metadata={"project_id": str(project_id)},
    )
    return ProjectMilestoneResponse.model_validate(milestone)


@router.delete("/{project_id}/milestones/{milestone_id}", status_code=204)
async def delete_project_milestone(
    project_id: UUID,
    milestone_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a project milestone and its synchronized responsibility item."""
    await check_project_membership(
        project_id, current_user.id, db, current_user.tenant_id, require_owner=True
    )
    try:
        await ProjectDeliveryPlanService(db).delete(
            milestone_id,
            current_user.tenant_id,
            current_user.id,
            project_id=project_id,
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.milestone.delete",
        resource_type="project_milestone",
        resource_id=milestone_id,
        metadata={"project_id": str(project_id)},
    )


@router.post("/{project_id}/milestones/reorder", response_model=ProjectDeliveryPlanResponse)
async def reorder_project_milestones(
    project_id: UUID,
    data: ProjectMilestoneReorder,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reorder all milestones in a project delivery plan."""
    await check_project_membership(
        project_id, current_user.id, db, current_user.tenant_id, require_owner=True
    )
    try:
        await ProjectDeliveryPlanService(db).reorder(
            project_id, current_user.tenant_id, data.milestone_ids
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.milestone.reorder",
        resource_type="project",
        resource_id=project_id,
        metadata={"milestone_count": len(data.milestone_ids)},
    )
    return await ProjectDeliveryPlanService(db).build_response(project_id, current_user.tenant_id)


async def _transition_project_milestone(
    *,
    project_id: UUID,
    milestone_id: UUID,
    action: str,
    db: AsyncSession,
    current_user: User,
) -> ProjectMilestoneResponse:
    await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    service = ProjectDeliveryPlanService(db)
    try:
        milestone = await getattr(service, action)(
            milestone_id, current_user.tenant_id, current_user.id, project_id=project_id
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if milestone.project_id != project_id:
        raise HTTPException(status_code=404, detail="Project milestone not found")
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action=f"project.milestone.{action}",
        resource_type="project_milestone",
        resource_id=milestone.id,
        metadata={"project_id": str(project_id), "status": milestone.status},
    )
    return ProjectMilestoneResponse.model_validate(milestone)


@router.post("/{project_id}/milestones/{milestone_id}/start", response_model=ProjectMilestoneResponse)
async def start_project_milestone(
    project_id: UUID,
    milestone_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _transition_project_milestone(
        project_id=project_id, milestone_id=milestone_id, action="start", db=db, current_user=current_user
    )


@router.post("/{project_id}/milestones/{milestone_id}/complete", response_model=ProjectMilestoneResponse)
async def complete_project_milestone(
    project_id: UUID,
    milestone_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _transition_project_milestone(
        project_id=project_id, milestone_id=milestone_id, action="complete", db=db, current_user=current_user
    )


@router.post("/{project_id}/milestones/{milestone_id}/reopen", response_model=ProjectMilestoneResponse)
async def reopen_project_milestone(
    project_id: UUID,
    milestone_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _transition_project_milestone(
        project_id=project_id, milestone_id=milestone_id, action="reopen", db=db, current_user=current_user
    )


@router.get("/{project_id}/delivery-workbench", response_model=ProjectDeliveryWorkbenchResponse)
async def get_project_delivery_workbench(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get delivery readiness, review, traceability, and next-action summary for a project."""
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")

    service = ProjectService(db)
    workbench = await service.get_delivery_workbench(project_id, current_user.tenant_id)
    if not workbench:
        raise HTTPException(status_code=404, detail="Project not found")
    return workbench


@router.get("/{project_id}/document-workbench", response_model=ProjectDeliveryWorkbenchResponse)
async def get_project_document_workbench(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the full project document delivery workbench."""
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")

    service = ProjectService(db)
    workbench = await service.get_document_workbench(project_id, current_user.tenant_id)
    if not workbench:
        raise HTTPException(status_code=404, detail="Project not found")
    return workbench


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a project by ID.

    Args:
        project_id: Project UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Project details

    Raises:
        HTTPException: If project not found or access denied
    """
    service = ProjectService(db)
    project = await service.get_project(project_id, current_user.tenant_id)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check membership
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")

    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a project.

    Args:
        project_id: Project UUID
        data: Project update data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated project

    Raises:
        HTTPException: If project not found or slug already exists
    """
    service = ProjectService(db)

    # Check membership first
    try:
        await check_project_membership(
            project_id,
            current_user.id,
            db,
            current_user.tenant_id,
            require_owner=data.status is not None,
        )
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        project = await service.update_project(
            project_id=project_id,
            data=data,
            tenant_id=current_user.tenant_id,
        )
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return ProjectResponse.model_validate(project)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _transition_project_status(
    *,
    project_id: UUID,
    status: str,
    action: str,
    db: AsyncSession,
    current_user: User,
) -> ProjectResponse:
    await check_project_membership(
        project_id,
        current_user.id,
        db,
        current_user.tenant_id,
        require_owner=True,
    )
    project = await ProjectService(db).set_project_status(
        project_id=project_id,
        status=status,
        tenant_id=current_user.tenant_id,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action=action,
        resource_type="project",
        resource_id=project_id,
        metadata={"status": status},
    )
    return ProjectResponse.model_validate(project)


@router.post("/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Archive a project while preserving its delivery evidence."""
    return await _transition_project_status(
        project_id=project_id,
        status="archived",
        action="project.archive",
        db=db,
        current_user=current_user,
    )


@router.post("/{project_id}/restore", response_model=ProjectResponse)
async def restore_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Restore an archived project to the active delivery workspace."""
    return await _transition_project_status(
        project_id=project_id,
        status="active",
        action="project.restore",
        db=db,
        current_user=current_user,
    )


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a project (soft delete).

    Args:
        project_id: Project UUID
        db: Database session
        current_user: Current authenticated user

    Raises:
        HTTPException: If project not found or access denied
    """
    service = ProjectService(db)

    # Only owner can delete
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id, require_owner=True)
    except HTTPException as e:
        raise e

    deleted = await service.delete_project(project_id, current_user.tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")


# Project Member Endpoints
@router.get("/{project_id}/members", response_model=ProjectMemberListResponse)
async def list_project_members(
    project_id: UUID,
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all members of a project.

    Args:
        project_id: Project UUID
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of project members

    Raises:
        HTTPException: If access denied
    """
    service = ProjectService(db)

    # Check membership
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")

    members, total = await service.list_members(
        project_id=project_id,
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
    )
    has_more = (pagination.page * pagination.page_size) < total

    return ProjectMemberListResponse(
        items=[ProjectMemberResponse.model_validate(m) for m in members],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=has_more,
    )


@router.post("/{project_id}/members", response_model=ProjectMemberResponse, status_code=201)
async def add_project_member(
    project_id: UUID,
    data: ProjectMemberCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a member to a project.

    Args:
        project_id: Project UUID
        data: Member creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created project member

    Raises:
        HTTPException: If project not found or user already a member
    """
    service = ProjectService(db)

    # Check membership (must be owner)
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id, require_owner=True)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Only owner can add members")

    try:
        member = await service.add_member(
            project_id=project_id,
            data=data,
            tenant_id=current_user.tenant_id,
        )
        return ProjectMemberResponse.model_validate(member)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{project_id}/members/{user_id}", status_code=204)
async def remove_project_member(
    project_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a member from a project.

    Args:
        project_id: Project UUID
        user_id: User UUID to remove
        db: Database session
        current_user: Current authenticated user

    Raises:
        HTTPException: If project/member not found or access denied
    """
    service = ProjectService(db)

    # Check membership (must be owner or removing self)
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id, require_owner=True)
    except HTTPException:
        # Allow removing self
        if user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")

    removed = await service.remove_member(
        project_id=project_id,
        user_id=user_id,
        tenant_id=current_user.tenant_id,
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Member not found")


# Project Settings Endpoints
@router.get(
    "/{project_id}/document-lifecycle-policy",
    response_model=DocumentLifecyclePolicyResponse,
)
async def get_project_document_lifecycle_policy(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the effective project document lifecycle policy."""
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")

    return await ProjectDocumentLifecyclePolicyService(db).get_policy(project_id)


@router.put(
    "/{project_id}/document-lifecycle-policy",
    response_model=DocumentLifecyclePolicyResponse,
)
async def update_project_document_lifecycle_policy(
    project_id: UUID,
    data: DocumentLifecyclePolicyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the project lifecycle policy without weakening platform permissions."""
    try:
        await check_project_membership(
            project_id,
            current_user.id,
            db,
            current_user.tenant_id,
            require_owner=True,
        )
    except HTTPException:
        raise HTTPException(status_code=403, detail="Only owner can update lifecycle policy")

    try:
        policy = await ProjectDocumentLifecyclePolicyService(db).update_policy(project_id, data)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.document_lifecycle_policy.update",
        resource_type="project",
        resource_id=project_id,
        metadata={
            "revision": policy.revision,
            "enabled_statuses": [status.key for status in policy.statuses],
            "transition_count": len(policy.transitions),
        },
    )
    return policy


@router.get("/{project_id}/settings", response_model=ProjectSettingsResponse)
async def get_project_settings(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get project settings.

    Args:
        project_id: Project UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Project settings

    Raises:
        HTTPException: If access denied
    """
    # Check membership
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")

    service = ProjectSettingsService(db)
    settings = await service.get_settings(project_id)

    if not settings:
        # Return empty settings
        from app.domains.projects.models import ProjectSettings

        settings = ProjectSettings(
            project_id=project_id,
            settings_json={},
        )

    return ProjectSettingsResponse.model_validate(settings)


@router.patch("/{project_id}/settings", response_model=ProjectSettingsResponse)
async def update_project_settings(
    project_id: UUID,
    data: ProjectSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update project settings.

    Args:
        project_id: Project UUID
        data: Settings update data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated project settings

    Raises:
        HTTPException: If access denied
    """
    # Check membership (must be owner)
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id, require_owner=True)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Only owner can update settings")

    service = ProjectSettingsService(db)
    settings = await service.upsert_settings(
        project_id=project_id,
        settings=data.settings,
    )
    return ProjectSettingsResponse.model_validate(settings)


# Source File Endpoints
@router.get("/{project_id}/files", response_model=SourceFileListResponse)
async def list_source_files(
    project_id: UUID,
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List source files for a project.

    Args:
        project_id: Project UUID
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of source files

    Raises:
        HTTPException: If access denied
    """
    service = SourceFileService(db)

    # Check membership
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")

    files, total = await service.list_source_files(
        project_id=project_id,
        tenant_id=current_user.tenant_id,
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
    )
    has_more = (pagination.page * pagination.page_size) < total

    return SourceFileListResponse(
        items=[SourceFileResponse.model_validate(f) for f in files],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=has_more,
    )


@router.post("/{project_id}/files", response_model=SourceFileResponse, status_code=201)
async def upload_project_file(
    project_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageProvider = Depends(get_storage),
):
    """Direct multipart project file upload."""
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")

    content = await file.read()
    size = len(content)
    filename = file.filename or "upload.bin"
    content_type = file.content_type or "application/octet-stream"

    if content_type not in SUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content type. Supported: {list(SUPPORTED_CONTENT_TYPES.keys())}",
        )

    # Validate file size
    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE} bytes",
        )

    try:
        handle = await storage.upload(
            tenant_id=str(current_user.tenant_id),
            project_id=str(project_id),
            filename=filename,
            content=content,
            content_type=content_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    service = SourceFileService(db)

    source_file = await service.create_source_file(
        project_id=project_id,
        tenant_id=current_user.tenant_id,
        data=SourceFileCreate(
            filename=handle.filename,
            original_filename=filename,
            content_type=content_type,
            size=size,
            hash=handle.hash,
            storage_path=handle.path,
            metadata={},
        ),
    )

    await SourceIngestionService(db).enqueue(source_file, current_user.id)

    return SourceFileResponse.model_validate(source_file)


@router.post("/{project_id}/files/upload", response_model=UploadUrlResponse)
async def initiate_file_upload(
    project_id: UUID,
    filename: str = Query(..., description="Original filename"),
    content_type: str = Query(..., description="MIME type"),
    size: int = Query(..., ge=0, description="File size in bytes"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageProvider = Depends(get_storage),
):
    """Initiate a file upload and get storage handle.

    This endpoint returns a storage handle that can be used to upload the file.
    For local storage, the file should be uploaded directly to the storage path.
    For S3, a pre-signed URL would be returned.

    Args:
        project_id: Project UUID
        filename: Original filename
        content_type: MIME type of the file
        size: File size in bytes
        db: Database session
        current_user: Current authenticated user
        storage: Storage provider

    Returns:
        Upload URL and storage path

    Raises:
        HTTPException: If access denied or content type/size invalid
    """
    from app.domains.projects.schemas import SourceFileCreate

    # Check membership
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")

    # Validate content type
    if content_type not in SUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content type. Supported: {list(SUPPORTED_CONTENT_TYPES.keys())}",
        )

    # Validate file size
    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE} bytes",
        )

    # Generate a unique filename for storage
    unique_filename = f"{uuid4()}_{filename}"

    # Create storage path components
    tenant_id = str(current_user.tenant_id)
    project_id_str = str(project_id)

    # For local storage, we need to create the upload location
    # The actual file upload will be handled by the confirm endpoint
    storage_path = f"{tenant_id}/{project_id_str}/{unique_filename}"

    # Create SourceFile record with pending status
    service = SourceFileService(db)
    source_file = await service.create_source_file(
        project_id=project_id,
        tenant_id=current_user.tenant_id,
        data=SourceFileCreate(
            filename=unique_filename,
            original_filename=filename,
            content_type=content_type,
            size=size,
            hash="",  # Will be verified on confirm
            storage_path=storage_path,
            metadata={},
        ),
    )

    # Calculate expiration (1 hour from now)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    return UploadUrlResponse(
        file_id=source_file.id,
        upload_url=f"file://{storage_path}",  # Local storage path
        storage_path=storage_path,
        expires_at=expires_at,
    )


@router.post("/{project_id}/files/{file_id}/confirm", response_model=SourceFileResponse)
async def confirm_file_upload(
    project_id: UUID,
    file_id: UUID,
    hash: str = Query(..., min_length=64, max_length=64, description="SHA256 hash of uploaded file"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageProvider = Depends(get_storage),
):
    """Confirm that a file upload has completed and create the source file record.

    Args:
        project_id: Project UUID
        file_id: Source file UUID
        hash: SHA256 hash of the uploaded file for verification
        db: Database session
        current_user: Current authenticated user
        storage: Storage provider

    Returns:
        Created source file record

    Raises:
        HTTPException: If access denied or file not found/invalid
    """
    from app.domains.projects.schemas import SourceFileCreate

    # Check membership
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get the source file record (should be created during upload initiation)
    service = SourceFileService(db)
    source_file = await service.get_source_file(file_id, current_user.tenant_id)

    if not source_file:
        raise HTTPException(status_code=404, detail="Source file record not found")

    # Verify project_id matches
    if source_file.project_id != project_id:
        raise HTTPException(status_code=400, detail="File does not belong to this project")

    # Store the provided hash and enqueue knowledge ingestion.
    source_file.hash = hash
    await db.flush()
    await SourceIngestionService(db).enqueue(source_file, current_user.id)

    return SourceFileResponse.model_validate(source_file)


@router.delete("/{project_id}/files/{file_id}", status_code=204)
async def delete_source_file(
    project_id: UUID,
    file_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageProvider = Depends(get_storage),
):
    """Delete a source file.

    Args:
        project_id: Project UUID
        file_id: Source file UUID
        db: Database session
        current_user: Current authenticated user
        storage: Storage provider

    Raises:
        HTTPException: If access denied or file not found
    """
    # Check membership (must be owner)
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id, require_owner=True)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Only owner can delete files")

    service = SourceFileService(db)
    source_file = await service.get_source_file(file_id, current_user.tenant_id)

    if not source_file:
        raise HTTPException(status_code=404, detail="Source file not found")

    # Delete from storage
    from app.services.storage import StorageHandle

    handle = StorageHandle(
        path=source_file.storage_path,
        filename=source_file.filename,
        content_type=source_file.content_type,
        size=int(source_file.size),
        hash=source_file.hash,
        storage_backend="local",
    )

    try:
        await storage.delete(handle)
    except FileNotFoundError:
        pass  # File may already be deleted

    await SourceIngestionService(db).retire_source_knowledge(file_id, current_user.tenant_id)

    # Soft delete the record
    deleted = await service.delete_source_file(file_id, current_user.tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source file not found")


@router.get("/{project_id}/ingestion-jobs", response_model=SourceIngestionJobListResponse)
async def list_source_ingestion_jobs(
    project_id: UUID,
    source_file_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List durable ingestion jobs visible to a project member."""
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")

    jobs = await SourceIngestionService(db).list_jobs(
        project_id,
        current_user.tenant_id,
        source_file_id=source_file_id,
    )
    return SourceIngestionJobListResponse(
        items=[SourceIngestionJobResponse.model_validate(job) for job in jobs],
        total=len(jobs),
    )


@router.post(
    "/{project_id}/ingestion-jobs/{job_id}/execute",
    response_model=SourceIngestionJobResponse,
)
async def execute_source_ingestion_job(
    project_id: UUID,
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageProvider = Depends(get_storage),
):
    """Execute one queued ingestion job."""
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
        service = SourceIngestionService(db)
        existing = await service.get_job(job_id, current_user.tenant_id)
        if not existing or existing.project_id != project_id:
            raise SourceIngestionError("ingestion job not found")
        job = await service.execute(
            job_id,
            tenant_id=current_user.tenant_id,
            storage=storage,
        )
        return SourceIngestionJobResponse.model_validate(job)
    except SourceIngestionError as error:
        status_code = 404 if "not found" in str(error) else 409
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.post(
    "/{project_id}/ingestion-jobs/{job_id}/retry",
    response_model=SourceIngestionJobResponse,
)
async def retry_source_ingestion_job(
    project_id: UUID,
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Queue a failed ingestion job for another attempt."""
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
        service = SourceIngestionService(db)
        existing = await service.get_job(job_id, current_user.tenant_id)
        if not existing or existing.project_id != project_id:
            raise SourceIngestionError("ingestion job not found")
        job = await service.retry(job_id, current_user.id)
        return SourceIngestionJobResponse.model_validate(job)
    except SourceIngestionError as error:
        status_code = 404 if "not found" in str(error) else 409
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.post(
    "/{project_id}/files/{file_id}/reingest",
    response_model=SourceIngestionJobResponse,
)
async def reingest_source_file(
    project_id: UUID,
    file_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retire source-derived knowledge and queue a clean ingestion run."""
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
        job = await SourceIngestionService(db).reingest(
            file_id,
            current_user.tenant_id,
            project_id,
            current_user.id,
        )
        return SourceIngestionJobResponse.model_validate(job)
    except SourceIngestionError as error:
        status_code = 404 if "not found" in str(error) else 409
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.get("/{project_id}/files/{file_id}/download", response_class=StreamingResponse)
async def download_source_file(
    project_id: UUID,
    file_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageProvider = Depends(get_storage),
):
    """Download a source file.

    Args:
        project_id: Project UUID
        file_id: Source file UUID
        db: Database session
        current_user: Current authenticated user
        storage: Storage provider

    Returns:
        File content

    Raises:
        HTTPException: If access denied or file not found
    """
    # Check membership
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Access denied")

    service = SourceFileService(db)
    source_file = await service.get_source_file(file_id, current_user.tenant_id)

    if not source_file:
        raise HTTPException(status_code=404, detail="Source file not found")

    # Create storage handle
    from app.services.storage import StorageHandle

    handle = StorageHandle(
        path=source_file.storage_path,
        filename=source_file.filename,
        content_type=source_file.content_type,
        size=int(source_file.size),
        hash=source_file.hash,
        storage_backend="local",
    )

    try:
        content = await storage.download(handle)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File content not found")

    download_name = source_file.original_filename or source_file.filename
    extension = f".{source_file.filename.rsplit('.', 1)[1]}" if "." in source_file.filename else ""
    ascii_name = download_name.encode("ascii", "ignore").decode().strip()
    ascii_name = ascii_name.replace("\\", "_").replace('"', "")
    if not ascii_name or ascii_name.startswith("."):
        ascii_name = f"download{extension}"
    filename_encoded = quote(download_name)
    return StreamingResponse(
        BytesIO(content),
        media_type=source_file.content_type,
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{filename_encoded}"
        },
    )


# Project Invitation Endpoints
@router.get("/{project_id}/invitations", response_model=ProjectInvitationListResponse)
async def list_project_invitations(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List invitation lifecycle state for a project owner."""
    await check_project_membership(project_id, current_user.id, db, current_user.tenant_id, require_owner=True)
    filters = (
        ProjectInvitation.project_id == project_id,
        ProjectInvitation.tenant_id == current_user.tenant_id,
        ProjectInvitation.deleted_at.is_(None),
    )
    result = await db.execute(select(ProjectInvitation).where(*filters).order_by(ProjectInvitation.created_at.desc()))
    items = list(result.scalars().all())
    return ProjectInvitationListResponse(
        items=[_invitation_response(item) for item in items],
        total=len(items),
        page=1,
        page_size=max(len(items), 1),
        has_more=False,
    )


@router.post("/{project_id}/invitations", response_model=ProjectInvitationCreatedResponse, status_code=201)
async def create_project_invitation(
    project_id: UUID,
    email: EmailStr,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an invitation to join a project.

    Args:
        project_id: Project UUID
        email: Email address to invite
        db: Database session
        current_user: Current authenticated user

    Returns:
        Invitation token

    Raises:
        HTTPException: If access denied or project not found
    """
    try:
        await check_project_membership(project_id, current_user.id, db, current_user.tenant_id, require_owner=True)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Only owner can invite members")

    normalized_email = str(email).strip().casefold()
    invited_user = (
        await db.execute(
            select(User).where(
                func.lower(User.email) == normalized_email,
                User.tenant_id == current_user.tenant_id,
                User.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if invited_user:
        membership = (
            await db.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == invited_user.id,
                )
            )
        ).scalar_one_or_none()
        if membership:
            raise HTTPException(status_code=409, detail="User is already a member of this project")

    existing = (
        await db.execute(
            select(ProjectInvitation).where(
                ProjectInvitation.project_id == project_id,
                func.lower(ProjectInvitation.email) == normalized_email,
                ProjectInvitation.accepted_at.is_(None),
                ProjectInvitation.revoked_at.is_(None),
                ProjectInvitation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing and not _invitation_expired(existing.expires_at):
        raise HTTPException(status_code=409, detail="An active invitation already exists for this email")

    token = secrets.token_urlsafe(32)
    invitation = ProjectInvitation(
        project_id=project_id,
        tenant_id=current_user.tenant_id,
        email=normalized_email,
        token=_invitation_token_digest(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(invitation)
    await db.flush()
    await db.refresh(invitation)
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.invitation.create",
        resource_type="project_invitation",
        resource_id=invitation.id,
        metadata={"project_id": str(project_id), "email": normalized_email},
    )
    return ProjectInvitationCreatedResponse(
        id=invitation.id,
        token=token,
        invite_path=f"/invitations/{token}",
        expires_at=invitation.expires_at,
    )


async def _owner_invitation(
    project_id: UUID,
    invitation_id: UUID,
    db: AsyncSession,
    current_user: User,
) -> ProjectInvitation:
    await check_project_membership(project_id, current_user.id, db, current_user.tenant_id, require_owner=True)
    invitation = (
        await db.execute(
            select(ProjectInvitation).where(
                ProjectInvitation.id == invitation_id,
                ProjectInvitation.project_id == project_id,
                ProjectInvitation.tenant_id == current_user.tenant_id,
                ProjectInvitation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    return invitation


@router.post(
    "/{project_id}/invitations/{invitation_id}/resend",
    response_model=ProjectInvitationCreatedResponse,
)
async def resend_project_invitation(
    project_id: UUID,
    invitation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rotate the invitation token and renew its expiry."""
    invitation = await _owner_invitation(project_id, invitation_id, db, current_user)
    if invitation.accepted_at is not None:
        raise HTTPException(status_code=409, detail="Accepted invitation cannot be resent")
    if invitation.revoked_at is not None:
        raise HTTPException(status_code=409, detail="Revoked invitation cannot be resent")
    token = secrets.token_urlsafe(32)
    invitation.token = _invitation_token_digest(token)
    invitation.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await db.flush()
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.invitation.resend",
        resource_type="project_invitation",
        resource_id=invitation.id,
        metadata={"project_id": str(project_id), "email": invitation.email},
    )
    return ProjectInvitationCreatedResponse(
        id=invitation.id,
        token=token,
        invite_path=f"/invitations/{token}",
        expires_at=invitation.expires_at,
    )


@router.post("/{project_id}/invitations/{invitation_id}/revoke", response_model=ProjectInvitationResponse)
async def revoke_project_invitation(
    project_id: UUID,
    invitation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke an unaccepted project invitation."""
    invitation = await _owner_invitation(project_id, invitation_id, db, current_user)
    if invitation.accepted_at is not None:
        raise HTTPException(status_code=409, detail="Accepted invitation cannot be revoked")
    invitation.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="project.invitation.revoke",
        resource_type="project_invitation",
        resource_id=invitation.id,
        metadata={"project_id": str(project_id), "email": invitation.email},
    )
    return _invitation_response(invitation)
