"""Documents Domain API Router

Endpoints for document management, versioning, baselines, and quality assessment.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.security import decode_token
from app.models.identity import User
from app.domains.documents.models import (
    Document,
    GenerationSessionStatus,
    DocumentStatus,
    DocumentType,
    QualityType,
)
from app.domains.documents.schemas import (
    DocumentCreate,
    DocumentUpdate,
    DocumentResponse,
    DocumentListResponse,
    DocumentStatusUpdate,
    DocumentStatusTransitionResponse,
    DocumentStatusCapability,
    DocumentStatusCapabilitiesResponse,
    DocumentVersionCreate,
    DocumentVersionResponse,
    DocumentVersionListResponse,
    DocumentBaselineCreate,
    DocumentBaselineResponse,
    DocumentBaselineListResponse,
    QualityResultResponse,
    QualityCheckRequest,
    DocumentGenerateRequest,
    DocumentGenerateResponse,
    DocumentGenerationMessageRequest,
    DocumentGenerationSectionResponse,
    DocumentGenerationSessionCreate,
    DocumentGenerationSessionResponse,
    DocumentGenerationTurnResponse,
    DocumentStatistics,
    PaginationParams,
)
from app.domains.documents.service import (
    ALLOWED_STATUS_TRANSITIONS,
    DocumentService,
    DocumentGenerationService,
)
from app.domains.change.schemas import (
    DocumentImpactAnalysisCreate,
    DocumentImpactAnalysisResponse,
    DocumentReferenceCreate,
    DocumentReferenceListResponse,
    DocumentReferenceResponse,
)
from app.domains.change.service import TraceabilityService
from app.integrations.llm.gateway import LLMGateway
from app.services.permission_evaluator import PermissionEvaluator
from app.domains.notifications.service import UserNotificationService


router = APIRouter()

STATUS_PERMISSION_ACTIONS = {
    DocumentStatus.DRAFT.value: "write",
    DocumentStatus.WRITING.value: "write",
    DocumentStatus.PENDING_REVIEW.value: "review",
    DocumentStatus.REVIEW.value: "review",
    DocumentStatus.IN_REVIEW.value: "review",
    DocumentStatus.REVISION_REQUIRED.value: "review",
    DocumentStatus.APPROVED.value: "approve",
    DocumentStatus.PUBLISHED.value: "publish",
    DocumentStatus.ARCHIVED.value: "archive",
}
OWNER_MANAGED_STATUS_ACTIONS = {
    DocumentStatus.DRAFT.value,
    DocumentStatus.WRITING.value,
    DocumentStatus.PENDING_REVIEW.value,
    DocumentStatus.REVIEW.value,
    DocumentStatus.IN_REVIEW.value,
    DocumentStatus.REVISION_REQUIRED.value,
}


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


async def ensure_project_access(
    db: AsyncSession,
    project_id: UUID,
    current_user: User,
) -> None:
    """Raise if the current user cannot access the project."""
    from sqlalchemy import select
    from app.models.projects import Project, ProjectMember

    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.tenant_id == current_user.tenant_id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if project:
        return

    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == current_user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Access denied to project")


def get_llm_gateway() -> LLMGateway | None:
    """Get LLM gateway with fallback routing if configured.

    Returns:
        LLMGateway instance or None
    """
    try:
        from app.core.settings import settings
        from app.integrations.llm.gateway import GatewayFactory

        if settings.OPENAI_API_KEY:
            return GatewayFactory.create_with_openai_fallback(
                primary_api_key=settings.OPENAI_API_KEY,
                primary_base_url=settings.OPENAI_BASE_URL,
                primary_model=settings.OPENAI_MODEL,
                fallback_api_key=settings.LLM_FALLBACK_API_KEY or None,
                fallback_base_url=settings.LLM_FALLBACK_BASE_URL or None,
                fallback_model=settings.LLM_FALLBACK_MODEL or None,
            )
    except Exception:
        pass
    return None


async def check_document_access(
    document_id: UUID,
    user_id: UUID,
    db: AsyncSession,
    tenant_id: UUID,
    require_owner: bool = False,
) -> Document:
    """Check if user has access to document and return it.

    Args:
        document_id: Document UUID
        user_id: User UUID
        db: Database session
        tenant_id: Tenant UUID
        require_owner: If True, user must be document creator

    Returns:
        Document if access allowed

    Raises:
        HTTPException: If access denied or document not found
    """
    from sqlalchemy import select
    from app.models.projects import Project, ProjectMember

    service = DocumentService(db)
    document = await service.get_document(document_id, tenant_id)

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check if user is the document creator
    if document.created_by == user_id:
        return document

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
        return document

    if require_owner:
        raise HTTPException(
            status_code=403,
            detail="Only document creator or project owner can perform this action",
        )

    # Check if user is a project member
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == document.project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if result.scalar_one_or_none():
        return document

    raise HTTPException(status_code=403, detail="Access denied")


async def is_document_owner(
    document: Document,
    user_id: UUID,
    db: AsyncSession,
    tenant_id: UUID,
) -> bool:
    """Return whether the user created the document or owns its project."""
    if document.created_by == user_id:
        return True

    from sqlalchemy import select
    from app.models.projects import Project

    result = await db.execute(
        select(Project.id).where(
            Project.id == document.project_id,
            Project.owner_id == user_id,
            Project.tenant_id == tenant_id,
            Project.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none() is not None


async def get_document_status_permission_decision(
    document: Document,
    current_user: User,
    db: AsyncSession,
    next_status: str,
) -> dict[str, Any]:
    """Return the auditable permission decision for a status transition."""
    action = STATUS_PERMISSION_ACTIONS.get(next_status, "write")
    evaluator = PermissionEvaluator(db)
    decision = await evaluator.explain_permission(
        current_user,
        action,
        "documents",
        current_user.tenant_id,
    )

    if decision["allowed"] or decision["reason"] == "deny_policy":
        return {
            **decision,
            "permission_action": f"documents.{action}",
        }

    from sqlalchemy import select
    from app.models.identity import Role
    from app.models.projects import ProjectMember

    project_role_result = await db.execute(
        select(Role)
        .join(ProjectMember, ProjectMember.role_id == Role.id)
        .where(
            ProjectMember.project_id == document.project_id,
            ProjectMember.user_id == current_user.id,
            Role.tenant_id == current_user.tenant_id,
        )
    )
    project_role = project_role_result.scalar_one_or_none()
    if project_role and evaluator.permissions_allow(project_role.permissions, action, "documents"):
        return {
            "allowed": True,
            "reason": "project_role",
            "permission_action": f"documents.{action}",
        }

    if next_status in OWNER_MANAGED_STATUS_ACTIONS and await is_document_owner(
        document,
        current_user.id,
        db,
        current_user.tenant_id,
    ):
        return {
            "allowed": True,
            "reason": "document_or_project_owner",
            "permission_action": f"documents.{action}",
        }

    return {
        **decision,
        "permission_action": f"documents.{action}",
    }


async def require_document_status_permission(
    document: Document,
    current_user: User,
    db: AsyncSession,
    next_status: str,
) -> None:
    """Raise when the current user cannot perform the target status action."""
    decision = await get_document_status_permission_decision(
        document,
        current_user,
        db,
        next_status,
    )
    if not decision["allowed"]:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Missing {decision['permission_action']} permission "
                f"({decision['reason']})"
            ),
        )


# Document Endpoints
@router.get("", response_model=DocumentListResponse)
async def list_documents(
    project_id: UUID | None = Query(None, description="Filter by project ID"),
    doc_type: str | None = Query(None, description="Filter by document type"),
    status: str | None = Query(None, description="Filter by status"),
    include_placeholders: bool = Query(False, description="Include placeholder documents"),
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all documents for the current user.

    Args:
        project_id: Optional project filter
        doc_type: Optional document type filter
        status: Optional status filter
        include_placeholders: If False (default), placeholder documents are excluded
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of documents
    """
    service = DocumentService(db)
    documents, total = await service.list_documents(
        tenant_id=current_user.tenant_id,
        project_id=project_id,
        doc_type=doc_type,
        status=status,
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
        include_placeholders=include_placeholders,
    )
    has_more = (pagination.page * pagination.page_size) < total

    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in documents],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=has_more,
    )


