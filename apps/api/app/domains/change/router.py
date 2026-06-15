"""Change Domain API Router

FastAPI endpoints for change requests, field patches, traceability, and controlled backwrite.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.security import decode_token
from app.models.identity import User
from app.domains.change.models import ChangeRequest
from app.domains.change.schemas import (
    ChangeRequestCreate,
    ChangeRequestUpdate,
    ChangeRequestResponse,
    ChangeRequestListResponse,
    ChangeAuditCommandCenterResponse,
    ChangeRequestApproval,
    ChangeRequestRejection,
    FieldPatchCreate,
    FieldPatchResponse,
    FieldPatchApproval,
    FieldPatchRejection,
    ChangeRequestCommentCreate,
    ChangeRequestCommentResponse,
    TraceabilityMatrixItem,
    TraceabilityMatrixResponse,
    TraceabilityCoverageResponse,
    TraceabilitySuggestionAcceptanceRequest,
    TraceabilitySuggestionAcceptanceResponse,
    ImpactAnalysisItem,
    ImpactAnalysisResponse,
    DocumentImpactAnalysisResponse,
    DocumentSyncProposalResponse,
    DocumentTraceabilityResponse,
    ConflictAnalysisResponse,
    ConflictAnalysisCompletionRequest,
    ConflictAssignmentRequest,
    ConflictRejectionRequest,
    ConflictRevisionAcceptanceRequest,
    ConflictScanResponse,
    DocumentConflictListResponse,
    DocumentConflictResponse,
    FullTraceabilityMatrixResponse,
    PaginationParams,
    SyncProposalDecision,
)
from app.domains.change.conflict_service import ConflictGovernanceService
from app.domains.change.service import (
    ChangeAuditCommandCenterService,
    ChangeService,
    FieldPatchService,
    TraceabilityService,
    ControlledBackwriteService,
    ChangeRequestCommentService,
)
from app.services.audit_service import AuditService


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


async def check_change_request_access(
    change_request_id: UUID,
    user_id: UUID,
    db: AsyncSession,
    tenant_id: UUID,
) -> ChangeRequest:
    """Check if user has access to change request and return it.

    Args:
        change_request_id: Change request UUID
        user_id: User UUID
        db: Database session
        tenant_id: Tenant UUID

    Returns:
        ChangeRequest if access allowed

    Raises:
        HTTPException: If access denied or change request not found
    """
    service = ChangeService(db)
    change_request = await service.get_change_request(change_request_id, tenant_id)

    if not change_request:
        raise HTTPException(status_code=404, detail="Change request not found")

    return change_request


# =============================================================================
# Change Request Endpoints
# =============================================================================


@router.post("/conflicts/projects/{project_id}/scan", response_model=ConflictScanResponse)
async def scan_project_conflicts(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run and persist deterministic conflict rules for one project."""
    return await ConflictGovernanceService(db).scan_project(
        tenant_id=current_user.tenant_id,
        project_id=project_id,
    )


