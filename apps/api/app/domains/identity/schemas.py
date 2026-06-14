"""Identity Domain Schemas

Pydantic v2 schemas for request/response validation.
"""

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# Generic type for paginated responses
T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response schema."""

    items: list[T]
    total: int
    page: int
    page_size: int
    has_more: bool


# Tenant Schemas
class TenantBase(BaseModel):
    """Base tenant schema."""

    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100)


class TenantCreate(TenantBase):
    """Schema for creating a tenant."""

    pass


class TenantUpdate(BaseModel):
    """Schema for updating a tenant."""

    name: str | None = Field(None, min_length=1, max_length=255)
    slug: str | None = Field(None, min_length=1, max_length=100)


class TenantResponse(TenantBase):
    """Schema for tenant response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


# User Schemas
class UserBase(BaseModel):
    """Base user schema."""

    email: EmailStr
    full_name: str | None = Field(None, max_length=255)
    is_active: bool = True


class UserCreate(UserBase):
    """Schema for creating a user."""

    password: str = Field(..., min_length=8, max_length=100)
    tenant_id: UUID | None = None


class UserUpdate(BaseModel):
    """Schema for updating a user."""

    email: EmailStr | None = None
    full_name: str | None = Field(None, max_length=255)
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8, max_length=100)


# Role Schemas
class RoleBase(BaseModel):
    """Base role schema."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)


class RoleCreate(RoleBase):
    """Schema for creating a role."""

    permissions: dict[str, Any] = Field(default_factory=dict)


class RoleUpdate(BaseModel):
    """Schema for updating a role."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    permissions: dict[str, Any] | None = None


class RoleResponse(RoleBase):
    """Schema for role response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    permissions: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class UserResponse(UserBase):
    """Schema for user response (excludes password)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    roles: list[RoleResponse] = Field(default_factory=list, validation_alias="role_responses")
    created_at: datetime
    updated_at: datetime


class AssignRoleRequest(BaseModel):
    """Schema for assigning a role to a user."""

    user_id: UUID
    role_id: UUID


# Policy Schemas
class PolicyBase(BaseModel):
    """Base policy schema."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    effect: str = Field(..., pattern="^(allow|deny)$")
    actions: list[str] = Field(..., min_length=1)
    resources: list[str] = Field(..., min_length=1)
    conditions: dict[str, Any] = Field(default_factory=dict)


class PolicyCreate(PolicyBase):
    """Schema for creating a policy."""

    pass


class PolicyUpdate(BaseModel):
    """Schema for updating a policy."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    effect: str | None = Field(None, pattern="^(allow|deny)$")
    actions: list[str] | None = None
    resources: list[str] | None = None
    conditions: dict[str, Any] | None = None


class PolicyResponse(PolicyBase):
    """Schema for policy response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    created_at: datetime
    updated_at: datetime


# Field Permission Schemas
class FieldPermissionBase(BaseModel):
    """Base field permission schema."""

    role_id: UUID
    resource_type: str = Field(..., min_length=1, max_length=100)
    field_name: str = Field(..., min_length=1, max_length=100)
    permission: str = Field(..., pattern="^(read|write|none)$")


class FieldPermissionCreate(FieldPermissionBase):
    """Schema for creating a field permission."""

    pass


class FieldPermissionUpdate(BaseModel):
    """Schema for updating a field permission."""

    permission: str = Field(..., pattern="^(read|write|none)$")


class FieldPermissionResponse(FieldPermissionBase):
    """Schema for field permission response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    created_at: datetime
    updated_at: datetime


class PermissionDiagnosticCheck(BaseModel):
    """One current-user permission diagnostic decision."""

    key: str
    label: str
    resource: str
    action: str
    allowed: bool
    reason: str


class PermissionDiagnosticFieldControl(BaseModel):
    """Field-level restriction evidence for one role."""

    role_id: UUID
    role_name: str
    resource_type: str
    field_name: str
    permission: str


class PermissionDiagnosticPolicyEvidence(BaseModel):
    """Policy evidence relevant to the permission center."""

    id: UUID
    name: str
    effect: str
    actions: list[str]
    resources: list[str]


