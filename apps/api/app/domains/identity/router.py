"""Identity Domain API Router

FastAPI endpoints for authentication, tenant, user, role, policy, and audit management.
"""

from typing import Annotated, Any
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import NO_VALUE

from app.db.session import get_db
from app.domains.identity.models import AuditLog, FieldPermission, Policy, Role, Tenant, User
from app.domains.identity.schemas import (
    AuditLogResponse,
    AssignRoleRequest,
    AuthMeResponse,
    FieldPermissionCreate,
    FieldPermissionResponse,
    FieldPermissionUpdate,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    AccountSecurityResponse,
    AccountDeactivateRequest,
    PaginatedResponse,
    PermissionDiagnosticCheck,
    PermissionDiagnosticFieldControl,
    PermissionDiagnosticPolicyEvidence,
    PermissionCommandCenterPriorityAction,
    PermissionCommandCenterReleaseGate,
    PermissionCommandCenterResponse,
    PermissionCommandCenterRiskItem,
    PermissionDiagnosticsResponse,
    PermissionSimulationRequest,
    PermissionSimulationResponse,
    PermissionSimulationRoleEvidence,
    PolicyCreate,
    PolicyResponse,
    PolicyUpdate,
    RoleResponse,
    RoleCreate,
    RoleUpdate,
    TenantApiKeyCreate,
    TenantApiKeyCreateResponse,
    TenantApiKeyResponse,
    TenantCreate,
    TenantResponse,
    TenantUpdate,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.domains.identity.service import (
    AuthService,
    FieldPermissionService,
    PolicyService,
    RoleService,
    TenantApiKeyService,
    TenantService,
    UserService,
)
from app.services.audit_service import AuditService
from app.services.permission_evaluator import PermissionEvaluator, create_permission_evaluator

router = APIRouter()
security = HTTPBearer()


def _role_response(role: Role) -> RoleResponse:
    """Normalize nullable DB fields before exposing roles in user responses."""
    return RoleResponse(
        id=role.id,
        tenant_id=role.tenant_id,
        name=role.name,
        description=role.description,
        permissions=role.permissions or {},
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


def _loaded_roles(target_user: User) -> list[Role] | None:
    loaded_value = inspect(target_user).attrs.roles.loaded_value
    if loaded_value is NO_VALUE:
        return None
    return [
        assignment.role
        for assignment in loaded_value
        if getattr(assignment, "role", None) is not None
    ]


async def _user_response_with_roles(db: AsyncSession, target_user: User) -> UserResponse:
    roles = _loaded_roles(target_user)
    if roles is None:
        roles = await RoleService(db).get_user_roles(target_user.id)

    return UserResponse.model_validate(target_user).model_copy(
        update={"roles": [_role_response(role) for role in roles]}
    )


# ============================================================================
# Dependency Injection
# ============================================================================

async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Dependency to get current authenticated user from JWT token.

    Args:
        credentials: HTTP Bearer token credentials
        db: Database session

    Returns:
        User: Current authenticated user

    Raises:
        HTTPException: 401 if not authenticated
    """
    auth_service = AuthService(db)
    token = credentials.credentials

    user = await auth_service.get_current_user(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return user


async def get_current_user_optional(
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
) -> User | None:
    """Optional dependency to get current user (returns None if not authenticated)."""
    if not credentials:
        return None

    auth_service = AuthService(db)
    return await auth_service.get_current_user(credentials.credentials)


async def require_admin(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Dependency to require admin user.

    Args:
        db: Database session
        user: Current authenticated user

    Returns:
        User: The admin user

    Raises:
        HTTPException: 403 if not admin
    """
    if not await has_admin_permission(db, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    return user


async def has_admin_permission(db: AsyncSession, user: User) -> bool:
    """Return whether the user has unrestricted administrator permissions."""
    roles = await RoleService(db).get_user_roles(user.id)
    return any(
        role.permissions and (role.permissions.get("*") or role.permissions.get("admin"))
        for role in roles
    )


async def require_team_permission(
    user: User,
    db: AsyncSession,
    action: str,
) -> None:
    """Require team permission for tenant member, role, policy, and field access."""
    evaluator = create_permission_evaluator(db)
    if await evaluator.has_permission(user, action, "team", user.tenant_id):
        return
    if action == "read" and await evaluator.has_permission(user, "manage", "team", user.tenant_id):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Team permission required",
    )


def get_audit_service(db: AsyncSession) -> AuditService:
    """Factory for AuditService."""
    return AuditService(db)


def _policy_applies_to_simulation(policy: Policy, action: str, resource: str) -> bool:
    """Return whether a policy is relevant to one permission simulation."""
    action_matches = action in policy.actions or "*" in policy.actions
    if not action_matches:
        return False

    resource_root = resource.split(":", 1)[0]
    for policy_resource in policy.resources:
        policy_root = policy_resource.rstrip("*").rstrip(":").split(":", 1)[0]
        if policy_resource == resource or policy_resource == "*" or policy_root == resource_root:
            return True
        if policy_resource.endswith("*") and resource.startswith(policy_resource[:-1]):
            return True
        if resource.endswith("*") and policy_resource.startswith(resource[:-1]):
            return True

    return False


# ============================================================================
# Auth Endpoints
# ============================================================================


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    request: Request,
    credentials: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoginResponse:
    """Authenticate user and return access token.

    Args:
        credentials: Login credentials (email, password)
        db: Database session

    Returns:
        LoginResponse: Access token and metadata

    Raises:
        HTTPException: 401 if credentials invalid
    """
    auth_service = AuthService(db)
    audit_service = AuditService(db)

    try:
        user, access_token = await auth_service.login(credentials)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )

    # Log successful login
    await audit_service.log_login(
        user_id=user.id,
        tenant_id=user.tenant_id,
        request=request,
    )

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=auth_service.get_token_expiry(),
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Logout current user by blacklisting their token.

    Args:
        user: Current authenticated user
        credentials: HTTP Bearer token
        db: Database session
    """
    auth_service = AuthService(db)
    audit_service = AuditService(db)

    # Blacklist the token
    await auth_service.logout(credentials.credentials)

    # Log logout
    await audit_service.log_logout(
        user_id=user.id,
        tenant_id=user.tenant_id,
        request=request,
    )


@router.get("/auth/me", response_model=AuthMeResponse)
async def get_me(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthMeResponse:
    """Get current authenticated user info.

    Args:
        user: Current authenticated user
        db: Database session

    Returns:
        AuthMeResponse: User information with roles
    """
    role_service = RoleService(db)
    roles = await role_service.get_user_roles(user.id)

    return AuthMeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        tenant_id=user.tenant_id,
        is_active=user.is_active,
        roles=[RoleResponse.model_validate(r) for r in roles],
    )


@router.get("/auth/security", response_model=AccountSecurityResponse)
async def get_account_security(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccountSecurityResponse:
    """Return the current user's account-security state and recent events."""
    events, _ = await AuditService(db).query_logs(
        tenant_id=user.tenant_id,
        user_id=user.id,
        resource_type="user",
        page_size=10,
    )
    return AccountSecurityResponse(
        security_version=user.security_version,
        password_changed_at=user.password_changed_at,
        last_login_at=user.last_login_at,
        active=user.is_active,
        recent_events=[AuditLogResponse.model_validate(event) for event in events],
    )


@router.post("/auth/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    data: PasswordChangeRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Change the current password and revoke all issued sessions."""
    try:
        await AuthService(db).change_password(user, data.current_password, data.new_password)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    await AuditService(db).log_action(
        user.tenant_id,
        user.id,
        "auth.password_changed",
        resource_type="user",
        resource_id=user.id,
        metadata={"sessions_revoked": True},
        request=request,
    )


@router.post("/auth/sessions/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_sessions(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Revoke every session for the current user, including this one."""
    await AuthService(db).revoke_all_sessions(user)
    await AuditService(db).log_action(
        user.tenant_id,
        user.id,
        "auth.sessions_revoked",
        resource_type="user",
        resource_id=user.id,
        request=request,
    )


@router.post("/auth/deactivate", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_account(
    data: AccountDeactivateRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Deactivate the current account and invalidate every session."""
    try:
        await AuthService(db).deactivate_account(user, data.current_password)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    await AuditService(db).log_action(
        user.tenant_id,
        user.id,
        "auth.account_deactivated",
        resource_type="user",
        resource_id=user.id,
        request=request,
    )


# ============================================================================
# Tenant Endpoints
# ============================================================================


@router.get("/tenants", response_model=PaginatedResponse[TenantResponse])
async def list_tenants(
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> PaginatedResponse[TenantResponse]:
    """List all tenants (admin only).

    Args:
        admin: Admin user
        db: Database session
        skip: Number of records to skip
        limit: Maximum number of records

    Returns:
        PaginatedResponse of tenants
    """
    service = TenantService(db)
    tenants, total = await service.list_tenants(skip=skip, limit=limit)

    return PaginatedResponse(
        items=[TenantResponse.model_validate(t) for t in tenants],
        total=total,
        page=skip // limit + 1,
        page_size=limit,
        has_more=(skip + len(tenants)) < total,
    )


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    data: TenantCreate,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TenantResponse:
    """Create a new tenant.

    Args:
        data: Tenant creation data
        admin: Admin user
        db: Database session

    Returns:
        Created tenant
    """
    service = TenantService(db)
    tenant = await service.create_tenant(data)
    return TenantResponse.model_validate(tenant)


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TenantResponse:
    """Get tenant by ID.

    Args:
        tenant_id: Tenant UUID
        user: Current authenticated user
        db: Database session

    Returns:
        Tenant details

    Raises:
        HTTPException: 404 if not found, 403 if no access
    """
    service = TenantService(db)
    tenant = await service.get_tenant(tenant_id)

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    # Check tenant access
    evaluator = create_permission_evaluator(db)
    if not await evaluator.check_tenant_access(user, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this tenant",
        )

    return TenantResponse.model_validate(tenant)


@router.patch("/tenants/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: UUID,
    data: TenantUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TenantResponse:
    """Update a tenant.

    Args:
        tenant_id: Tenant UUID
        data: Update data
        user: Current authenticated user
        db: Database session

    Returns:
        Updated tenant

    Raises:
        HTTPException: 404 if not found, 403 if no access
    """
    service = TenantService(db)
    tenant = await service.get_tenant(tenant_id)

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    # Check tenant access
    evaluator = create_permission_evaluator(db)
    if not await evaluator.check_tenant_access(user, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this tenant",
        )

    updated = await service.update_tenant(tenant_id, data)
    return TenantResponse.model_validate(updated)


# ============================================================================
# User Endpoints
# ============================================================================


@router.get("/users", response_model=PaginatedResponse[UserResponse])
async def list_users(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> PaginatedResponse[UserResponse]:
    """List users for the current tenant.

    Args:
        user: Current authenticated user
        db: Database session
        skip: Number of records to skip
        limit: Maximum number of records

    Returns:
        PaginatedResponse of users
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )
    await require_team_permission(user, db, "read")

    service = UserService(db)
    users, total = await service.list_users(
        tenant_id=user.tenant_id,
        skip=skip,
        limit=limit,
    )

    return PaginatedResponse(
        items=[await _user_response_with_roles(db, tenant_user) for tenant_user in users],
        total=total,
        page=skip // limit + 1,
        page_size=limit,
        has_more=(skip + len(users)) < total,
    )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> UserResponse:
    """Create a new user.

    Args:
        data: User creation data
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Returns:
        Created user

    Raises:
        HTTPException: 400 if tenant_id mismatch
    """
    audit_service = AuditService(db)
    await require_team_permission(user, db, "manage")

    # Set tenant_id to current user's tenant if not provided
    if data.tenant_id is None:
        if not user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create user without tenant",
            )
        data.tenant_id = user.tenant_id
    elif user.tenant_id and data.tenant_id != user.tenant_id:
        # Check if current user is admin and can create users in other tenants
        evaluator = create_permission_evaluator(db)
        if not await evaluator.check_tenant_access(user, data.tenant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot create user in this tenant",
            )

    service = UserService(db)
    new_user = await service.create_user(data)

    # Audit log
    await audit_service.log_action(
        tenant_id=new_user.tenant_id,
        user_id=user.id,
        action="user.create",
        resource_type="user",
        resource_id=new_user.id,
        request=request,
    )

    return await _user_response_with_roles(db, new_user)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    """Get user by ID.

    Args:
        user_id: User UUID
        user: Current authenticated user
        db: Database session

    Returns:
        User details

    Raises:
        HTTPException: 404 if not found, 403 if no access
    """
    await require_team_permission(user, db, "read")
    service = UserService(db)
    target_user = await service.get_user(user_id, tenant_id=user.tenant_id)

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return await _user_response_with_roles(db, target_user)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    data: UserUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> UserResponse:
    """Update a user.

    Args:
        user_id: User UUID
        data: Update data
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Returns:
        Updated user

    Raises:
        HTTPException: 404 if not found, 403 if no access
    """
    await require_team_permission(user, db, "manage")
    service = UserService(db)
    target_user = await service.get_user(user_id, tenant_id=user.tenant_id)

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    updated = await service.update_user(user_id, data, tenant_id=user.tenant_id)

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="user.update",
        resource_type="user",
        resource_id=user_id,
        request=request,
    )

    return await _user_response_with_roles(db, updated)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> None:
    """Soft delete a user.

    Args:
        user_id: User UUID
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Raises:
        HTTPException: 404 if not found, 403 if no access
    """
    await require_team_permission(user, db, "manage")
    service = UserService(db)
    target_user = await service.get_user(user_id, tenant_id=user.tenant_id)

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    await service.delete_user(user_id, tenant_id=user.tenant_id)

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="user.delete",
        resource_type="user",
        resource_id=user_id,
        request=request,
    )


# ============================================================================
# Role Endpoints
# ============================================================================


@router.get("/roles", response_model=PaginatedResponse[RoleResponse])
async def list_roles(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> PaginatedResponse[RoleResponse]:
    """List roles for the current tenant.

    Args:
        user: Current authenticated user
        db: Database session
        skip: Number of records to skip
        limit: Maximum number of records

    Returns:
        PaginatedResponse of roles
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )
    await require_team_permission(user, db, "read")

    service = RoleService(db)
    roles, total = await service.list_roles(
        tenant_id=user.tenant_id,
        skip=skip,
        limit=limit,
    )

    return PaginatedResponse(
        items=[RoleResponse.model_validate(r) for r in roles],
        total=total,
        page=skip // limit + 1,
        page_size=limit,
        has_more=(skip + len(roles)) < total,
    )


@router.post("/roles", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    data: RoleCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> RoleResponse:
    """Create a new role.

    Args:
        data: Role creation data
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Returns:
        Created role
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )
    await require_team_permission(user, db, "manage")

    service = RoleService(db)
    role = await service.create_role(data, tenant_id=user.tenant_id)

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="role.create",
        resource_type="role",
        resource_id=role.id,
        request=request,
    )

    return RoleResponse.model_validate(role)


