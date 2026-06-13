"""Audit Service

Records all security-relevant actions for compliance and monitoring.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.identity.models import AuditLog


class AuditService:
    """Service for recording and querying audit logs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_action(
        self,
        tenant_id: UUID | None,
        user_id: UUID | None,
        action: str,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        request: Request | None = None,
    ) -> AuditLog:
        """Record an audit log entry.

        Args:
            tenant_id: Tenant UUID (required for all tenant-scoped actions)
            user_id: User UUID who performed the action
            action: Action identifier (e.g., "login", "logout", "project.create")
            resource_type: Type of resource affected (e.g., "project", "user")
            resource_id: UUID of the affected resource
            metadata: Additional action-specific data
            request: FastAPI request object for IP/user agent extraction

        Returns:
            Created AuditLog entry
        """
        # Extract client info from request if provided
        ip_address: str | None = None
        user_agent: str | None = None

        if request:
            # Try to get real client IP (handles proxies)
            ip_address = request.headers.get(
                "X-Forwarded-For",
                request.headers.get("X-Real-IP", None),
            )
            if ip_address and "," in ip_address:
                # Take first IP in chain (original client)
                ip_address = ip_address.split(",")[0].strip()

            user_agent = request.headers.get("User-Agent", None)

        audit_log = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            extra_data=metadata,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        self.db.add(audit_log)
        await self.db.flush()
        await self.db.refresh(audit_log)
        return audit_log

    async def log_login(
        self,
        user_id: UUID,
        tenant_id: UUID | None,
        request: Request,
    ) -> AuditLog:
        """Record a login event.

        Args:
            user_id: User UUID who logged in
            tenant_id: Tenant UUID
            request: FastAPI request object

        Returns:
            Created AuditLog entry
        """
        return await self.log_action(
            tenant_id=tenant_id,
            user_id=user_id,
            action="auth.login",
            resource_type="user",
            resource_id=user_id,
            metadata={"event": "login_success"},
            request=request,
        )

    async def log_logout(
        self,
        user_id: UUID,
        tenant_id: UUID | None,
        request: Request,
    ) -> AuditLog:
        """Record a logout event.

        Args:
            user_id: User UUID who logged out
            tenant_id: Tenant UUID
            request: FastAPI request object

        Returns:
            Created AuditLog entry
        """
        return await self.log_action(
            tenant_id=tenant_id,
            user_id=user_id,
            action="auth.logout",
            resource_type="user",
            resource_id=user_id,
            metadata={"event": "logout"},
            request=request,
        )

    async def log_permission_change(
        self,
        user_id: UUID,
        tenant_id: UUID | None,
        action: str,
        role_id: UUID,
        request: Request,
    ) -> AuditLog:
        """Record a permission/role change event.

        Args:
            user_id: User UUID performing the change
            tenant_id: Tenant UUID
            action: Action identifier (role.assign, role.revoke, etc.)
            role_id: Role UUID being modified
            request: FastAPI request object

        Returns:
            Created AuditLog entry
        """
        return await self.log_action(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type="role",
            resource_id=role_id,
            request=request,
        )

    async def log_sensitive_access(
        self,
        user_id: UUID,
        tenant_id: UUID | None,
        resource_type: str,
        resource_id: UUID,
        action: str,
        request: Request,
    ) -> AuditLog:
        """Record a sensitive data access event.

        Args:
            user_id: User UUID accessing the data
            tenant_id: Tenant UUID
            resource_type: Type of resource being accessed
            resource_id: UUID of the resource
            action: Action identifier (e.g., "document.read_private")
            request: FastAPI request object

        Returns:
            Created AuditLog entry
        """
        return await self.log_action(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata={"sensitive": True},
            request=request,
        )

    async def query_logs(
        self,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AuditLog], int]:
        """Query audit logs with optional filters.

        Args:
            tenant_id: Filter by tenant (required for non-admin queries)
            user_id: Filter by user
            action: Filter by action
            resource_type: Filter by resource type
            resource_id: Filter by resource ID
            start_date: Filter by start date
            end_date: Filter by end date
            page: Page number (1-indexed)
            page_size: Number of records per page

        Returns:
            Tuple of (list of AuditLogs, total count)
        """
        # Build base query
        query = select(AuditLog)
        count_query = select(func.count(AuditLog.id))

        # Apply filters
        if tenant_id is not None:
            query = query.where(AuditLog.tenant_id == tenant_id)
            count_query = count_query.where(AuditLog.tenant_id == tenant_id)

        if user_id is not None:
            query = query.where(AuditLog.user_id == user_id)
            count_query = count_query.where(AuditLog.user_id == user_id)

        if action is not None:
            query = query.where(AuditLog.action == action)
            count_query = count_query.where(AuditLog.action == action)

        if resource_type is not None:
            query = query.where(AuditLog.resource_type == resource_type)
            count_query = count_query.where(AuditLog.resource_type == resource_type)

        if resource_id is not None:
            query = query.where(AuditLog.resource_id == resource_id)
            count_query = count_query.where(AuditLog.resource_id == resource_id)

        if start_date is not None:
            query = query.where(AuditLog.created_at >= start_date)
            count_query = count_query.where(AuditLog.created_at >= start_date)

        if end_date is not None:
            query = query.where(AuditLog.created_at <= end_date)
            count_query = count_query.where(AuditLog.created_at <= end_date)

        # Get total count
        count_result = await self.db.execute(count_query)
        total = count_result.scalar_one()

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size).order_by(AuditLog.created_at.desc())

        # Get results
        result = await self.db.execute(query)
        logs = list(result.scalars().all())

        return logs, total


def create_audit_service(db: AsyncSession) -> AuditService:
    """Factory function to create AuditService instance.

    Args:
        db: Async SQLAlchemy session

    Returns:
        AuditService instance
    """
    return AuditService(db)