@router.post("", response_model=DocumentResponse, status_code=201)
async def create_document(
    data: DocumentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new document.

    Args:
        data: Document creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created document
    """
    service = DocumentService(db)
    document = await service.create_document(
        tenant_id=current_user.tenant_id,
        project_id=data.project_id,
        doc_type=data.doc_type,
        title=data.title,
        content=data.content,
        created_by=current_user.id,
        metadata=data.metadata,
    )
    return DocumentResponse.model_validate(document)


@router.get("/generation-sessions", response_model=list[DocumentGenerationSessionResponse])
async def list_generation_sessions(
    project_id: UUID = Query(..., description="Project ID"),
    status: str | None = Query(None, description="Optional generation session status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    llm_gateway: LLMGateway | None = Depends(get_llm_gateway),
):
    """List interactive document generation sessions for a project."""
    await ensure_project_access(db, project_id, current_user)

    if status and status not in {item.value for item in GenerationSessionStatus}:
        raise HTTPException(status_code=400, detail="Invalid generation session status")

    service = DocumentGenerationService(db, llm_gateway)
    sessions = await service.list_generation_sessions(
        tenant_id=current_user.tenant_id,
        project_id=project_id,
        status=status,
    )
    return [DocumentGenerationSessionResponse.model_validate(session) for session in sessions]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a document by ID.

    Args:
        document_id: Document UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Document details

    Raises:
        HTTPException: If document not found or access denied
    """
    document = await check_document_access(
        document_id, current_user.id, db, current_user.tenant_id
    )
    return DocumentResponse.model_validate(document)


@router.patch("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: UUID,
    data: DocumentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a document.

    Args:
        document_id: Document UUID
        data: Update data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated document

    Raises:
        HTTPException: If document not found or access denied
    """
    await check_document_access(
        document_id, current_user.id, db, current_user.tenant_id
    )

    if data.status is not None:
        raise HTTPException(
            status_code=400,
            detail="Use the document status workflow endpoint to change status",
        )

    service = DocumentService(db)
    updated = await service.update_document(
        document_id=document_id,
        tenant_id=current_user.tenant_id,
        updates=data,
    )
    return DocumentResponse.model_validate(updated)


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a document (soft delete).

    Args:
        document_id: Document UUID
        db: Database session
        current_user: Current authenticated user

    Raises:
        HTTPException: If document not found or access denied
    """
    await check_document_access(
        document_id, current_user.id, db, current_user.tenant_id, require_owner=True
    )

    service = DocumentService(db)
    deleted = await service.delete_document(document_id, current_user.tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")


@router.post("/{document_id}/references", response_model=DocumentReferenceResponse, status_code=201)
async def create_document_reference(
    document_id: UUID,
    data: DocumentReferenceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a formal downstream reference from this source document."""
    source_doc = await check_document_access(
        document_id, current_user.id, db, current_user.tenant_id
    )

    service = TraceabilityService(db)
    try:
        reference = await service.create_document_reference(
            tenant_id=current_user.tenant_id,
            project_id=source_doc.project_id,
            source_document_id=document_id,
            target_document_id=data.target_document_id,
            reference_type=data.reference_type,
            created_by=current_user.id,
            source_section=data.source_section,
            target_section=data.target_section,
            metadata=data.metadata,
        )
        return DocumentReferenceResponse.model_validate(reference)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{document_id}/references", response_model=DocumentReferenceListResponse)
async def list_document_references(
    document_id: UUID,
    direction: str = Query("all", description="all, incoming, or outgoing"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List formal references connected to a document."""
    await check_document_access(
        document_id, current_user.id, db, current_user.tenant_id
    )

    service = TraceabilityService(db)
    references = await service.list_document_references(
        tenant_id=current_user.tenant_id,
        document_id=document_id,
        direction=direction,
    )
    return DocumentReferenceListResponse(
        items=[DocumentReferenceResponse.model_validate(item) for item in references],
        total=len(references),
    )


@router.post("/{document_id}/impact-analysis", response_model=DocumentImpactAnalysisResponse, status_code=201)
async def create_document_impact_analysis(
    document_id: UUID,
    data: DocumentImpactAnalysisCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create persisted impact analysis and sync proposals for a document."""
    await check_document_access(
        document_id, current_user.id, db, current_user.tenant_id
    )

    service = TraceabilityService(db)
    try:
        analysis = await service.create_document_impact_analysis(
            tenant_id=current_user.tenant_id,
            document_id=document_id,
            created_by=current_user.id,
            trigger_type=data.trigger_type,
            summary=data.summary,
            change_request_id=data.change_request_id,
        )
        loaded = await service.get_document_impact_analysis(analysis.id, current_user.tenant_id)
        return DocumentImpactAnalysisResponse.model_validate(loaded or analysis)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{document_id}/status", response_model=DocumentResponse)
async def update_document_status(
    document_id: UUID,
    data: DocumentStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update document status.

    Args:
        document_id: Document UUID
        data: Status update data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated document

    Raises:
        HTTPException: If document not found or access denied
    """
    if data.status not in ALLOWED_STATUS_TRANSITIONS:
        raise HTTPException(status_code=400, detail=f"Unknown document status '{data.status}'")

    document = await check_document_access(
        document_id,
        current_user.id,
        db,
        current_user.tenant_id,
    )
    await require_document_status_permission(document, current_user, db, data.status)

    service = DocumentService(db)
    try:
        updated = await service.transition_status(
            document_id=document_id,
            tenant_id=current_user.tenant_id,
            status_update=data,
            changed_by=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if updated and updated.status in {
        DocumentStatus.PENDING_REVIEW.value,
        DocumentStatus.REVIEW.value,
        DocumentStatus.IN_REVIEW.value,
        DocumentStatus.APPROVED.value,
        DocumentStatus.PUBLISHED.value,
        DocumentStatus.ARCHIVED.value,
    }:
        status_labels = {
            DocumentStatus.PENDING_REVIEW.value: "待评审",
            DocumentStatus.REVIEW.value: "评审中",
            DocumentStatus.IN_REVIEW.value: "评审中",
            DocumentStatus.APPROVED.value: "已批准",
            DocumentStatus.PUBLISHED.value: "已发布",
            DocumentStatus.ARCHIVED.value: "已归档",
        }
        await UserNotificationService(db).notify_project_members(
            tenant_id=current_user.tenant_id,
            project_id=updated.project_id,
            actor_id=current_user.id,
            title=f"文档{status_labels[updated.status]}",
            body=f"《{updated.title}》已进入{status_labels[updated.status]}状态。",
            category="document_lifecycle",
            priority="high" if updated.status in {DocumentStatus.PENDING_REVIEW.value, DocumentStatus.REVIEW.value, DocumentStatus.IN_REVIEW.value} else "normal",
            action_url=f"/projects/{updated.project_id}/documents/{updated.id}",
            entity_type="document",
            entity_id=updated.id,
            dedupe_key=f"document:{updated.id}:status:{updated.status}:v{updated.version}",
        )
    return DocumentResponse.model_validate(updated)


@router.get("/{document_id}/status-capabilities", response_model=DocumentStatusCapabilitiesResponse)
async def get_document_status_capabilities(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List workflow and permission readiness for every document status action."""
    document = await check_document_access(
        document_id,
        current_user.id,
        db,
        current_user.tenant_id,
    )
    service = DocumentService(db)
    current_status = document.status or DocumentStatus.DRAFT.value
    policy = await service.get_document_lifecycle_policy(document)
    capabilities: list[DocumentStatusCapability] = []

    for status_config in policy.statuses:
        status = status_config.key
        if status == current_status:
            continue
        decision = await get_document_status_permission_decision(
            document,
            current_user,
            db,
            status,
        )
        blockers = await service.get_status_transition_blockers(document, status, policy)
        capabilities.append(
            DocumentStatusCapability(
                status=status,
                label=status_config.label,
                permission_action=decision["permission_action"],
                allowed=bool(decision["allowed"]) and not blockers,
                authorization_reason=decision["reason"],
                blockers=blockers,
            )
        )

    return DocumentStatusCapabilitiesResponse(
        current_status=current_status,
        policy_revision=policy.revision,
        capabilities=capabilities,
    )


@router.get("/{document_id}/status-history", response_model=list[DocumentStatusTransitionResponse])
async def list_document_status_history(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List document status transition history."""
    await check_document_access(
        document_id, current_user.id, db, current_user.tenant_id
    )

    service = DocumentService(db)
    return await service.list_status_history(document_id, current_user.tenant_id)


# Version Endpoints
@router.post("/{document_id}/versions", response_model=DocumentVersionResponse, status_code=201)
async def create_version(
    document_id: UUID,
    data: DocumentVersionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new document version.

    Args:
        document_id: Document UUID
        data: Version creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created version

    Raises:
        HTTPException: If document not found or access denied
    """
    await check_document_access(
        document_id, current_user.id, db, current_user.tenant_id
    )

    service = DocumentService(db)
    version = await service.create_version(
        document_id=document_id,
        tenant_id=current_user.tenant_id,
        content=data.content,
        changes_summary=data.changes_summary,
        created_by=current_user.id,
    )
    if not version:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentVersionResponse.model_validate(version)


@router.get("/{document_id}/versions", response_model=DocumentVersionListResponse)
async def get_version_history(
    document_id: UUID,
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get version history for a document.

    Args:
        document_id: Document UUID
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        List of document versions

    Raises:
        HTTPException: If document not found or access denied
    """
    await check_document_access(
        document_id, current_user.id, db, current_user.tenant_id
    )

    service = DocumentService(db)
    versions = await service.get_version_history(
        document_id=document_id,
        tenant_id=current_user.tenant_id,
    )

    total = len(versions)
    skip = (pagination.page - 1) * pagination.page_size
    paginated_versions = versions[skip : skip + pagination.page_size]

    return DocumentVersionListResponse(
        items=[DocumentVersionResponse.model_validate(v) for v in paginated_versions],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=(pagination.page * pagination.page_size) < total,
    )


# Baseline Endpoints
@router.post("/{document_id}/baselines", response_model=DocumentBaselineResponse, status_code=201)
async def create_baseline(
    document_id: UUID,
    data: DocumentBaselineCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a baseline for a document version.

    Args:
        document_id: Document UUID
        data: Baseline creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created baseline

    Raises:
        HTTPException: If document or version not found or access denied
    """
    await check_document_access(
        document_id, current_user.id, db, current_user.tenant_id
    )

    service = DocumentService(db)
    baseline = await service.create_baseline(
        document_id=document_id,
        version_id=data.version_id,
        tenant_id=current_user.tenant_id,
        baseline_name=data.baseline_name,
        reason=data.baseline_reason,
        approved_by=data.approved_by or current_user.id,
    )
    if not baseline:
        raise HTTPException(status_code=404, detail="Document or version not found")
    return DocumentBaselineResponse.model_validate(baseline)


@router.get("/{document_id}/baselines", response_model=DocumentBaselineListResponse)
async def list_baselines(
    document_id: UUID,
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List baselines for a document.

    Args:
        document_id: Document UUID
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        List of document baselines

    Raises:
        HTTPException: If document not found or access denied
    """
    from sqlalchemy import select, func
    from app.domains.documents.models import DocumentBaseline

    await check_document_access(
        document_id, current_user.id, db, current_user.tenant_id
    )

    # Count total
    count_result = await db.execute(
        select(func.count(DocumentBaseline.id)).where(
            DocumentBaseline.document_id == document_id,
            DocumentBaseline.tenant_id == current_user.tenant_id,
        )
    )
    total = count_result.scalar()

    # Get paginated results
    result = await db.execute(
        select(DocumentBaseline)
        .where(
            DocumentBaseline.document_id == document_id,
            DocumentBaseline.tenant_id == current_user.tenant_id,
        )
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
        .order_by(DocumentBaseline.created_at.desc())
    )
    baselines = list(result.scalars().all())

    return DocumentBaselineListResponse(
        items=[DocumentBaselineResponse.model_validate(b) for b in baselines],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=(pagination.page * pagination.page_size) < total,
    )


@router.post("/{document_id}/baselines/{baseline_id}/rollback", response_model=DocumentResponse)
async def rollback_to_baseline(
    document_id: UUID,
    baseline_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rollback document to a baseline.

    Args:
        document_id: Document UUID
        baseline_id: Baseline UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Rolled back document

    Raises:
        HTTPException: If baseline not found or access denied
    """
    await check_document_access(
        document_id, current_user.id, db, current_user.tenant_id, require_owner=True
    )

    service = DocumentService(db)
    document = await service.rollback_to_baseline(
        baseline_id=baseline_id,
        tenant_id=current_user.tenant_id,
    )
    if not document:
        raise HTTPException(status_code=404, detail="Baseline not found")
    return DocumentResponse.model_validate(document)


# Quality Assessment Endpoints
@router.get("/{document_id}/quality", response_model=list[QualityResultResponse])
async def get_quality_results(
    document_id: UUID,
    quality_type: str | None = Query(None, description="Filter by quality type"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get quality assessment results for a document.

    Args:
        document_id: Document UUID
        quality_type: Optional quality type filter
        db: Database session
        current_user: Current authenticated user

    Returns:
        List of quality results

    Raises:
        HTTPException: If document not found or access denied
    """
    from sqlalchemy import select
    from app.domains.documents.models import QualityResult

    await check_document_access(
        document_id, current_user.id, db, current_user.tenant_id
    )

    query = select(QualityResult).where(
        QualityResult.document_id == document_id,
        QualityResult.tenant_id == current_user.tenant_id,
    )
    if quality_type:
        query = query.where(QualityResult.quality_type == quality_type)

    result = await db.execute(query.order_by(QualityResult.checked_at.desc()))
    results = list(result.scalars().all())

    return [QualityResultResponse.model_validate(r) for r in results]


@router.post("/{document_id}/quality/check", response_model=QualityResultResponse)
async def check_quality(
    document_id: UUID,
    data: QualityCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    llm_gateway: LLMGateway | None = Depends(get_llm_gateway),
):
    """Run quality check on a document.

    Args:
        document_id: Document UUID
        data: Quality check parameters
        db: Database session
        current_user: Current authenticated user
        llm_gateway: LLM gateway for AI-powered assessment

    Returns:
        Quality check result

    Raises:
        HTTPException: If document not found or access denied
    """
    await check_document_access(
        document_id, current_user.id, db, current_user.tenant_id
    )

    # Validate quality type
    valid_quality_types = [qt.value for qt in QualityType]
    if data.quality_type not in valid_quality_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid quality type. Must be one of: {valid_quality_types}",
        )

    service = DocumentService(db)
    result = await service.assess_quality(
        document_id=document_id,
        tenant_id=current_user.tenant_id,
        quality_type=data.quality_type,
        version_id=data.version_id,
        llm_gateway=llm_gateway,
    )
    return QualityResultResponse.model_validate(result)


# Document Generation Endpoint
@router.post("/generation-sessions", response_model=DocumentGenerationSessionResponse, status_code=201)
async def start_generation_session(
    data: DocumentGenerationSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    llm_gateway: LLMGateway | None = Depends(get_llm_gateway),
):
    """Start an interactive, section-by-section document generation session."""
    await ensure_project_access(db, data.project_id, current_user)

    valid_doc_types = [dt.value for dt in DocumentType]
    if data.doc_type not in valid_doc_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document type. Must be one of: {valid_doc_types}",
        )

    context = dict(data.context)
    if data.title:
        context["title"] = data.title

    service = DocumentGenerationService(db, llm_gateway)
    session = await service.start_generation_session(
        tenant_id=current_user.tenant_id,
        project_id=data.project_id,
        doc_type=data.doc_type,
        title=data.title,
        template_id=data.template_id,
        context=context,
        created_by=current_user.id,
    )
    return DocumentGenerationSessionResponse.model_validate(session)


@router.get("/generation-sessions/{session_id}", response_model=DocumentGenerationSessionResponse)
async def get_generation_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    llm_gateway: LLMGateway | None = Depends(get_llm_gateway),
):
    """Get an interactive document generation session."""
    service = DocumentGenerationService(db, llm_gateway)
    session = await service.get_generation_session(session_id, current_user.tenant_id)
    if not session:
        raise HTTPException(status_code=404, detail="Generation session not found")
    await ensure_project_access(db, session.project_id, current_user)
    return DocumentGenerationSessionResponse.model_validate(session)


@router.post("/generation-sessions/{session_id}/cancel", response_model=DocumentGenerationSessionResponse)
async def cancel_generation_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    llm_gateway: LLMGateway | None = Depends(get_llm_gateway),
):
    """Cancel a non-finalized interactive document generation session."""
    service = DocumentGenerationService(db, llm_gateway)
    session = await service.get_generation_session(session_id, current_user.tenant_id)
    if not session:
        raise HTTPException(status_code=404, detail="Generation session not found")
    await ensure_project_access(db, session.project_id, current_user)

    try:
        cancelled = await service.cancel_generation_session(
            session_id=session_id,
            tenant_id=current_user.tenant_id,
            cancelled_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DocumentGenerationSessionResponse.model_validate(cancelled)


@router.post("/generation-sessions/{session_id}/messages", response_model=DocumentGenerationTurnResponse)
async def continue_generation_session(
    session_id: UUID,
    data: DocumentGenerationMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    llm_gateway: LLMGateway | None = Depends(get_llm_gateway),
):
    """Continue an interactive document generation session."""
    service = DocumentGenerationService(db, llm_gateway)
    try:
        result = await service.continue_generation_session(
            session_id=session_id,
            tenant_id=current_user.tenant_id,
            user_message=data.message,
            action=data.action,
            created_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session_response = DocumentGenerationSessionResponse.model_validate(result.session)
    return DocumentGenerationTurnResponse(
        session=session_response,
        current_section=DocumentGenerationSectionResponse.model_validate(result.current_section),
        assistant_message=result.assistant_message,
        section_summaries=result.section_summaries,
        write_log=result.write_log,
        skill_trace=result.skill_trace,
        quality_gate=result.quality_gate,
        pending_confirmations=result.pending_confirmations,
    )


@router.post("/generation-sessions/{session_id}/finalize", response_model=DocumentGenerateResponse)
async def finalize_generation_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    llm_gateway: LLMGateway | None = Depends(get_llm_gateway),
):
    """Finalize an interactive session into a draft document."""
    service = DocumentGenerationService(db, llm_gateway)
    try:
        document = await service.finalize_generation_session(
            session_id=session_id,
            tenant_id=current_user.tenant_id,
            created_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return DocumentGenerateResponse(
        document_id=document.id,
        doc_type=document.doc_type,
        title=document.title,
        content=document.content,
        status=document.status,
        version=document.version,
        generated_at=document.created_at,
    )


@router.post("/generate", response_model=DocumentGenerateResponse)
async def generate_document(
    data: DocumentGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    llm_gateway: LLMGateway | None = Depends(get_llm_gateway),
):
    """Generate a new document using AI.

    Args:
        data: Document generation parameters
        db: Database session
        current_user: Current authenticated user
        llm_gateway: LLM gateway for generation

    Returns:
        Generated document

    Raises:
        HTTPException: If project not found or access denied
    """
    from sqlalchemy import select
    from app.models.projects import Project, ProjectMember

    # Verify project access
    result = await db.execute(
        select(Project).where(
            Project.id == data.project_id,
            Project.tenant_id == current_user.tenant_id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()

    if not project:
        # Check if user is a member
        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == data.project_id,
                ProjectMember.user_id == current_user.id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Access denied to project")

    # Validate document type
    valid_doc_types = [dt.value for dt in DocumentType]
    if data.doc_type not in valid_doc_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document type. Must be one of: {valid_doc_types}",
        )

    # Add project context
    context = dict(data.context)
    context["project_name"] = context.get("project_name", project.name if project else "Unknown")
    if data.title:
        context["title"] = data.title

    service = DocumentGenerationService(db, llm_gateway)
    document = await service.generate_document(
        doc_type=data.doc_type,
        project_id=data.project_id,
        tenant_id=current_user.tenant_id,
        context=context,
        created_by=current_user.id,
        template_id=data.template_id,
    )

    return DocumentGenerateResponse(
        document_id=document.id,
        doc_type=document.doc_type,
        title=document.title,
        content=document.content,
        status=document.status,
        version=document.version,
        generated_at=document.created_at,
    )


# Document Statistics Endpoint
@router.get("/statistics/summary", response_model=DocumentStatistics)
async def get_document_statistics(
    project_id: UUID | None = Query(None, description="Filter by project ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get document statistics.

    Args:
        project_id: Optional project filter
        db: Database session
        current_user: Current authenticated user

    Returns:
        Document statistics
    """
    from sqlalchemy import select, func, case
    from app.domains.documents.models import Document

    # Get total count
    count_query = select(func.count(Document.id)).where(
        Document.tenant_id == current_user.tenant_id,
        Document.deleted_at.is_(None),
    )
    if project_id:
        count_query = count_query.where(Document.project_id == project_id)
    count_result = await db.execute(count_query)
    total = count_result.scalar()

    # Get counts by type using GROUP BY
    type_query = select(
        Document.doc_type,
        func.count(Document.id).label('count')
    ).where(
        Document.tenant_id == current_user.tenant_id,
        Document.deleted_at.is_(None),
    )
    if project_id:
        type_query = type_query.where(Document.project_id == project_id)
    type_query = type_query.group_by(Document.doc_type)
    type_result = await db.execute(type_query)
    by_type = {row.doc_type: row.count for row in type_result.all()}

    # Get counts by status using GROUP BY
    status_query = select(
        Document.status,
        func.count(Document.id).label('count')
    ).where(
        Document.tenant_id == current_user.tenant_id,
        Document.deleted_at.is_(None),
    )
    if project_id:
        status_query = status_query.where(Document.project_id == project_id)
    status_query = status_query.group_by(Document.status)
    status_result = await db.execute(status_query)
    by_status = {row.status: row.count for row in status_result.all()}

    # Get average quality score using database aggregation
    avg_query = select(func.avg(Document.quality_score)).where(
        Document.tenant_id == current_user.tenant_id,
        Document.deleted_at.is_(None),
        Document.quality_score.isnot(None),
    )
    if project_id:
        avg_query = avg_query.where(Document.project_id == project_id)
    avg_result = await db.execute(avg_query)
    avg_quality = avg_result.scalar()

    return DocumentStatistics(
        total_documents=total,
        by_type=by_type,
        by_status=by_status,
        average_quality_score=round(avg_quality, 2) if avg_quality else None,
    )