@router.get("/roles/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoleResponse:
    """Get role by ID.

    Args:
        role_id: Role UUID
        user: Current authenticated user
        db: Database session

    Returns:
        Role details

    Raises:
        HTTPException: 404 if not found
    """
    await require_team_permission(user, db, "read")
    service = RoleService(db)
    role = await service.get_role(role_id, tenant_id=user.tenant_id)

    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    return RoleResponse.model_validate(role)


@router.patch("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: UUID,
    data: RoleUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> RoleResponse:
    """Update a role.

    Args:
        role_id: Role UUID
        data: Update data
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Returns:
        Updated role

    Raises:
        HTTPException: 404 if not found
    """
    await require_team_permission(user, db, "manage")
    service = RoleService(db)
    role = await service.get_role(role_id, tenant_id=user.tenant_id)

    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    updated = await service.update_role(role_id, data, tenant_id=user.tenant_id)

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="role.update",
        resource_type="role",
        resource_id=role_id,
        request=request,
    )

    return RoleResponse.model_validate(updated)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> None:
    """Delete an unassigned role in the current tenant."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )
    await require_team_permission(user, db, "manage")

    service = RoleService(db)
    role = await service.get_role(role_id, tenant_id=user.tenant_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    deleted = await service.delete_role(role_id, tenant_id=user.tenant_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Role is assigned to users and cannot be deleted",
        )

    audit_service = AuditService(db)
    await audit_service.log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="role.delete",
        resource_type="role",
        resource_id=role_id,
        request=request,
    )


@router.post("/roles/{role_id}/assign", status_code=status.HTTP_204_NO_CONTENT)
async def assign_role_to_user(
    role_id: UUID,
    data: AssignRoleRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> None:
    """Assign a role to a user.

    Args:
        role_id: Role UUID
        data: Assignment data with user_id
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Raises:
        HTTPException: 404 if role or user not found, 403 if no permission
    """
    service = RoleService(db)

    # Verify role exists
    role = await service.get_role(role_id, tenant_id=user.tenant_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    # Check permission
    await require_team_permission(user, db, "manage")

    success = await service.assign_role_to_user(data.user_id, role_id, user.tenant_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log_permission_change(
        user_id=user.id,
        tenant_id=user.tenant_id,
        action="role.assign",
        role_id=role_id,
        request=request,
    )


@router.delete("/roles/{role_id}/assign/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_role_from_user(
    role_id: UUID,
    target_user_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> None:
    """Revoke a tenant-owned role from a tenant-owned user."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )

    service = RoleService(db)
    role = await service.get_role(role_id, tenant_id=user.tenant_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    await require_team_permission(user, db, "manage")

    success = await service.revoke_role_from_user(target_user_id, role_id, user.tenant_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    audit_service = AuditService(db)
    await audit_service.log_permission_change(
        user_id=user.id,
        tenant_id=user.tenant_id,
        action="role.revoke",
        role_id=role_id,
        request=request,
    )


# ============================================================================
# Policy Endpoints
# ============================================================================


@router.get("/policies", response_model=PaginatedResponse[PolicyResponse])
async def list_policies(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> PaginatedResponse[PolicyResponse]:
    """List policies for the current tenant.

    Args:
        user: Current authenticated user
        db: Database session
        skip: Number of records to skip
        limit: Maximum number of records

    Returns:
        PaginatedResponse of policies
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )
    await require_team_permission(user, db, "read")

    service = PolicyService(db)
    policies, total = await service.list_policies(
        tenant_id=user.tenant_id,
        skip=skip,
        limit=limit,
    )

    return PaginatedResponse(
        items=[PolicyResponse.model_validate(p) for p in policies],
        total=total,
        page=skip // limit + 1,
        page_size=limit,
        has_more=(skip + len(policies)) < total,
    )


@router.post("/policies", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_policy(
    data: PolicyCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> PolicyResponse:
    """Create a new policy.

    Args:
        data: Policy creation data
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Returns:
        Created policy
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )
    await require_team_permission(user, db, "manage")

    service = PolicyService(db)
    policy = await service.create_policy(data, tenant_id=user.tenant_id)

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="policy.create",
        resource_type="policy",
        resource_id=policy.id,
        request=request,
    )

    return PolicyResponse.model_validate(policy)


@router.get("/policies/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PolicyResponse:
    """Get a policy by ID in the current tenant."""
    await require_team_permission(user, db, "read")
    service = PolicyService(db)
    policy = await service.get_policy(policy_id, tenant_id=user.tenant_id)

    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy not found",
        )

    return PolicyResponse.model_validate(policy)


@router.patch("/policies/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: UUID,
    data: PolicyUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> PolicyResponse:
    """Update a policy in the current tenant and write an audit record."""
    await require_team_permission(user, db, "manage")
    service = PolicyService(db)
    policy = await service.get_policy(policy_id, tenant_id=user.tenant_id)

    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy not found",
        )

    updated = await service.update_policy(policy_id, data, tenant_id=user.tenant_id)

    audit_service = AuditService(db)
    await audit_service.log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="policy.update",
        resource_type="policy",
        resource_id=policy_id,
        request=request,
    )

    return PolicyResponse.model_validate(updated)


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> None:
    """Delete a policy in the current tenant and write an audit record."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )
    await require_team_permission(user, db, "manage")

    service = PolicyService(db)
    policy = await service.get_policy(policy_id, tenant_id=user.tenant_id)
    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy not found",
        )

    await service.delete_policy(policy_id, tenant_id=user.tenant_id)

    audit_service = AuditService(db)
    await audit_service.log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="policy.delete",
        resource_type="policy",
        resource_id=policy_id,
        request=request,
    )


# ============================================================================
# Field Permission Endpoints
# ============================================================================


@router.get(
    "/field-permissions/{role_id}/{resource_type}",
    response_model=list[FieldPermissionResponse],
)
async def get_field_permissions(
    role_id: UUID,
    resource_type: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[FieldPermissionResponse]:
    """Get field permissions for a role and resource type.

    Args:
        role_id: Role UUID
        resource_type: Resource type string
        user: Current authenticated user
        db: Database session

    Returns:
        List of field permissions
    """
    await require_team_permission(user, db, "read")
    service = FieldPermissionService(db)
    permissions = await service.get_field_permissions_for_role(
        role_id=role_id,
        resource_type=resource_type,
        tenant_id=user.tenant_id,
    )

    return [FieldPermissionResponse.model_validate(p) for p in permissions]


@router.post(
    "/field-permissions",
    response_model=FieldPermissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def set_field_permission(
    data: FieldPermissionCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> FieldPermissionResponse:
    """Set field permission for a role.

    Args:
        data: Field permission data
        user: Current authenticated user
        db: Database session
        request: HTTP request

    Returns:
        Created/updated field permission
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )
    await require_team_permission(user, db, "manage")

    service = FieldPermissionService(db)
    try:
        permission = await service.set_field_permission(data, tenant_id=user.tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="field_permission.set",
        resource_type="field_permission",
        resource_id=permission.id,
        request=request,
    )

    return FieldPermissionResponse.model_validate(permission)


