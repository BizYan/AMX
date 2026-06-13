"""Collaboration Domain API Router

Endpoints for pessimistic locking, document snapshots, and comments.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.security import decode_token
from app.models.identity import User
from app.domains.collaboration.models import (
    CollaborationLock,
    DocumentSnapshot,
    DocumentComment,
    CommentThread,
    LockType,
    SnapshotType,
    ThreadType,
)
from app.domains.collaboration.schemas import (
    CollaborationLockAcquire,
    CollaborationLockRelease,
    CollaborationLockResponse,
    DocumentSnapshotCreate,
    DocumentSnapshotResponse,
    DocumentCommentCreate,
    DocumentCommentUpdate,
    DocumentCommentResponse,
    CommentThreadCreate,
    CommentThreadResponse,
    CollaborationAcceptanceCommandCenterResponse,
    CollaborationReviewHubResponse,
    CollaborationReviewItemResponse,
    CollaborationWorkItemBoardResponse,
    CollaborationWorkItemCreate,
    CollaborationWorkItemResponse,
    CollaborationWorkItemUpdate,
    LockConflictError,
    LockNotFoundError,
    LockExpiredError,
)
from app.domains.collaboration.work_item_service import CollaborationWorkItemService
from app.services.collaboration_service import (
    CollaborationService,
    LockConflictException,
    LockNotFoundException,
    LockExpiredException,
)
from app.services.audit_service import AuditService, create_audit_service
from app.domains.notifications.service import UserNotificationService


router = APIRouter(prefix="/collaboration", tags=["collaboration"])

REVIEW_ACTIONS = {
    "assign-me",
    "mark-read",
    "pass-acceptance",
    "return-revision",
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


def get_collaboration_service(db: AsyncSession = Depends(get_db)) -> CollaborationService:
    """Dependency to get CollaborationService.

    Args:
        db: Database session

    Returns:
        CollaborationService instance
    """
    audit_service = create_audit_service(db)
    return CollaborationService(db, audit_service)


@router.get("/review-hub", response_model=CollaborationReviewHubResponse)
async def get_review_hub(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the cross-project collaboration review command center."""
    service = get_collaboration_service(db)
    return await service.build_review_hub(
        tenant_id=current_user.tenant_id,
        current_user_id=current_user.id,
    )