@router.get("/conflicts/projects/{project_id}", response_model=DocumentConflictListResponse)
async def list_project_conflicts(
    project_id: UUID,
    severity: str | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List persisted document conflicts for one project."""
    return await ConflictGovernanceService(db).list_project_conflicts(
        tenant_id=current_user.tenant_id,
        project_id=project_id,
        severity=severity,
        status=status,
    )


@router.get("/conflicts/{conflict_id}", response_model=DocumentConflictResponse)
async def get_persisted_conflict(
    conflict_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get one persisted document conflict."""
    conflict = await ConflictGovernanceService(db).get_conflict(
        tenant_id=current_user.tenant_id,
        conflict_id=conflict_id,
    )
    if not conflict:
        raise HTTPException(status_code=404, detail="Document conflict not found")
    return conflict


@router.post("/conflicts/{conflict_id}/assign", response_model=DocumentConflictResponse)
async def assign_persisted_conflict(
    conflict_id: UUID,
    data: ConflictAssignmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Assign or reassign a persisted document conflict."""
    service = ConflictGovernanceService(db)
    try:
        conflict = await service.assign_conflict(
            tenant_id=current_user.tenant_id,
            conflict_id=conflict_id,
            actor_id=current_user.id,
            assignee_user_id=data.assignee_user_id,
            reason=data.reason,
        )
        await AuditService(db).log_action(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="document_conflict.assign",
            resource_type="document_conflict",
            resource_id=conflict.id,
            metadata={"assignee_user_id": str(data.assignee_user_id)},
        )
        return conflict
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/conflicts/{conflict_id}/complete-analysis", response_model=DocumentConflictResponse)
async def complete_persisted_conflict_analysis(
    conflict_id: UUID,
    data: ConflictAnalysisCompletionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move a persisted document conflict from analysis to decision."""
    service = ConflictGovernanceService(db)
    try:
        conflict = await service.complete_analysis(
            tenant_id=current_user.tenant_id,
            conflict_id=conflict_id,
            actor_id=current_user.id,
            reason=data.reason,
            evidence=data.evidence,
        )
        await AuditService(db).log_action(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="document_conflict.complete_analysis",
            resource_type="document_conflict",
            resource_id=conflict.id,
            metadata={"status": conflict.status},
        )
        return conflict
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/conflicts/{conflict_id}/reject", response_model=DocumentConflictResponse)
async def reject_persisted_conflict(
    conflict_id: UUID,
    data: ConflictRejectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reject an inapplicable or false persisted document conflict."""
    service = ConflictGovernanceService(db)
    try:
        conflict = await service.reject_conflict(
            tenant_id=current_user.tenant_id,
            conflict_id=conflict_id,
            actor_id=current_user.id,
            reason=data.reason,
            evidence=data.evidence,
        )
        await AuditService(db).log_action(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="document_conflict.reject",
            resource_type="document_conflict",
            resource_id=conflict.id,
            metadata={"status": conflict.status},
        )
        return conflict
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/conflicts/{conflict_id}/accept-revision", response_model=DocumentConflictResponse)
async def accept_persisted_conflict_revision(
    conflict_id: UUID,
    data: ConflictRevisionAcceptanceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accept a conflict revision and create a linked change-request draft."""
    service = ConflictGovernanceService(db)
    try:
        conflict = await service.accept_revision(
            tenant_id=current_user.tenant_id,
            conflict_id=conflict_id,
            actor_id=current_user.id,
            suggested_revision=data.suggested_revision,
            reason=data.reason,
            evidence=data.evidence,
        )
        await AuditService(db).log_action(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="document_conflict.accept_revision",
            resource_type="document_conflict",
            resource_id=conflict.id,
            metadata={
                "status": conflict.status,
                "change_request_id": str(conflict.linked_change_request_id),
            },
        )
        return conflict
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=ChangeRequestListResponse)
async def list_change_requests(
    project_id: UUID | None = Query(None, description="Filter by project ID"),
    status: str | None = Query(None, description="Filter by status"),
    change_type: str | None = Query(None, description="Filter by change type"),
    priority: str | None = Query(None, description="Filter by priority"),
    pagination: PaginationParams = Query(default=PaginationParams()),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all change requests for the current tenant.

    Args:
        project_id: Optional project filter
        status: Optional status filter
        change_type: Optional change type filter
        priority: Optional priority filter
        pagination: Pagination parameters
        db: Database session
        current_user: Current authenticated user

    Returns:
        Paginated list of change requests
    """
    service = ChangeService(db)
    change_requests, total = await service.list_change_requests(
        tenant_id=current_user.tenant_id,
        project_id=project_id,
        status=status,
        change_type=change_type,
        priority=priority,
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
    )
    has_more = (pagination.page * pagination.page_size) < total

    return ChangeRequestListResponse(
        items=[ChangeRequestResponse.model_validate(cr) for cr in change_requests],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_more=has_more,
    )


@router.post("", response_model=ChangeRequestResponse, status_code=201)
async def create_change_request(
    data: ChangeRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new change request.

    Args:
        data: Change request creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created change request
    """
    service = ChangeService(db)
    change_request = await service.create_change_request(
        tenant_id=current_user.tenant_id,
        project_id=data.project_id,
        source_doc_id=data.source_document_id,
        target_doc_id=data.target_document_id,
        change_type=data.change_type,
        description=data.description,
        requested_by=current_user.id,
        priority=data.priority,
        rationale=data.rationale,
        impact_analysis=data.impact_analysis,
        risk_assessment=data.risk_assessment,
    )
    return ChangeRequestResponse.model_validate(change_request)


@router.get("/command-center", response_model=ChangeAuditCommandCenterResponse)
async def get_change_audit_command_center(
    project_id: UUID | None = Query(None, description="Optional project scope"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get change, patch, and traceability readiness for release review."""
    service = ChangeAuditCommandCenterService(db)
    return await service.get_command_center(
        tenant_id=current_user.tenant_id,
        project_id=project_id,
    )


@router.get("/{change_request_id}", response_model=ChangeRequestResponse)
async def get_change_request(
    change_request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a change request by ID.

    Args:
        change_request_id: Change request UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Change request details

    Raises:
        HTTPException: If change request not found
    """
    change_request = await check_change_request_access(
        change_request_id, current_user.id, db, current_user.tenant_id
    )
    return ChangeRequestResponse.model_validate(change_request)


@router.patch("/{change_request_id}", response_model=ChangeRequestResponse)
async def update_change_request(
    change_request_id: UUID,
    data: ChangeRequestUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a change request.

    Args:
        change_request_id: Change request UUID
        data: Update data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated change request

    Raises:
        HTTPException: If change request not found or not editable
    """
    await check_change_request_access(
        change_request_id, current_user.id, db, current_user.tenant_id
    )

    service = ChangeService(db)
    try:
        updated = await service.update_change_request(
            change_request_id=change_request_id,
            tenant_id=current_user.tenant_id,
            updates=data,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Change request not found")
        return ChangeRequestResponse.model_validate(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{change_request_id}", status_code=204)
async def delete_change_request(
    change_request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a change request (soft delete).

    Args:
        change_request_id: Change request UUID
        db: Database session
        current_user: Current authenticated user

    Raises:
        HTTPException: If change request not found
    """
    service = ChangeService(db)
    try:
        deleted = await service.soft_delete_change_request(
            change_request_id=change_request_id,
            tenant_id=current_user.tenant_id,
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Change request not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{change_request_id}/submit", response_model=ChangeRequestResponse)
async def submit_for_review(
    change_request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit change request for review.

    Args:
        change_request_id: Change request UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated change request

    Raises:
        HTTPException: If change request not found or not submittable
    """
    await check_change_request_access(
        change_request_id, current_user.id, db, current_user.tenant_id
    )

    service = ChangeService(db)
    try:
        updated = await service.submit_for_review(
            change_request_id=change_request_id,
            tenant_id=current_user.tenant_id,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Change request not found")
        return ChangeRequestResponse.model_validate(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{change_request_id}/approve", response_model=ChangeRequestResponse)
async def approve_change_request(
    change_request_id: UUID,
    data: ChangeRequestApproval,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve a change request.

    Args:
        change_request_id: Change request UUID
        data: Approval data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated change request

    Raises:
        HTTPException: If change request not found or not approvable
    """
    await check_change_request_access(
        change_request_id, current_user.id, db, current_user.tenant_id
    )

    service = ChangeService(db)
    try:
        updated = await service.approve_change_request(
            change_request_id=change_request_id,
            tenant_id=current_user.tenant_id,
            reviewer_id=current_user.id,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Change request not found")
        return ChangeRequestResponse.model_validate(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{change_request_id}/reject", response_model=ChangeRequestResponse)
async def reject_change_request(
    change_request_id: UUID,
    data: ChangeRequestRejection,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reject a change request.

    Args:
        change_request_id: Change request UUID
        data: Rejection data with reason
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated change request

    Raises:
        HTTPException: If change request not found or not rejectable
    """
    await check_change_request_access(
        change_request_id, current_user.id, db, current_user.tenant_id
    )

    service = ChangeService(db)
    try:
        updated = await service.reject_change_request(
            change_request_id=change_request_id,
            tenant_id=current_user.tenant_id,
            reviewer_id=current_user.id,
            reason=data.reason,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Change request not found")
        return ChangeRequestResponse.model_validate(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{change_request_id}/apply", response_model=ChangeRequestResponse)
async def apply_change_request(
    change_request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply a change request (create new version with patches).

    Args:
        change_request_id: Change request UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated change request

    Raises:
        HTTPException: If change request not found or not applicable
    """
    await check_change_request_access(
        change_request_id, current_user.id, db, current_user.tenant_id
    )

    service = ChangeService(db)
    try:
        updated = await service.apply_change_request(
            change_request_id=change_request_id,
            tenant_id=current_user.tenant_id,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Change request not found")
        return ChangeRequestResponse.model_validate(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{change_request_id}/cancel", response_model=ChangeRequestResponse)
async def cancel_change_request(
    change_request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel a change request.

    Args:
        change_request_id: Change request UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated change request

    Raises:
        HTTPException: If change request not found or not cancellable
    """
    await check_change_request_access(
        change_request_id, current_user.id, db, current_user.tenant_id
    )

    service = ChangeService(db)
    try:
        updated = await service.cancel_change_request(
            change_request_id=change_request_id,
            tenant_id=current_user.tenant_id,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Change request not found")
        return ChangeRequestResponse.model_validate(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# Field Patch Endpoints
# =============================================================================


@router.get("/{change_request_id}/patches", response_model=list[FieldPatchResponse])
async def get_patches(
    change_request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all patches for a change request.

    Args:
        change_request_id: Change request UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        List of field patches
    """
    await check_change_request_access(
        change_request_id, current_user.id, db, current_user.tenant_id
    )

    service = FieldPatchService(db)
    patches = await service.get_patches_for_change_request(
        change_request_id=change_request_id,
        tenant_id=current_user.tenant_id,
    )
    return [FieldPatchResponse.model_validate(p) for p in patches]


@router.post("/{change_request_id}/patches", response_model=FieldPatchResponse, status_code=201)
async def create_field_patch(
    change_request_id: UUID,
    data: FieldPatchCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a field patch for a change request.

    Args:
        change_request_id: Change request UUID
        data: Patch creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created field patch
    """
    change_request = await check_change_request_access(
        change_request_id, current_user.id, db, current_user.tenant_id
    )

    # Only allow patches on draft change requests
    if change_request.status != "draft":
        raise HTTPException(status_code=400, detail="Can only add patches to draft change requests")

    service = FieldPatchService(db)
    try:
        patch = await service.create_field_patch(
            change_request_id=change_request_id,
            tenant_id=current_user.tenant_id,
            document_id=data.document_id,
            field_path=data.field_path,
            old_value=data.old_value,
            new_value=data.new_value,
            patch_type=data.patch_type,
        )
        return FieldPatchResponse.model_validate(patch)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{change_request_id}/patches/{patch_id}/approve", response_model=FieldPatchResponse)
async def approve_field_patch(
    change_request_id: UUID,
    patch_id: UUID,
    data: FieldPatchApproval,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve a field patch.

    Args:
        change_request_id: Change request UUID
        patch_id: Patch UUID
        data: Approval data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated field patch
    """
    await check_change_request_access(
        change_request_id, current_user.id, db, current_user.tenant_id
    )

    service = FieldPatchService(db)
    try:
        updated = await service.approve_field_patch(
            patch_id=patch_id,
            tenant_id=current_user.tenant_id,
            reviewer_id=current_user.id,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Patch not found")
        return FieldPatchResponse.model_validate(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{change_request_id}/patches/{patch_id}/reject", response_model=FieldPatchResponse)
async def reject_field_patch(
    change_request_id: UUID,
    patch_id: UUID,
    data: FieldPatchRejection,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reject a field patch.

    Args:
        change_request_id: Change request UUID
        patch_id: Patch UUID
        data: Rejection data with reason
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated field patch
    """
    await check_change_request_access(
        change_request_id, current_user.id, db, current_user.tenant_id
    )

    service = FieldPatchService(db)
    try:
        updated = await service.reject_field_patch(
            patch_id=patch_id,
            tenant_id=current_user.tenant_id,
            reviewer_id=current_user.id,
            reason=data.reason,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Patch not found")
        return FieldPatchResponse.model_validate(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# Comment Endpoints
# =============================================================================


@router.get("/{change_request_id}/comments", response_model=list[ChangeRequestCommentResponse])
async def get_comments(
    change_request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all comments for a change request.

    Args:
        change_request_id: Change request UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        List of comments
    """
    await check_change_request_access(
        change_request_id, current_user.id, db, current_user.tenant_id
    )

    service = ChangeRequestCommentService(db)
    comments = await service.get_comments_for_change_request(
        change_request_id=change_request_id,
        tenant_id=current_user.tenant_id,
    )
    return [ChangeRequestCommentResponse.model_validate(c) for c in comments]


@router.post("/{change_request_id}/comments", response_model=ChangeRequestCommentResponse, status_code=201)
async def create_comment(
    change_request_id: UUID,
    data: ChangeRequestCommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a comment on a change request.

    Args:
        change_request_id: Change request UUID
        data: Comment creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created comment
    """
    await check_change_request_access(
        change_request_id, current_user.id, db, current_user.tenant_id
    )

    service = ChangeRequestCommentService(db)
    comment = await service.create_comment(
        change_request_id=change_request_id,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        content=data.content,
    )
    return ChangeRequestCommentResponse.model_validate(comment)


# =============================================================================
# Traceability Endpoints
# =============================================================================


@router.get("/traceability/matrix")
async def get_traceability_matrix(
    project_id: UUID = Query(..., description="Project ID"),
    doc_type: str | None = Query(None, description="Filter by document type"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate traceability matrix for a project.

    Args:
        project_id: Project UUID
        doc_type: Optional document type filter
        db: Database session
        current_user: Current authenticated user

    Returns:
        Traceability matrix items
    """
    service = TraceabilityService(db)
    items = await service.generate_traceability_matrix(
        project_id=project_id,
        tenant_id=current_user.tenant_id,
        doc_type=doc_type,
    )
    return {"items": [item.model_dump() for item in items], "total": len(items)}


@router.get("/traceability/coverage", response_model=TraceabilityCoverageResponse)
async def get_traceability_coverage(
    project_id: UUID = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get project-level traceability coverage, gaps, and reference suggestions."""
    service = TraceabilityService(db)
    return await service.get_traceability_coverage(
        project_id=project_id,
        tenant_id=current_user.tenant_id,
    )


@router.post(
    "/traceability/coverage/accept-suggestions",
    response_model=TraceabilitySuggestionAcceptanceResponse,
)
async def accept_traceability_suggestions(
    data: TraceabilitySuggestionAcceptanceRequest | None = None,
    project_id: UUID = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create formal document references from project coverage suggestions."""
    service = TraceabilityService(db)
    return await service.accept_reference_suggestions(
        project_id=project_id,
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        suggestion_ids=data.suggestion_ids if data else None,
    )


@router.get("/traceability/impact")
async def get_impact_analysis(
    document_id: UUID = Query(..., description="Document ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Analyze impact of changes to a document.

    Args:
        document_id: Document UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Impact analysis with upstream and downstream documents
    """
    service = TraceabilityService(db)
    upstream, downstream = await service.get_impact_analysis(
        document_id=document_id,
        tenant_id=current_user.tenant_id,
    )
    return {
        "document_id": document_id,
        "upstream_documents": [item.model_dump() for item in upstream],
        "downstream_documents": [item.model_dump() for item in downstream],
    }


@router.get("/traceability/document/{document_id}")
async def get_document_traceability(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full traceability lineage for a specific document.

    Args:
        document_id: Document UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Document traceability with ancestors, descendants, and linked documents
    """
    service = TraceabilityService(db)
    result = await service.get_document_traceability(
        document_id=document_id,
        tenant_id=current_user.tenant_id,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Document not found")
    return result.model_dump()


@router.get("/traceability/matrix/full")
async def get_full_traceability_matrix(
    project_id: UUID = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate full hierarchical traceability matrix for a project.

    Args:
        project_id: Project UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Full traceability matrix grouped by document type
    """
    service = TraceabilityService(db)
    result = await service.generate_full_traceability_matrix(
        project_id=project_id,
        tenant_id=current_user.tenant_id,
    )
    return result.model_dump()


@router.get("/traceability/conflicts/{document_id}")
async def get_document_conflicts(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Find contradictions between document versions.

    Args:
        document_id: Document UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Conflict analysis with list of contradictions
    """
    service = TraceabilityService(db)
    result = await service.find_conflicts(
        document_id=document_id,
        tenant_id=current_user.tenant_id,
    )
    return result.model_dump()


@router.get("/traceability/impact/change-request/{change_request_id}")
async def get_change_request_impact(
    change_request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Analyze impact of a change request.

    Args:
        change_request_id: Change request UUID
        db: Database session
        current_user: Current authenticated user

    Returns:
        Impact analysis with upstream and downstream documents
    """
    service = TraceabilityService(db)
    upstream, downstream = await service.analyze_impact(
        change_request_id=change_request_id,
        tenant_id=current_user.tenant_id,
    )
    return {
        "change_request_id": change_request_id,
        "upstream_documents": [item.model_dump() for item in upstream],
        "downstream_documents": [item.model_dump() for item in downstream],
    }


@router.get("/impact-analyses/{analysis_id}", response_model=DocumentImpactAnalysisResponse)
async def get_persisted_impact_analysis(
    analysis_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a persisted document impact analysis with sync proposals."""
    service = TraceabilityService(db)
    analysis = await service.get_document_impact_analysis(
        analysis_id=analysis_id,
        tenant_id=current_user.tenant_id,
    )
    if not analysis:
        raise HTTPException(status_code=404, detail="Impact analysis not found")
    return DocumentImpactAnalysisResponse.model_validate(analysis)


@router.post("/sync-proposals/{proposal_id}/apply", response_model=DocumentSyncProposalResponse)
async def apply_sync_proposal(
    proposal_id: UUID,
    data: SyncProposalDecision = SyncProposalDecision(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply a human-reviewed sync proposal and create a new document version."""
    service = TraceabilityService(db)
    try:
        proposal = await service.apply_sync_proposal(
            proposal_id=proposal_id,
            tenant_id=current_user.tenant_id,
            decided_by=current_user.id,
            decision_note=data.decision_note,
            candidate_content=data.candidate_content,
        )
        return DocumentSyncProposalResponse.model_validate(proposal)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sync-proposals/{proposal_id}/reject", response_model=DocumentSyncProposalResponse)
async def reject_sync_proposal(
    proposal_id: UUID,
    data: SyncProposalDecision = SyncProposalDecision(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reject a sync proposal without changing the target document."""
    service = TraceabilityService(db)
    try:
        proposal = await service.reject_sync_proposal(
            proposal_id=proposal_id,
            tenant_id=current_user.tenant_id,
            decided_by=current_user.id,
            decision_note=data.decision_note,
        )
        return DocumentSyncProposalResponse.model_validate(proposal)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