@router.get("/permission-diagnostics", response_model=PermissionDiagnosticsResponse)
async def get_permission_diagnostics(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PermissionDiagnosticsResponse:
    """Return current-user RBAC, ABAC, field-control, and policy evidence."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )
    await require_team_permission(user, db, "read")

    evaluator = create_permission_evaluator(db)
    role_service = RoleService(db)
    field_service = FieldPermissionService(db)
    policy_service = PolicyService(db)

    check_targets = [
        ("projects.read", "项目资料读取", "projects", "read"),
        ("documents.review", "文档评审", "documents", "review"),
        ("documents.export", "导出交付包", "documents", "export"),
        ("agents.manage", "智能编排管理", "agents", "manage"),
        ("team.read", "团队权限读取", "team", "read"),
        ("team.manage", "团队权限管理", "team", "manage"),
    ]
    checks: list[PermissionDiagnosticCheck] = []
    for key, label, resource, action in check_targets:
        decision = await evaluator.explain_permission(user, action, resource, user.tenant_id)
        checks.append(
            PermissionDiagnosticCheck(
                key=key,
                label=label,
                resource=resource,
                action=action,
                allowed=bool(decision["allowed"]),
                reason=str(decision["reason"]),
            )
        )

    roles = await role_service.get_user_roles(user.id)
    field_controls: list[PermissionDiagnosticFieldControl] = []
    for role in roles:
        for resource_type in ["document", "project", "agent_run"]:
            permissions = await field_service.get_field_permissions_for_role(
                role_id=role.id,
                resource_type=resource_type,
                tenant_id=user.tenant_id,
            )
            for permission in permissions:
                field_controls.append(
                    PermissionDiagnosticFieldControl(
                        role_id=role.id,
                        role_name=role.name,
                        resource_type=permission.resource_type,
                        field_name=permission.field_name,
                        permission=permission.permission,
                    )
                )

    policies, _ = await policy_service.list_policies(tenant_id=user.tenant_id, skip=0, limit=100)
    policy_evidence = [
        PermissionDiagnosticPolicyEvidence(
            id=policy.id,
            name=policy.name,
            effect=policy.effect,
            actions=policy.actions,
            resources=policy.resources,
        )
        for policy in policies
    ]

    allowed_count = sum(1 for check in checks if check.allowed)
    denied_count = len(checks) - allowed_count
    return PermissionDiagnosticsResponse(
        generated_at=datetime.now(timezone.utc),
        tenant_id=user.tenant_id,
        user_id=user.id,
        summary={
            "total": len(checks),
            "allowed": allowed_count,
            "denied": denied_count,
            "field_restricted": sum(1 for control in field_controls if control.permission == "none"),
        },
        checks=checks,
        field_controls=field_controls,
        policy_evidence=policy_evidence,
    )


@router.get("/permission-command-center", response_model=PermissionCommandCenterResponse)
async def get_permission_command_center(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PermissionCommandCenterResponse:
    """Return team-access governance gate, risks, and priority actions."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )
    await require_team_permission(user, db, "read")

    users, _ = await UserService(db).list_users(user.tenant_id, skip=0, limit=500)
    roles, _ = await RoleService(db).list_roles(user.tenant_id, skip=0, limit=500)
    policies, _ = await PolicyService(db).list_policies(user.tenant_id, skip=0, limit=500)
    diagnostics = await get_permission_diagnostics(user=user, db=db)

    field_permission_count = int(
        await db.scalar(
            select(func.count(FieldPermission.id)).where(FieldPermission.tenant_id == user.tenant_id)
        )
        or 0
    )
    field_restricted_count = int(
        await db.scalar(
            select(func.count(FieldPermission.id)).where(
                FieldPermission.tenant_id == user.tenant_id,
                FieldPermission.permission == "none",
            )
        )
        or 0
    )
    audit_log_count = int(
        await db.scalar(select(func.count(AuditLog.id)).where(AuditLog.tenant_id == user.tenant_id))
        or 0
    )
    recent_audit_actions = list(
        (
            await db.scalars(
                select(AuditLog.action)
                .where(AuditLog.tenant_id == user.tenant_id)
                .order_by(AuditLog.created_at.desc())
                .limit(5)
            )
        ).all()
    )

    users_without_roles = sum(1 for item in users if not _loaded_roles(item) and item.is_active is not False)
    high_privilege_roles = sum(1 for role in roles if _role_has_high_privilege(role))
    deny_policy_count = sum(1 for policy in policies if policy.effect == "deny")
    summary = {
        "total_users": len(users),
        "active_users": sum(1 for item in users if item.is_active is not False),
        "users_without_roles": users_without_roles,
        "role_count": len(roles),
        "high_privilege_roles": high_privilege_roles,
        "policy_count": len(policies),
        "deny_policy_count": deny_policy_count,
        "field_permission_count": field_permission_count,
        "field_restricted_count": field_restricted_count,
        "audit_log_count": audit_log_count,
        "diagnostic_allowed": diagnostics.summary.get("allowed", 0),
        "diagnostic_denied": diagnostics.summary.get("denied", 0),
    }
    risk_items = _permission_command_risks(summary)
    release_gate = _permission_release_gate(summary, risk_items)

    return PermissionCommandCenterResponse(
        generated_at=datetime.now(timezone.utc),
        tenant_id=user.tenant_id,
        release_gate=release_gate,
        summary=summary,
        risk_items=risk_items,
        priority_actions=_permission_priority_actions(summary),
        diagnostic_snapshot=diagnostics.summary,
        recent_audit_actions=recent_audit_actions,
    )


def _role_has_high_privilege(role: Role) -> bool:
    permissions = role.permissions or {}
    if permissions == "*" or permissions is True:
        return True
    if not isinstance(permissions, dict):
        return False
    for resource, value in permissions.items():
        if value == "*" or value is True:
            return True
        if isinstance(value, list):
            actions = {str(item) for item in value}
        elif isinstance(value, str):
            actions = {value}
        elif isinstance(value, dict):
            actions = {str(action) for action, enabled in value.items() if enabled}
        else:
            actions = set()
        if "*" in actions or "manage" in actions:
            return True
        if resource == "documents" and actions.intersection({"publish", "export", "archive"}):
            return True
    return False


def _permission_command_risks(summary: dict[str, int]) -> list[PermissionCommandCenterRiskItem]:
    risks: list[PermissionCommandCenterRiskItem] = []
    if summary["users_without_roles"]:
        risks.append(
            PermissionCommandCenterRiskItem(
                code="users_without_roles",
                severity="critical",
                title="存在未授权成员",
                detail="启用账号没有任何角色，无法证明最小权限边界和责任归属。",
                count=summary["users_without_roles"],
                href="/team",
            )
        )
    if summary["diagnostic_denied"]:
        risks.append(
            PermissionCommandCenterRiskItem(
                code="permission_denials",
                severity="high",
                title="权限自检存在拒绝项",
                detail="当前账号的关键项目、文档、编排或团队操作仍被拒绝，需要发布前复核。",
                count=summary["diagnostic_denied"],
                href="/team",
            )
        )
    if summary["deny_policy_count"]:
        risks.append(
            PermissionCommandCenterRiskItem(
                code="deny_policies",
                severity="medium",
                title="存在拒绝策略",
                detail="deny 策略会覆盖角色授权，需要确认命中范围和业务例外。",
                count=summary["deny_policy_count"],
                href="/team",
            )
        )
    if summary["field_restricted_count"]:
        risks.append(
            PermissionCommandCenterRiskItem(
                code="field_restrictions",
                severity="medium",
                title="字段级权限限制生效",
                detail="字段 none 权限会影响文档、导出和智能编排可见性，需要确认敏感字段策略。",
                count=summary["field_restricted_count"],
                href="/team",
            )
        )
    if summary["high_privilege_roles"]:
        risks.append(
            PermissionCommandCenterRiskItem(
                code="high_privilege_roles",
                severity="medium",
                title="高权限角色需要复核",
                detail="存在可发布、导出、授权或管理的角色，建议在发布前复核授权范围。",
                count=summary["high_privilege_roles"],
                href="/team",
            )
        )
    if summary["audit_log_count"] == 0:
        risks.append(
            PermissionCommandCenterRiskItem(
                code="missing_audit_evidence",
                severity="medium",
                title="缺少权限审计证据",
                detail="没有可追踪的权限变更或模拟记录，验收时难以说明授权来源。",
                count=1,
                href="/audit",
            )
        )
    return risks


def _permission_release_gate(
    summary: dict[str, int],
    risk_items: list[PermissionCommandCenterRiskItem],
) -> PermissionCommandCenterReleaseGate:
    blockers = [item.title for item in risk_items if item.severity in {"critical", "high"}]
    warnings = [item.title for item in risk_items if item.severity == "medium"]
    if blockers:
        return PermissionCommandCenterReleaseGate(
            status="blocked",
            label="权限阻断",
            summary="团队权限仍存在无角色成员或关键权限拒绝项，不能作为生产验收证据。",
            blockers=blockers,
            warnings=warnings,
        )
    if warnings:
        return PermissionCommandCenterReleaseGate(
            status="attention",
            label="需要复核",
            summary="没有硬阻断，但高权限、拒绝策略、字段限制或审计证据仍需发布前确认。",
            blockers=[],
            warnings=warnings,
        )
    return PermissionCommandCenterReleaseGate(
        status="passed",
        label="权限可验收",
        summary="成员、角色、策略、字段权限和审计证据满足团队权限验收要求。",
        blockers=[],
        warnings=[],
    )


def _permission_priority_actions(summary: dict[str, int]) -> list[PermissionCommandCenterPriorityAction]:
    actions: list[PermissionCommandCenterPriorityAction] = []
    if summary["users_without_roles"]:
        actions.append(
            PermissionCommandCenterPriorityAction(
                code="assign_roles",
                title="分配未授权成员角色",
                description="为没有角色的启用成员补齐岗位角色，避免最小权限边界缺失。",
                href="/team",
                priority="critical",
            )
        )
    if summary["diagnostic_denied"]:
        actions.append(
            PermissionCommandCenterPriorityAction(
                code="review_denials",
                title="复核权限自检拒绝项",
                description="检查项目、文档、编排、团队权限的拒绝原因，并调整角色或策略。",
                href="/team",
                priority="high",
            )
        )
    if summary["deny_policy_count"] or summary["field_restricted_count"]:
        actions.append(
            PermissionCommandCenterPriorityAction(
                code="review_policy_and_fields",
                title="复核策略与字段权限",
                description="确认 deny 策略、字段 none 权限不会阻断交付包、文档评审和智能编排。",
                href="/team",
                priority="medium",
            )
        )
    if summary["audit_log_count"] == 0:
        actions.append(
            PermissionCommandCenterPriorityAction(
                code="preserve_audit_evidence",
                title="补齐权限审计证据",
                description="执行权限模拟或角色分配操作，保留可追溯的验收证据。",
                href="/audit",
                priority="medium",
            )
        )
    if not actions:
        actions.append(
            PermissionCommandCenterPriorityAction(
                code="preserve_governance_baseline",
                title="保留权限治理基线",
                description="保留当前角色、策略、字段权限和审计证据，用于发布验收。",
                href="/team",
                priority="medium",
            )
        )
    return actions


@router.post("/permission-simulations", response_model=PermissionSimulationResponse)
async def simulate_permission_decision(
    data: PermissionSimulationRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PermissionSimulationResponse:
    """Simulate one tenant member permission decision with auditable evidence."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )
    await require_team_permission(user, db, "read")

    target_user = await UserService(db).get_user(data.user_id, tenant_id=user.tenant_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    evaluator = create_permission_evaluator(db)
    role_service = RoleService(db)
    field_service = FieldPermissionService(db)
    policy_service = PolicyService(db)

    decision = await evaluator.explain_permission(
        target_user,
        data.action,
        data.resource,
        user.tenant_id,
    )
    roles = await role_service.get_user_roles(target_user.id)

    field_controls: list[PermissionDiagnosticFieldControl] = []
    if data.resource_type:
        for role in roles:
            permissions = await field_service.get_field_permissions_for_role(
                role_id=role.id,
                resource_type=data.resource_type,
                tenant_id=user.tenant_id,
            )
            for permission in permissions:
                if data.field_name and permission.field_name != data.field_name:
                    continue
                field_controls.append(
                    PermissionDiagnosticFieldControl(
                        role_id=role.id,
                        role_name=role.name,
                        resource_type=permission.resource_type,
                        field_name=permission.field_name,
                        permission=permission.permission,
                    )
                )

    policies, _ = await policy_service.list_policies(tenant_id=user.tenant_id, skip=0, limit=100)
    policy_evidence = [
        PermissionDiagnosticPolicyEvidence(
            id=policy.id,
            name=policy.name,
            effect=policy.effect,
            actions=policy.actions,
            resources=policy.resources,
        )
        for policy in policies
        if _policy_applies_to_simulation(policy, data.action, data.resource)
    ]

    await AuditService(db).log_action(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="permission.simulate",
        resource_type="user",
        resource_id=target_user.id,
        metadata={
            "target_user_id": str(target_user.id),
            "resource": data.resource,
            "action": data.action,
            "allowed": bool(decision["allowed"]),
            "reason": str(decision["reason"]),
        },
    )

    return PermissionSimulationResponse(
        generated_at=datetime.now(timezone.utc),
        tenant_id=user.tenant_id,
        requested_by_user_id=user.id,
        target_user_id=target_user.id,
        target_user_email=target_user.email,
        target_user_name=target_user.full_name,
        resource=data.resource,
        action=data.action,
        allowed=bool(decision["allowed"]),
        reason=str(decision["reason"]),
        roles=[
            PermissionSimulationRoleEvidence(
                id=role.id,
                name=role.name,
                description=role.description,
                permissions=role.permissions or {},
            )
            for role in roles
        ],
        field_controls=field_controls,
        policy_evidence=policy_evidence,
    )


# ============================================================================
# Tenant API Key Endpoints
# ============================================================================


def _api_key_response(key: Any) -> TenantApiKeyResponse:
    return TenantApiKeyResponse.model_validate(key)


@router.get("/api-keys", response_model=PaginatedResponse[TenantApiKeyResponse])
async def list_api_keys(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> PaginatedResponse[TenantApiKeyResponse]:
    """List current-tenant API key metadata without plaintext secrets."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )
    await require_team_permission(user, db, "read")

    service = TenantApiKeyService(db)
    keys, total = await service.list_api_keys(user.tenant_id, skip=skip, limit=limit)
    return PaginatedResponse(
        items=[_api_key_response(key) for key in keys],
        total=total,
        page=skip // limit + 1,
        page_size=limit,
        has_more=(skip + len(keys)) < total,
    )


@router.post("/api-keys", response_model=TenantApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    data: TenantApiKeyCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TenantApiKeyCreateResponse:
    """Create a tenant API key and return the plaintext secret once."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )
    await require_team_permission(user, db, "manage")

    service = TenantApiKeyService(db)
    key, plain_key = await service.create_api_key(
        data,
        tenant_id=user.tenant_id,
        created_by_id=user.id,
    )
    payload = _api_key_response(key).model_dump()
    return TenantApiKeyCreateResponse(**payload, api_key=plain_key)


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Revoke a current-tenant API key."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a tenant",
        )
    await require_team_permission(user, db, "manage")

    service = TenantApiKeyService(db)
    if not await service.revoke_api_key(key_id, tenant_id=user.tenant_id, revoked_by_id=user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )


# ============================================================================
# Audit Log Endpoints
# ============================================================================


@router.get("/audit-logs", response_model=PaginatedResponse[AuditLogResponse])
async def list_audit_logs(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: UUID | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    resource_id: UUID | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> PaginatedResponse[AuditLogResponse]:
    """List audit logs.

    Super administrators can query all tenants. Team readers and managers can
    query only their own tenant, which keeps the team permission page usable
    without exposing cross-tenant audit history.
    """
    is_admin = await has_admin_permission(db, user)
    if not is_admin:
        await require_team_permission(user, db, "read")
        if tenant_id is not None and tenant_id != user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot query audit logs for another tenant",
            )
        tenant_id = user.tenant_id

    service = AuditService(db)
    logs, total = await service.query_logs(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )

    return PaginatedResponse(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page - 1) * page_size + len(logs) < total,
    )