class PermissionDiagnosticsResponse(BaseModel):
    """Current-user permission diagnostic summary."""

    generated_at: datetime
    tenant_id: UUID | None
    user_id: UUID
    summary: dict[str, int]
    checks: list[PermissionDiagnosticCheck]
    field_controls: list[PermissionDiagnosticFieldControl]
    policy_evidence: list[PermissionDiagnosticPolicyEvidence]


class PermissionCommandCenterReleaseGate(BaseModel):
    """Release gate for tenant team-access governance."""

    status: str
    label: str
    summary: str
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PermissionCommandCenterRiskItem(BaseModel):
    """Actionable permission governance risk."""

    code: str
    severity: str
    title: str
    detail: str
    count: int
    href: str


class PermissionCommandCenterPriorityAction(BaseModel):
    """Priority action for closing team permission governance."""

    code: str
    title: str
    description: str
    href: str
    priority: str


class PermissionCommandCenterResponse(BaseModel):
    """Aggregated team permission command center payload."""

    generated_at: datetime
    tenant_id: UUID | None
    release_gate: PermissionCommandCenterReleaseGate
    summary: dict[str, int]
    risk_items: list[PermissionCommandCenterRiskItem]
    priority_actions: list[PermissionCommandCenterPriorityAction]
    diagnostic_snapshot: dict[str, int]
    recent_audit_actions: list[str] = Field(default_factory=list)


class PermissionSimulationRequest(BaseModel):
    """Request a tenant-scoped permission decision for one member."""

    user_id: UUID
    resource: str = Field(..., min_length=1, max_length=100)
    action: str = Field(..., min_length=1, max_length=100)
    resource_type: str | None = Field(None, min_length=1, max_length=100)
    field_name: str | None = Field(None, min_length=1, max_length=100)


class PermissionSimulationRoleEvidence(BaseModel):
    """Role evidence used to understand a simulated permission decision."""

    id: UUID
    name: str
    description: str | None
    permissions: dict[str, Any]


class PermissionSimulationResponse(BaseModel):
    """Auditable result for one simulated permission decision."""

    generated_at: datetime
    tenant_id: UUID | None
    requested_by_user_id: UUID
    target_user_id: UUID
    target_user_email: EmailStr
    target_user_name: str | None
    resource: str
    action: str
    allowed: bool
    reason: str
    roles: list[PermissionSimulationRoleEvidence]
    field_controls: list[PermissionDiagnosticFieldControl]
    policy_evidence: list[PermissionDiagnosticPolicyEvidence]


# Tenant API Key Schemas
class TenantApiKeyCreate(BaseModel):
    """Create a tenant-scoped API key."""

    name: str = Field(..., min_length=1, max_length=255)
    permissions: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class TenantApiKeyResponse(BaseModel):
    """API key metadata response without plaintext secret."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    name: str
    key_prefix: str
    permissions: list[str]
    status: str
    created_by_id: UUID | None
    revoked_by_id: UUID | None
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TenantApiKeyCreateResponse(TenantApiKeyResponse):
    """Create response with the plaintext secret shown once."""

    api_key: str


# Auth Schemas
class LoginRequest(BaseModel):
    """Schema for login request."""

    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """Schema for login response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class PasswordChangeRequest(BaseModel):
    """Authenticated password-change request."""

    current_password: str
    new_password: str = Field(..., min_length=8, max_length=100)


class AccountDeactivateRequest(BaseModel):
    """Authenticated self-deactivation request."""

    current_password: str


class AccountSecurityResponse(BaseModel):
    """Current account security lifecycle state."""

    security_version: int
    password_changed_at: datetime | None
    last_login_at: datetime | None
    active: bool
    recent_events: list["AuditLogResponse"] = Field(default_factory=list)


class AuthMeResponse(BaseModel):
    """Schema for auth me response."""

    id: UUID
    email: EmailStr
    full_name: str | None
    tenant_id: UUID | None
    is_active: bool
    roles: list[RoleResponse]


# Audit Log Schemas
class AuditLogResponse(BaseModel):
    """Schema for audit log response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    user_id: UUID | None
    action: str
    resource_type: str | None
    resource_id: UUID | None
    extra_data: dict[str, Any] | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime


class AuditLogFilter(BaseModel):
    """Schema for audit log filtering."""

    tenant_id: UUID | None = None
    user_id: UUID | None = None
    action: str | None = None
    resource_type: str | None = None
    resource_id: UUID | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)