@router.get("/acceptance-command-center", response_model=CollaborationAcceptanceCommandCenterResponse)
async def get_acceptance_command_center(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return acceptance release gate, risks, and priority actions."""
    service = get_collaboration_service(db)
    return await service.build_acceptance_command_center(
        tenant_id=current_user.tenant_id,
        current_user_id=current_user.id,
    )


@router.post("/review-items/{review_id}/{action}", response_model=CollaborationReviewItemResponse)
async def perform_review_action(
    review_id: UUID,
    action: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply a review queue action to the underlying document."""
    if action not in REVIEW_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported review action '{action}'")

    service = get_collaboration_service(db)
    try:
        return await service.perform_review_action(
            tenant_id=current_user.tenant_id,
            document_id=review_id,
            user_id=current_user.id,
            action=action,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _work_item_error(error: Exception) -> HTTPException:
    if isinstance(error, PermissionError):
        return HTTPException(status_code=403, detail=str(error))
    if "not found" in str(error).lower():
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=400, detail=str(error))


async def _audit_work_item(
    db: AsyncSession,
    current_user: User,
    action: str,
    work_item_id: UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    await AuditService(db).log_action(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action=f"collaboration.work_item.{action}",
        resource_type="collaboration_work_item",
        resource_id=work_item_id,
        metadata=metadata or {},
    )


@router.get("/work-items", response_model=CollaborationWorkItemBoardResponse)
async def list_work_items(
    status: str | None = Query(None),
    priority: str | None = Query(None),
    assignment: str = Query("all", pattern="^(all|mine|unassigned)$"),
    project_id: UUID | None = Query(None),
    overdue_only: bool = Query(False),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CollaborationWorkItemService(db).list_work_items(
        current_user.tenant_id,
        current_user.id,
        status=status,
        priority=priority,
        assignment=assignment,
        project_id=project_id,
        overdue_only=overdue_only,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.post("/work-items", response_model=CollaborationWorkItemResponse, status_code=201)
async def create_work_item(
    data: CollaborationWorkItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        item = await CollaborationWorkItemService(db).create_work_item(
            tenant_id=current_user.tenant_id,
            created_by=current_user.id,
            **data.model_dump(),
        )
        await _audit_work_item(db, current_user, "create", item.id)
        return item
    except (ValueError, PermissionError) as error:
        raise _work_item_error(error)


@router.patch("/work-items/{work_item_id}", response_model=CollaborationWorkItemResponse)
async def update_work_item(
    work_item_id: UUID,
    data: CollaborationWorkItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        changes = data.model_dump(exclude_unset=True)
        item = await CollaborationWorkItemService(db).update_work_item(
            work_item_id,
            current_user.tenant_id,
            current_user.id,
            changes,
        )
        await _audit_work_item(db, current_user, "update", item.id, {"fields": sorted(changes)})
        return item
    except (ValueError, PermissionError) as error:
        raise _work_item_error(error)


async def _transition_work_item(
    transition: str,
    work_item_id: UUID,
    db: AsyncSession,
    current_user: User,
):
    service = CollaborationWorkItemService(db)
    try:
        item = await getattr(service, transition)(work_item_id, current_user.tenant_id, current_user.id)
        await _audit_work_item(db, current_user, transition, item.id)
        return item
    except (ValueError, PermissionError) as error:
        raise _work_item_error(error)


@router.post("/work-items/{work_item_id}/claim", response_model=CollaborationWorkItemResponse)
async def claim_work_item(
    work_item_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _transition_work_item("claim", work_item_id, db, current_user)


@router.post("/work-items/{work_item_id}/complete", response_model=CollaborationWorkItemResponse)
async def complete_work_item(
    work_item_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _transition_work_item("complete", work_item_id, db, current_user)


@router.post("/work-items/{work_item_id}/reopen", response_model=CollaborationWorkItemResponse)
async def reopen_work_item(
    work_item_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _transition_work_item("reopen", work_item_id, db, current_user)


# Lock Endpoints
@router.post("/locks", response_model=CollaborationLockResponse, status_code=201)
async def acquire_lock(
    data: CollaborationLockAcquire,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Acquire a lock on a resource.

    Args:
        data: Lock acquisition data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created lock

    Raises:
        HTTPException: If lock conflict or invalid parameters
    """
    service = get_collaboration_service(db)

    # Validate lock type
    if data.lock_type not in [LockType.EXCLUSIVE.value, LockType.SHARED.value]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid lock type. Must be '{LockType.EXCLUSIVE.value}' or '{LockType.SHARED.value}'",
        )

    try:
        lock = await service.acquire_lock(
            tenant_id=current_user.tenant_id,
            resource_type=data.resource_type,
            resource_id=data.resource_id,
            user_id=current_user.id,
            lock_type=data.lock_type,
            ttl_seconds=data.ttl_seconds,
        )
        return CollaborationLockResponse.model_validate(lock)
    except LockConflictException as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "lock_conflict",
                "message": e.message,
                "existing_lock": (
                    CollaborationLockResponse.model_validate(e.existing_lock).model_dump()
                    if e.existing_lock else None
                ),
            },
        )


@router.delete("/locks/{lock_id}", status_code=204)
async def release_lock(
    lock_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Release a lock.

    Args:
        lock_id: UUID of the lock to release
        db: Database session
        current_user: Current authenticated user

    Raises:
        HTTPException: If lock not found or not owned by user
    """
    service = get_collaboration_service(db)

    try:
        await service.release_lock(
            lock_id=lock_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
        )
    except LockNotFoundException:
        raise HTTPException(status_code=404, detail="Lock not found or not owned by user")


@router.post("/locks/{lock_id}/refresh", response_model=CollaborationLockResponse)
async def refresh_lock(
    lock_id: UUID,
    ttl_seconds: int = Query(default=300, ge=10, le=3600, description="New TTL in seconds"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Refresh a lock TTL.

    Args:
        lock_id: UUID of the lock
        ttl_seconds: New TTL in seconds
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated lock

    Raises:
        HTTPException: If lock not found, expired, or not owned by user
    """
    service = get_collaboration_service(db)

    try:
        lock = await service.refresh_lock(
            lock_id=lock_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            ttl_seconds=ttl_seconds,
        )
        return CollaborationLockResponse.model_validate(lock)
    except LockNotFoundException:
        raise HTTPException(status_code=404, detail="Lock not found or not owned by user")
    except LockExpiredException:
        raise HTTPException(status_code=410, detail="Lock has expired")


@router.get("/locks", response_model=list[CollaborationLockResponse])
async def get_active_locks(
    resource_type: str = Query(..., description="Type of resource"),
    resource_id: UUID = Query(..., description="UUID of the resource"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get active locks on a resource.

    Args:
        resource_type: Type of resource
        resource_id: UUID of the resource
        db: Database session
        current_user: Current authenticated user

    Returns:
        List of active locks
    """
    service = get_collaboration_service(db)

    locks = await service.get_active_locks(
        tenant_id=current_user.tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    return [CollaborationLockResponse.model_validate(lock) for lock in locks]


# Snapshot Endpoints
@router.post("/documents/{document_id}/snapshots", response_model=DocumentSnapshotResponse, status_code=201)
async def create_snapshot(
    document_id: UUID,
    data: DocumentSnapshotCreate = DocumentSnapshotCreate(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a document snapshot.

    Args:
        document_id: UUID of the document
        data: Snapshot creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created snapshot

    Raises:
        HTTPException: If document not found
    """
    service = get_collaboration_service(db)

    # Validate snapshot type
    if data.snapshot_type not in [SnapshotType.AUTO.value, SnapshotType.MANUAL.value]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid snapshot type. Must be '{SnapshotType.AUTO.value}' or '{SnapshotType.MANUAL.value}'",
        )

    try:
        snapshot = await service.create_snapshot(
            tenant_id=current_user.tenant_id,
            document_id=document_id,
            user_id=current_user.id,
            snapshot_type=data.snapshot_type,
            draft_data=data.model_dump(exclude_none=True, exclude={"snapshot_type"}),
        )
        return DocumentSnapshotResponse.model_validate(snapshot)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/documents/{document_id}/snapshots", response_model=list[DocumentSnapshotResponse])
async def get_snapshots(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all snapshots for a document.

    Args:
        document_id: UUID of the document
        db: Database session
        current_user: Current authenticated user

    Returns:
        List of snapshots
    """
    service = get_collaboration_service(db)

    snapshots = await service.get_snapshots(
        tenant_id=current_user.tenant_id,
        document_id=document_id,
    )
    return [DocumentSnapshotResponse.model_validate(s) for s in snapshots]


@router.post("/snapshots/{snapshot_id}/restore", response_model=DocumentSnapshotResponse)
async def restore_snapshot(
    snapshot_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Restore a document from a snapshot.

    Args:
        snapshot_id: UUID of the snapshot
        db: Database session
        current_user: Current authenticated user

    Returns:
        Restored snapshot

    Raises:
        HTTPException: If snapshot or document not found
    """
    service = get_collaboration_service(db)

    try:
        snapshot = await service.restore_snapshot(
            snapshot_id=snapshot_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
        )
        return DocumentSnapshotResponse.model_validate(snapshot)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# Comment Endpoints
@router.post("/documents/{document_id}/comments", response_model=DocumentCommentResponse, status_code=201)
async def create_comment(
    document_id: UUID,
    data: DocumentCommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a document comment.

    Args:
        document_id: UUID of the document
        data: Comment creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created comment
    """
    service = get_collaboration_service(db)

    try:
        comment = await service.create_comment(
            tenant_id=current_user.tenant_id,
            document_id=document_id,
            entity_id=data.entity_id,
            user_id=current_user.id,
            content=data.content,
            anchor=data.anchor,
            parent_id=data.parent_comment_id,
        )
        await UserNotificationService(db).notify_document_comment(
            tenant_id=current_user.tenant_id,
            document_id=document_id,
            comment_id=comment.id,
            actor_id=current_user.id,
            parent_comment_id=comment.parent_comment_id,
        )
        return DocumentCommentResponse.model_validate(comment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/comments/{comment_id}", response_model=DocumentCommentResponse)
async def update_comment(
    comment_id: UUID,
    data: DocumentCommentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a document comment.

    Args:
        comment_id: UUID of the comment
        data: Comment update data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated comment

    Raises:
        HTTPException: If comment not found or user not authorized
    """
    service = get_collaboration_service(db)

    try:
        comment = await service.update_comment(
            comment_id=comment_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            content=data.content,
        )
        return DocumentCommentResponse.model_validate(comment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/comments/{comment_id}/resolve", response_model=DocumentCommentResponse)
async def resolve_comment(
    comment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resolve a document comment.

    Args:
        comment_id: UUID of the comment
        db: Database session
        current_user: Current authenticated user

    Returns:
        Updated comment

    Raises:
        HTTPException: If comment not found
    """
    service = get_collaboration_service(db)

    try:
        comment = await service.resolve_comment(
            comment_id=comment_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
        )
        return DocumentCommentResponse.model_validate(comment)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a document comment (soft delete).

    Args:
        comment_id: UUID of the comment
        db: Database session
        current_user: Current authenticated user

    Raises:
        HTTPException: If comment not found or user not authorized
    """
    service = get_collaboration_service(db)

    try:
        await service.delete_comment(
            comment_id=comment_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/documents/{document_id}/comments", response_model=list[DocumentCommentResponse])
async def get_comments(
    document_id: UUID,
    entity_id: UUID | None = Query(None, description="Filter by entity ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get comments for a document or entity.

    Args:
        document_id: UUID of the document
        entity_id: Optional UUID of the entity
        db: Database session
        current_user: Current authenticated user

    Returns:
        List of comments
    """
    service = get_collaboration_service(db)

    comments = await service.get_comments(
        tenant_id=current_user.tenant_id,
        document_id=document_id,
        entity_id=entity_id,
    )
    return [DocumentCommentResponse.model_validate(c) for c in comments]


# Thread Endpoints
@router.post("/documents/{document_id}/threads", response_model=CommentThreadResponse, status_code=201)
async def create_thread(
    document_id: UUID,
    data: CommentThreadCreate = CommentThreadCreate(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a comment thread.

    Args:
        document_id: UUID of the document
        data: Thread creation data
        db: Database session
        current_user: Current authenticated user

    Returns:
        Created thread
    """
    service = get_collaboration_service(db)

    # Validate thread type
    if data.thread_type and data.thread_type not in [ThreadType.GENERAL.value, ThreadType.ENTITY.value]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid thread type. Must be '{ThreadType.GENERAL.value}' or '{ThreadType.ENTITY.value}'",
        )

    thread = await service.create_thread(
        tenant_id=current_user.tenant_id,
        document_id=document_id,
        thread_type=data.thread_type or ThreadType.GENERAL.value,
    )
    return CommentThreadResponse.model_validate(thread)


@router.get("/documents/{document_id}/threads", response_model=list[CommentThreadResponse])
async def get_threads(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all threads for a document.

    Args:
        document_id: UUID of the document
        db: Database session
        current_user: Current authenticated user

    Returns:
        List of threads
    """
    service = get_collaboration_service(db)

    threads = await service.get_threads(
        tenant_id=current_user.tenant_id,
        document_id=document_id,
    )
    return [CommentThreadResponse.model_validate(t) for t in threads]
