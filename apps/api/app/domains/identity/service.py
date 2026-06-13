"""Identity Domain Services

Business logic for authentication, tenant, user, role, and policy management.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from jwt.exceptions import InvalidTokenError
from sqlalchemy import delete, select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.settings import settings
from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
    add_to_blacklist,
    is_token_blacklisted,
)
from app.domains.identity.models import (
    AuditLog,
    FieldPermission,
    Policy,
    TenantApiKey,
)
from app.models.identity import (
    Role,
    Tenant,
    User,
    UserRole,
)
from app.domains.identity.schemas import (
    AssignRoleRequest,
    FieldPermissionCreate,
    LoginRequest,
    PolicyCreate,
    PolicyUpdate,
    RoleCreate,
    RoleUpdate,
    TenantCreate,
    TenantUpdate,
    TenantApiKeyCreate,
    UserCreate,
    UserUpdate,
)


class TenantApiKeyService:
    """Manage tenant-scoped API keys with one-time secret reveal."""

    KEY_PREFIX_LENGTH = 12

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _hash_key(api_key: str) -> str:
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    @classmethod
    def _generate_key(cls) -> str:
        return f"amx_{secrets.token_urlsafe(32)}"

    async def create_api_key(
        self,
        data: TenantApiKeyCreate,
        tenant_id: UUID,
        created_by_id: UUID | None,
    ) -> tuple[TenantApiKey, str]:
        """Create an API key and return its plaintext value exactly once."""
        plain_key = self._generate_key()
        key = TenantApiKey(
            tenant_id=tenant_id,
            name=data.name,
            key_prefix=plain_key[: self.KEY_PREFIX_LENGTH],
            key_hash=self._hash_key(plain_key),
            permissions=list(dict.fromkeys(data.permissions)),
            status="active",
            created_by_id=created_by_id,
            expires_at=data.expires_at,
        )
        self.db.add(key)
        await self.db.flush()
        await self.db.refresh(key)
        await self._write_audit(
            tenant_id=tenant_id,
            user_id=created_by_id,
            action="api_key.create",
            key=key,
        )
        return key, plain_key

    async def list_api_keys(
        self,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[TenantApiKey], int]:
        """List tenant API key metadata without plaintext secrets."""
        filters = [
            TenantApiKey.tenant_id == tenant_id,
            TenantApiKey.deleted_at.is_(None),
        ]
        total = await self.db.scalar(select(func.count(TenantApiKey.id)).where(*filters))
        result = await self.db.execute(
            select(TenantApiKey)
            .where(*filters)
            .order_by(TenantApiKey.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def verify_api_key(self, api_key: str) -> TenantApiKey | None:
        """Return the active key record if a plaintext API key is valid."""
        result = await self.db.execute(
            select(TenantApiKey).where(
                TenantApiKey.key_hash == self._hash_key(api_key),
                TenantApiKey.status == "active",
                TenantApiKey.deleted_at.is_(None),
            )
        )
        key = result.scalar_one_or_none()
        if not key:
            return None
        now = datetime.now(timezone.utc)
        if key.expires_at and key.expires_at <= now:
            return None
        key.last_used_at = now
        await self.db.flush()
        await self.db.refresh(key)
        return key

    async def revoke_api_key(
        self,
        key_id: UUID,
        tenant_id: UUID,
        revoked_by_id: UUID | None,
    ) -> bool:
        """Revoke one tenant API key."""
        result = await self.db.execute(
            select(TenantApiKey).where(
                TenantApiKey.id == key_id,
                TenantApiKey.tenant_id == tenant_id,
                TenantApiKey.deleted_at.is_(None),
            )
        )
        key = result.scalar_one_or_none()
        if not key:
            return False

        key.status = "revoked"
        key.revoked_by_id = revoked_by_id
        key.revoked_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(key)
        await self._write_audit(
            tenant_id=tenant_id,
            user_id=revoked_by_id,
            action="api_key.revoke",
            key=key,
        )
        return True

    async def _write_audit(
        self,
        tenant_id: UUID,
        user_id: UUID | None,
        action: str,
        key: TenantApiKey,
    ) -> None:
        audit_log = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type="api_key",
            resource_id=key.id,
            extra_data={
                "name": key.name,
                "key_prefix": key.key_prefix,
                "permissions": key.permissions,
                "status": key.status,
                "expires_at": key.expires_at.isoformat() if key.expires_at else None,
            },
        )
        self.db.add(audit_log)
        await self.db.flush()


class AuthService:
    """Service for authentication operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def login(self, credentials: LoginRequest) -> tuple[User, str]:
        """Authenticate user and create access token.

        Args:
            credentials: Login credentials

        Returns:
            Tuple of (User, access_token)

        Raises:
            ValueError: If credentials are invalid
        """
        result = await self.db.execute(
            select(User).where(
                User.email == credentials.email,
                User.deleted_at.is_(None),
            )
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(credentials.password, user.hashed_password):
            raise ValueError("Invalid email or password")

        if not user.is_active:
            raise ValueError("User account is disabled")

        # Create access token with user info
        token_data = {
            "sub": str(user.id),
            "email": user.email,
            "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        }
        access_token = create_access_token(token_data)

        return user, access_token

    async def logout(self, token: str) -> None:
        """Logout user by blacklisting their token.

        Args:
            token: JWT token to blacklist
        """
        try:
            payload = decode_token(token)
            jti = payload.get("jti")
            if jti:
                await add_to_blacklist(jti, self.db)
        except InvalidTokenError:
            pass  # Invalid tokens are simply ignored

    async def get_current_user(self, token: str) -> User | None:
        """Get current user from JWT token.

        Args:
            token: JWT bearer token

        Returns:
            User if token is valid, None otherwise
        """
        try:
            payload = decode_token(token)
            jti = payload.get("jti")

            # Check if token is blacklisted
            if jti and await is_token_blacklisted(jti, self.db):
                return None

            user_id = payload.get("sub")
            if not user_id:
                return None

            result = await self.db.execute(
                select(User).where(
                    User.id == UUID(user_id),
                    User.deleted_at.is_(None),
                )
            )
            user = result.scalar_one_or_none()

            if user and not user.is_active:
                return None

            return user
        except (InvalidTokenError, ValueError):
            return None

    def get_token_expiry(self) -> int:
        """Get token expiry time in seconds."""
        return settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60


class TenantService:
    """Service for tenant management operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_tenant(self, data: TenantCreate) -> Tenant:
        """Create a new tenant.

        Args:
            data: Tenant creation data

        Returns:
            Created Tenant
        """
        tenant = Tenant(
            name=data.name,
            slug=data.slug,
        )
        self.db.add(tenant)
        await self.db.flush()
        await self.db.refresh(tenant)
        return tenant

    async def get_tenant(self, tenant_id: UUID) -> Tenant | None:
        """Get tenant by ID.

        Args:
            tenant_id: Tenant UUID

        Returns:
            Tenant if found, None otherwise
        """
        result = await self.db.execute(
            select(Tenant).where(
                Tenant.id == tenant_id,
                Tenant.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        """Get tenant by slug.

        Args:
            slug: Tenant slug

        Returns:
            Tenant if found, None otherwise
        """
        result = await self.db.execute(
            select(Tenant).where(
                Tenant.slug == slug,
                Tenant.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_tenants(
        self,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Tenant], int]:
        """List all tenants (admin only).

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of Tenants, total count)
        """
        # Count total
        count_result = await self.db.execute(
            select(func.count(Tenant.id)).where(Tenant.deleted_at.is_(None))
        )
        total = count_result.scalar_one()

        # Get paginated results
        result = await self.db.execute(
            select(Tenant)
            .where(Tenant.deleted_at.is_(None))
            .offset(skip)
            .limit(limit)
            .order_by(Tenant.created_at.desc())
        )
        tenants = list(result.scalars().all())

        return tenants, total

    async def update_tenant(self, tenant_id: UUID, data: TenantUpdate) -> Tenant | None:
        """Update a tenant.

        Args:
            tenant_id: Tenant UUID
            data: Update data

        Returns:
            Updated Tenant if found, None otherwise
        """
        tenant = await self.get_tenant(tenant_id)
        if not tenant:
            return None

        if data.name is not None:
            tenant.name = data.name
        if data.slug is not None:
            tenant.slug = data.slug

        await self.db.flush()
        await self.db.refresh(tenant)
        return tenant


class UserService:
    """Service for user management operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_user(self, data: UserCreate) -> User:
        """Create a new user.

        Args:
            data: User creation data

        Returns:
            Created User
        """
        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            tenant_id=data.tenant_id,
            is_active=data.is_active,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def get_user(self, user_id: UUID, tenant_id: UUID | None = None) -> User | None:
        """Get user by ID with optional tenant filter.

        Args:
            user_id: User UUID
            tenant_id: Optional tenant filter

        Returns:
            User if found, None otherwise
        """
        query = select(User).where(
            User.id == user_id,
            User.deleted_at.is_(None),
        )
        if tenant_id is not None:
            query = query.where(User.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str, tenant_id: UUID | None = None) -> User | None:
        """Get user by email with optional tenant filter.

        Args:
            email: User email
            tenant_id: Optional tenant filter

        Returns:
            User if found, None otherwise
        """
        query = select(User).where(
            User.email == email,
            User.deleted_at.is_(None),
        )
        if tenant_id is not None:
            query = query.where(User.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_users(
        self,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[User], int]:
        """List users for a tenant.

        Args:
            tenant_id: Tenant UUID
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of Users, total count)
        """
        # Count total
        count_result = await self.db.execute(
            select(func.count(User.id)).where(
                User.tenant_id == tenant_id,
                User.deleted_at.is_(None),
            )
        )
        total = count_result.scalar_one()

        # Get paginated results with roles
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.roles).selectinload(UserRole.role))
            .where(
                User.tenant_id == tenant_id,
                User.deleted_at.is_(None),
            )
            .offset(skip)
            .limit(limit)
            .order_by(User.created_at.desc())
        )
        users = list(result.scalars().all())

        return users, total

    async def update_user(
        self,
        user_id: UUID,
        data: UserUpdate,
        tenant_id: UUID | None = None,
    ) -> User | None:
        """Update a user.

        Args:
            user_id: User UUID
            data: Update data
            tenant_id: Optional tenant filter

        Returns:
            Updated User if found, None otherwise
        """
        user = await self.get_user(user_id, tenant_id)
        if not user:
            return None

        if data.email is not None:
            user.email = data.email
        if data.full_name is not None:
            user.full_name = data.full_name
        if data.is_active is not None:
            user.is_active = data.is_active
        if data.password is not None:
            user.hashed_password = hash_password(data.password)

        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def delete_user(self, user_id: UUID, tenant_id: UUID | None = None) -> bool:
        """Soft delete a user.

        Args:
            user_id: User UUID
            tenant_id: Optional tenant filter

        Returns:
            True if deleted, False if not found
        """
        user = await self.get_user(user_id, tenant_id)
        if not user:
            return False

        user.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True


