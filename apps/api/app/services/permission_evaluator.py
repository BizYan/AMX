"""Permission Evaluator Service

Evaluates RBAC + ABAC + Field permissions for resource access control.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.identity.models import FieldPermission, Policy, Role, User, UserRole
from app.domains.identity.service import FieldPermissionService, PolicyService

TEAM_MANAGED_RESOURCES = {"roles", "users", "policies", "field_permissions", "field-permissions"}


class PermissionEvaluator:
    """Service for evaluating permissions across RBAC, ABAC, and field-level controls."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._policy_service: PolicyService | None = None
        self._field_permission_service: FieldPermissionService | None = None

    @property
    def policy_service(self) -> PolicyService:
        """Lazy initialization of PolicyService."""
        if self._policy_service is None:
            self._policy_service = PolicyService(self.db)
        return self._policy_service

    @property
    def field_permission_service(self) -> FieldPermissionService:
        """Lazy initialization of FieldPermissionService."""
        if self._field_permission_service is None:
            self._field_permission_service = FieldPermissionService(self.db)
        return self._field_permission_service

    async def has_permission(
        self,
        user: User,
        action: str,
        resource: str,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Check if user has permission for action on resource.

        Combines RBAC role permissions with ABAC policy evaluation.

        Args:
            user: User to check
            action: Action being performed (e.g., "read", "write", "delete")
            resource: Resource being accessed (e.g., "projects", "documents:read")
            tenant_id: Tenant ID for policy scope

        Returns:
            True if allowed, False otherwise
        """
        # Admin users have all permissions
        if await self._is_admin_user(user):
            return True

        # Check role-based permissions first (fast path)
        if await self._has_rbac_permission(user, action, resource):
            # Check if there are any deny policies
            if await self._has_deny_policy(user, action, resource, tenant_id):
                return False
            return True

        # Fall back to policy evaluation
        return await self.policy_service.evaluate_policy(
            user=user,
            action=action,
            resource=resource,
            tenant_id=tenant_id or user.tenant_id,
        )

    async def explain_permission(
        self,
        user: User,
        action: str,
        resource: str,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Return an auditable explanation for a permission decision."""
        scoped_tenant_id = tenant_id or user.tenant_id
        if await self._is_admin_user(user):
            return {"allowed": True, "reason": "admin"}

        rbac_allowed = await self._has_rbac_permission(user, action, resource)
        if rbac_allowed:
            if await self._has_deny_policy(user, action, resource, scoped_tenant_id):
                return {"allowed": False, "reason": "deny_policy"}
            return {"allowed": True, "reason": "rbac"}

        policy_allowed = await self.policy_service.evaluate_policy(
            user=user,
            action=action,
            resource=resource,
            tenant_id=scoped_tenant_id,
        )
        if policy_allowed:
            return {"allowed": True, "reason": "allow_policy"}

        return {"allowed": False, "reason": "no_grant"}

    async def _is_admin_user(self, user: User) -> bool:
        """Check if user has admin role."""
        roles = await self._get_user_roles(user.id)
        for role in roles:
            perms = role.permissions or {}
            if perms.get("*") or perms.get("admin"):
                return True
        return False

    async def _has_rbac_permission(
        self,
        user: User,
        action: str,
        resource: str,
    ) -> bool:
        """Check if user has RBAC permission for action."""
        roles = await self._get_user_roles(user.id)
        if not roles:
            return False

        for role in roles:
            if self.permissions_allow(role.permissions, action, resource):
                return True

        return False

    def permissions_allow(
        self,
        permissions: dict[str, Any] | None,
        action: str,
        resource: str,
    ) -> bool:
        """Evaluate one role permission payload using the standard RBAC contract."""
        perms = permissions if isinstance(permissions, dict) else {}
        if perms.get("*") or perms.get("admin"):
            return True

        for candidate_resource, candidate_action in self._permission_candidates(action, resource):
            resource_prefix = candidate_resource.split(":")[0]
            for perm_key, perm_value in perms.items():
                if perm_key in {candidate_resource, f"{resource_prefix}:*", "*"} and self._permission_value_allows(
                    perm_value,
                    candidate_action,
                ):
                    return True
        return False

    def _permission_candidates(self, action: str, resource: str) -> list[tuple[str, str]]:
        """Return compatible RBAC pairs for old endpoint checks and new UI grants."""
        candidates: list[tuple[str, str]] = [(resource, action)]

        if "." in action:
            action_resource, action_name = action.split(".", 1)
            candidates.extend([
                (resource, action_name),
                (action_resource, action_name),
            ])

            if action_resource in TEAM_MANAGED_RESOURCES:
                candidates.append(("team", "manage"))

        if resource in TEAM_MANAGED_RESOURCES:
            if action in {"read", "list", "view"}:
                candidates.append(("team", "read"))
            candidates.append(("team", "manage"))

        deduped: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            if candidate not in seen:
                deduped.append(candidate)
                seen.add(candidate)
        return deduped

    def _permission_value_allows(self, permission_value: Any, action: str) -> bool:
        if permission_value is True:
            return True
        if isinstance(permission_value, str):
            return permission_value in {action, "*", "admin"}
        if isinstance(permission_value, list):
            return action in permission_value or "*" in permission_value or "manage" in permission_value
        if isinstance(permission_value, dict):
            return bool(permission_value.get(action) or permission_value.get("*") or permission_value.get("manage"))
        return False

    async def _has_deny_policy(
        self,
        user: User,
        action: str,
        resource: str,
        tenant_id: UUID | None,
    ) -> bool:
        """Check if any deny policy applies to this access."""
        result = await self.db.execute(
            select(Policy).where(
                Policy.tenant_id == tenant_id,
                Policy.effect == "deny",
            )
        )
        policies = list(result.scalars().all())

        for policy in policies:
            # Check if policy applies to this resource
            if not self._policy_matches_resource(policy, resource):
                continue

            # Check if policy applies to this action
            if action not in policy.actions and "*" not in policy.actions:
                continue

            # Check conditions
            if policy.conditions:
                if not self._evaluate_conditions(policy.conditions, user, tenant_id):
                    continue

            return True

        return False

    async def _get_user_roles(self, user_id: UUID) -> list[Role]:
        """Get all roles for a user."""
        result = await self.db.execute(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        return list(result.scalars().all())

    def _policy_matches_resource(self, policy: Policy, resource: str) -> bool:
        """Check if policy resources match the given resource."""
        for policy_resource in policy.resources:
            if policy_resource == "*":
                return True
            if policy_resource.endswith("*"):
                prefix = policy_resource[:-1]
                if resource.startswith(prefix):
                    return True
            if policy_resource == resource:
                return True
        return False

    def _evaluate_conditions(
        self,
        conditions: dict[str, Any],
        user: User,
        tenant_id: UUID | None,
    ) -> bool:
        """Evaluate ABAC conditions against user context."""
        for key, value in conditions.items():
            if key == "tenant_id":
                expected = str(tenant_id)
                actual = str(value).replace("{{tenant_id}}", str(tenant_id))
                if expected != actual:
                    return False
            elif key == "user_id":
                expected = str(user.id)
                actual = str(value).replace("{{user_id}}", str(user.id))
                if expected != actual:
                    return False
            elif key == "is_active":
                if user.is_active != value:
                    return False
        return True

    async def has_field_permission(
        self,
        user: User,
        role: Role,
        resource_type: str,
        field_name: str,
        permission_type: str = "read",
    ) -> bool:
        """Check if user has field-level permission.

        Args:
            user: User to check
            role: Role to check permissions for
            resource_type: Type of resource (e.g., "project", "document")
            field_name: Name of the field being accessed
            permission_type: Type of permission ("read" or "write")

        Returns:
            True if allowed, False otherwise
        """
        # Admin roles have all field permissions
        if role.permissions and role.permissions.get("*"):
            return True

        # Get field permissions for the role
        permissions = await self.field_permission_service.get_field_permissions_for_role(
            role_id=role.id,
            resource_type=resource_type,
            tenant_id=user.tenant_id,
        )

        # Check specific field permission
        for perm in permissions:
            if perm.field_name == field_name:
                if perm.permission == permission_type or perm.permission == "read":
                    return True
                elif perm.permission == "none":
                    return False

        # No explicit permission means allowed
        return True

    async def filter_response_based_on_permissions(
        self,
        user: User,
        response_data: dict[str, Any],
        resource_type: str,
    ) -> dict[str, Any]:
        """Filter response data based on user's field permissions.

        Args:
            user: User to check permissions for
            response_data: Response data dictionary
            resource_type: Type of resource

        Returns:
            Filtered data dictionary with inaccessible fields removed
        """
        # Get user's roles
        roles = await self._get_user_roles(user.id)
        if not roles:
            return response_data

        # Collect all field permissions from all roles
        all_permissions: list[FieldPermission] = []
        for role in roles:
            perms = await self.field_permission_service.get_field_permissions_for_role(
                role_id=role.id,
                resource_type=resource_type,
                tenant_id=user.tenant_id,
            )
            all_permissions.extend(perms)

        # Build permission map (merge permissions, most restrictive wins)
        perm_map: dict[str, str] = {}
        for perm in all_permissions:
            current = perm_map.get(perm.field_name)
            if current is None:
                perm_map[perm.field_name] = perm.permission
            elif current == "none":
                # Already blocked
                perm_map[perm.field_name] = "none"
            elif perm.permission == "none":
                perm_map[perm.field_name] = "none"
            elif current == "read" and perm.permission == "write":
                # Upgrade read to write (more permissive)
                perm_map[perm.field_name] = "write"
            # "read" stays "read" if new is also "read"

        # Filter response data
        filtered = {}
        for field, value in response_data.items():
            perm = perm_map.get(field)
            if perm is None:
                # No explicit permission means allowed
                filtered[field] = value
            elif perm == "read" or perm == "write":
                # Allowed to read
                filtered[field] = value
            # "none" means field is excluded from response

        return filtered

    async def check_tenant_access(
        self,
        user: User,
        target_tenant_id: UUID,
    ) -> bool:
        """Check if user can access resources from a different tenant.

        Args:
            user: User to check
            target_tenant_id: Tenant ID of the target resource

        Returns:
            True if allowed, False otherwise
        """
        # Users can only access their own tenant unless they are admin
        if user.tenant_id == target_tenant_id:
            return True

        # Check if user is admin (global access)
        if await self._is_admin_user(user):
            return True

        return False


def create_permission_evaluator(db: AsyncSession) -> PermissionEvaluator:
    """Factory function to create PermissionEvaluator instance.

    Args:
        db: Async SQLAlchemy session

    Returns:
        PermissionEvaluator instance
    """
    return PermissionEvaluator(db)