class RoleService:
    """Service for role management operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_role(self, data: RoleCreate, tenant_id: UUID) -> Role:
        """Create a new role.

        Args:
            data: Role creation data
            tenant_id: Tenant UUID

        Returns:
            Created Role
        """
        role = Role(
            name=data.name,
            description=data.description,
            permissions=data.permissions,
            tenant_id=tenant_id,
        )
        self.db.add(role)
        await self.db.flush()
        await self.db.refresh(role)
        return role

    async def get_role(self, role_id: UUID, tenant_id: UUID | None = None) -> Role | None:
        """Get role by ID with optional tenant filter.

        Args:
            role_id: Role UUID
            tenant_id: Optional tenant filter

        Returns:
            Role if found, None otherwise
        """
        query = select(Role).where(Role.id == role_id)
        if tenant_id is not None:
            query = query.where(Role.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_roles(
        self,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Role], int]:
        """List roles for a tenant.

        Args:
            tenant_id: Tenant UUID
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of Roles, total count)
        """
        # Count total
        count_result = await self.db.execute(
            select(func.count(Role.id)).where(Role.tenant_id == tenant_id)
        )
        total = count_result.scalar_one()

        # Get paginated results
        result = await self.db.execute(
            select(Role)
            .where(Role.tenant_id == tenant_id)
            .offset(skip)
            .limit(limit)
            .order_by(Role.created_at.desc())
        )
        roles = list(result.scalars().all())

        return roles, total

    async def update_role(
        self,
        role_id: UUID,
        data: RoleUpdate,
        tenant_id: UUID | None = None,
    ) -> Role | None:
        """Update a role.

        Args:
            role_id: Role UUID
            data: Update data
            tenant_id: Optional tenant filter

        Returns:
            Updated Role if found, None otherwise
        """
        role = await self.get_role(role_id, tenant_id)
        if not role:
            return None

        if data.name is not None:
            role.name = data.name
        if data.description is not None:
            role.description = data.description
        if data.permissions is not None:
            role.permissions = data.permissions

        await self.db.flush()
        await self.db.refresh(role)
        return role

    async def assign_role_to_user(
        self,
        user_id: UUID,
        role_id: UUID,
        tenant_id: UUID,
    ) -> bool:
        """Assign a role to a user.

        Args:
            user_id: User UUID
            role_id: Role UUID
            tenant_id: Tenant UUID to verify role ownership

        Returns:
            True if assigned, False otherwise
        """
        # Verify user exists
        user_result = await self.db.execute(
            select(User).where(
                User.id == user_id,
                User.tenant_id == tenant_id,
                User.deleted_at.is_(None),
            )
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return False

        # Verify role exists and belongs to the caller's tenant
        role_result = await self.db.execute(
            select(Role).where(Role.id == role_id, Role.tenant_id == tenant_id)
        )
        role = role_result.scalar_one_or_none()
        if not role:
            return False

        # Check if assignment already exists
        existing = await self.db.execute(
            select(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
            )
        )
        if existing.scalar_one_or_none():
            return True  # Already assigned

        # Create assignment
        user_role = UserRole(user_id=user_id, role_id=role_id)
        self.db.add(user_role)
        await self.db.flush()
        return True

    async def revoke_role_from_user(
        self,
        user_id: UUID,
        role_id: UUID,
        tenant_id: UUID,
    ) -> bool:
        """Remove a tenant-owned role assignment from a tenant-owned user.

        Returns True when the assignment no longer exists. Returns False when
        the user or role is outside the tenant boundary.
        """
        user_result = await self.db.execute(
            select(User.id).where(
                User.id == user_id,
                User.tenant_id == tenant_id,
                User.deleted_at.is_(None),
            )
        )
        if user_result.scalar_one_or_none() is None:
            return False

        role_result = await self.db.execute(
            select(Role.id).where(Role.id == role_id, Role.tenant_id == tenant_id)
        )
        if role_result.scalar_one_or_none() is None:
            return False

        await self.db.execute(
            delete(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
            )
        )
        await self.db.flush()
        return True

    async def delete_role(self, role_id: UUID, tenant_id: UUID) -> bool:
        """Delete an unassigned tenant role.

        Assigned roles are blocked so administrators cannot accidentally remove
        active authorization boundaries from users.
        """
        role = await self.get_role(role_id, tenant_id=tenant_id)
        if not role:
            return False

        assignment_count = await self.db.scalar(
            select(func.count(UserRole.user_id)).where(UserRole.role_id == role_id)
        )
        if assignment_count:
            return False

        await self.db.execute(
            delete(FieldPermission).where(
                FieldPermission.role_id == role_id,
                FieldPermission.tenant_id == tenant_id,
            )
        )
        await self.db.delete(role)
        await self.db.flush()
        return True

    async def get_user_roles(self, user_id: UUID) -> list[Role]:
        """Get all roles for a user.

        Args:
            user_id: User UUID

        Returns:
            List of Roles assigned to the user
        """
        result = await self.db.execute(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        return list(result.scalars().all())


class PolicyService:
    """Service for policy management and evaluation."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_policy(self, data: PolicyCreate, tenant_id: UUID) -> Policy:
        """Create a new policy.

        Args:
            data: Policy creation data
            tenant_id: Tenant UUID

        Returns:
            Created Policy
        """
        policy = Policy(
            name=data.name,
            description=data.description,
            effect=data.effect,
            actions=data.actions,
            resources=data.resources,
            conditions=data.conditions,
            tenant_id=tenant_id,
        )
        self.db.add(policy)
        await self.db.flush()
        await self.db.refresh(policy)
        return policy

    async def get_policy(self, policy_id: UUID, tenant_id: UUID | None = None) -> Policy | None:
        """Get policy by ID with optional tenant filter.

        Args:
            policy_id: Policy UUID
            tenant_id: Optional tenant filter

        Returns:
            Policy if found, None otherwise
        """
        query = select(Policy).where(Policy.id == policy_id)
        if tenant_id is not None:
            query = query.where(Policy.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_policies(
        self,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Policy], int]:
        """List policies for a tenant.

        Args:
            tenant_id: Tenant UUID
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of Policies, total count)
        """
        # Count total
        count_result = await self.db.execute(
            select(func.count(Policy.id)).where(Policy.tenant_id == tenant_id)
        )
        total = count_result.scalar_one()

        # Get paginated results
        result = await self.db.execute(
            select(Policy)
            .where(Policy.tenant_id == tenant_id)
            .offset(skip)
            .limit(limit)
            .order_by(Policy.created_at.desc())
        )
        policies = list(result.scalars().all())

        return policies, total

    async def update_policy(
        self,
        policy_id: UUID,
        data: PolicyUpdate,
        tenant_id: UUID | None = None,
    ) -> Policy | None:
        """Update a policy.

        Args:
            policy_id: Policy UUID
            data: Update data
            tenant_id: Optional tenant filter

        Returns:
            Updated Policy if found, None otherwise
        """
        policy = await self.get_policy(policy_id, tenant_id)
        if not policy:
            return None

        if data.name is not None:
            policy.name = data.name
        if data.description is not None:
            policy.description = data.description
        if data.effect is not None:
            policy.effect = data.effect
        if data.actions is not None:
            policy.actions = data.actions
        if data.resources is not None:
            policy.resources = data.resources
        if data.conditions is not None:
            policy.conditions = data.conditions

        await self.db.flush()
        await self.db.refresh(policy)
        return policy

    async def delete_policy(self, policy_id: UUID, tenant_id: UUID) -> bool:
        """Delete a tenant policy."""
        policy = await self.get_policy(policy_id, tenant_id=tenant_id)
        if not policy:
            return False

        await self.db.delete(policy)
        await self.db.flush()
        return True

    async def evaluate_policy(
        self,
        user: User,
        action: str,
        resource: str,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Evaluate if user has permission for action on resource.

        Args:
            user: User to check
            action: Action being performed (e.g., "read", "write")
            resource: Resource being accessed (e.g., "projects:*", "documents:read")
            tenant_id: Tenant ID for policy scope

        Returns:
            True if allowed, False otherwise
        """
        # Get user roles
        roles = await self._get_user_roles(user.id)
        if not roles:
            return False

        # Collect all role permissions
        role_permissions: set[str] = set()
        for role in roles:
            perms = role.permissions or {}
            # Wildcard permissions
            if perms.get("*"):
                return True  # Superuser
            # Action-specific permissions
            resource_perms = perms.get(resource, perms.get(resource.split(":")[0] + ":*", []))
            if isinstance(resource_perms, list):
                role_permissions.update(resource_perms)
            elif resource_perms:
                role_permissions.add(resource_perms)

        # Check if action is in role permissions
        if action in role_permissions or "*" in role_permissions:
            # Find applicable policies - fetch all for tenant first
            query = select(Policy).where(Policy.tenant_id == tenant_id)
            result = await self.db.execute(query)
            all_policies = list(result.scalars().all())

            # Filter policies by resource matching (including wildcard)
            policies = [
                p for p in all_policies
                if any(self._wildcard_match(r, resource) for r in p.resources)
            ]

            # Evaluate policies (deny takes precedence)
            has_deny = False
            has_allow = False

            for policy in policies:
                # Check if policy applies to this action
                if action in policy.actions or "*" in policy.actions:
                    if policy.effect == "deny":
                        has_deny = True
                    elif policy.effect == "allow":
                        has_allow = True

                    # Check conditions
                    if policy.conditions:
                        if not self._evaluate_conditions(policy.conditions, user, tenant_id):
                            continue

            if has_deny:
                return False
            return has_allow

        return False

    async def _get_user_roles(self, user_id: UUID) -> list[Role]:
        """Get all roles for a user."""
        result = await self.db.execute(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        return list(result.scalars().all())

    def _wildcard_match(self, pattern: str, resource: str) -> bool:
        """Check if resource matches wildcard pattern."""
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return resource.startswith(prefix)
        return pattern == resource

    def _evaluate_conditions(
        self,
        conditions: dict[str, Any],
        user: User,
        tenant_id: UUID | None,
    ) -> bool:
        """Evaluate ABAC conditions against user context."""
        # Simple condition evaluation
        for key, value in conditions.items():
            if key == "tenant_id":
                if str(tenant_id) != str(value).replace("{{tenant_id}}", str(tenant_id)):
                    return False
            elif key == "user_id":
                if str(user.id) != str(value).replace("{{user_id}}", str(user.id)):
                    return False
            elif key == "is_active":
                if user.is_active != value:
                    return False
        return True


class FieldPermissionService:
    """Service for field-level permission management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def set_field_permission(
        self,
        data: FieldPermissionCreate,
        tenant_id: UUID,
    ) -> FieldPermission:
        """Set or update field permission.

        Args:
            data: Field permission data
            tenant_id: Tenant UUID

        Returns:
            Created/Updated FieldPermission
        """
        role_result = await self.db.execute(
            select(Role.id).where(
                Role.id == data.role_id,
                Role.tenant_id == tenant_id,
            )
        )
        if role_result.scalar_one_or_none() is None:
            raise ValueError("Role not found for tenant")

        # Check for existing
        result = await self.db.execute(
            select(FieldPermission).where(
                FieldPermission.role_id == data.role_id,
                FieldPermission.resource_type == data.resource_type,
                FieldPermission.field_name == data.field_name,
                FieldPermission.tenant_id == tenant_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.permission = data.permission
            await self.db.flush()
            await self.db.refresh(existing)
            return existing

        # Create new
        permission = FieldPermission(
            role_id=data.role_id,
            resource_type=data.resource_type,
            field_name=data.field_name,
            permission=data.permission,
            tenant_id=tenant_id,
        )
        self.db.add(permission)
        await self.db.flush()
        await self.db.refresh(permission)
        return permission

    async def get_field_permissions_for_role(
        self,
        role_id: UUID,
        resource_type: str,
        tenant_id: UUID | None = None,
    ) -> list[FieldPermission]:
        """Get all field permissions for a role and resource type.

        Args:
            role_id: Role UUID
            resource_type: Resource type string
            tenant_id: Optional tenant filter

        Returns:
            List of FieldPermissions
        """
        query = select(FieldPermission).where(
            FieldPermission.role_id == role_id,
            FieldPermission.resource_type == resource_type,
        )
        if tenant_id is not None:
            query = query.where(FieldPermission.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    def filter_fields_based_on_permissions(
        self,
        permissions: list[FieldPermission],
        data: dict[str, Any],
        permission_type: str = "read",
    ) -> dict[str, Any]:
        """Filter data fields based on field permissions.

        Args:
            permissions: List of field permissions
            data: Data dictionary to filter
            permission_type: Type of permission to check ("read" or "write")

        Returns:
            Filtered data dictionary
        """
        # Build permission map
        perm_map: dict[str, str] = {}
        for perm in permissions:
            perm_map[perm.field_name] = perm.permission

        filtered = {}
        for field, value in data.items():
            perm = perm_map.get(field)
            if perm is None:
                # No explicit permission means allow
                filtered[field] = value
            elif perm == permission_type or perm == "read":
                # Allowed to read/write
                filtered[field] = value
            # "none" permission means field is excluded

        return filtered
