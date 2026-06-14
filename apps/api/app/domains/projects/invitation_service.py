"""Governed invitation preview, account activation, and acceptance."""

from datetime import datetime, timezone
import hashlib
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.domains.identity.schemas import RoleCreate, UserCreate
from app.domains.identity.service import RoleService, UserService
from app.domains.projects.models import ProjectInvitation
from app.domains.projects.schemas import (
    ProjectInvitationAcceptResponse,
    ProjectInvitationActivationRequest,
    ProjectInvitationActivationResponse,
    ProjectInvitationPreviewResponse,
)
from app.models.identity import Role, User, UserRole
from app.models.projects import Project, ProjectMember
from app.services.audit_service import AuditService


PROJECT_MEMBER_ROLE = "project_member"
PROJECT_MEMBER_PERMISSIONS = {
    "projects": ["read"],
    "documents": ["read", "comment"],
    "collaboration": ["read", "write"],
}


class InvitationError(Exception):
    """Expected invitation failure with an HTTP-compatible status."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ProjectInvitationService:
    """Consume invitation tokens without exposing raw tokens or tenant data."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _expired(expires_at: datetime) -> bool:
        normalized = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=timezone.utc)
        return normalized <= datetime.now(timezone.utc)

    @classmethod
    def _status(cls, invitation: ProjectInvitation) -> str:
        if invitation.revoked_at is not None:
            return "revoked"
        if invitation.accepted_at is not None:
            return "accepted"
        if cls._expired(invitation.expires_at):
            return "expired"
        return "active"

    @staticmethod
    def _mask_email(email: str) -> str:
        local, domain = email.split("@", 1)
        if len(local) <= 2:
            masked = local[0] + "*" * max(len(local) - 1, 1)
        else:
            masked = local[0] + "*" * (len(local) - 2) + local[-1]
        return f"{masked}@{domain}"

    async def _find(self, token: str, *, lock: bool = False) -> ProjectInvitation | None:
        query = select(ProjectInvitation).where(
            or_(
                ProjectInvitation.token == self._digest(token),
                ProjectInvitation.token == token,
            ),
            ProjectInvitation.deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update()
        return (await self.db.execute(query)).scalar_one_or_none()

    async def _project(self, invitation: ProjectInvitation) -> Project:
        project = (
            await self.db.execute(
                select(Project).where(
                    Project.id == invitation.project_id,
                    Project.tenant_id == invitation.tenant_id,
                    Project.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not project:
            raise InvitationError(404, "Project not found")
        return project

    async def preview(self, token: str) -> ProjectInvitationPreviewResponse:
        invitation = await self._find(token)
        if not invitation:
            return ProjectInvitationPreviewResponse(status="invalid")
        status = self._status(invitation)
        if status != "active":
            return ProjectInvitationPreviewResponse(status=status)
        project = await self._project(invitation)
        return ProjectInvitationPreviewResponse(
            status="active",
            project_name=project.name,
            masked_email=self._mask_email(invitation.email),
            expires_at=invitation.expires_at,
        )

    async def _active_invitation(self, token: str) -> ProjectInvitation:
        invitation = await self._find(token, lock=True)
        if not invitation:
            raise InvitationError(404, "Invitation not found")
        status = self._status(invitation)
        if status == "revoked":
            raise InvitationError(410, "Invitation has been revoked")
        if status == "accepted":
            raise InvitationError(409, "Invitation has already been accepted")
        if status == "expired":
            raise InvitationError(410, "Invitation has expired")
        return invitation

    async def _member_role(self, tenant_id: UUID) -> Role:
        role = (
            await self.db.execute(
                select(Role).where(
                    Role.tenant_id == tenant_id,
                    Role.name == PROJECT_MEMBER_ROLE,
                ).order_by(Role.created_at.asc()).limit(1)
            )
        ).scalar_one_or_none()
        if role:
            return role
        return await RoleService(self.db).create_role(
            RoleCreate(
                name=PROJECT_MEMBER_ROLE,
                description="Least-privilege role for invited project members",
                permissions=PROJECT_MEMBER_PERMISSIONS,
            ),
            tenant_id,
        )

    async def _add_membership(self, invitation: ProjectInvitation, user: User, role: Role) -> None:
        user_role = (
            await self.db.execute(
                select(UserRole).where(
                    UserRole.user_id == user.id,
                    UserRole.role_id == role.id,
                )
            )
        ).scalar_one_or_none()
        if not user_role:
            self.db.add(UserRole(user_id=user.id, role_id=role.id))

        membership = (
            await self.db.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == invitation.project_id,
                    ProjectMember.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if not membership:
            self.db.add(
                ProjectMember(
                    project_id=invitation.project_id,
                    user_id=user.id,
                    role_id=role.id,
                )
            )
        elif membership.role_id is None:
            membership.role_id = role.id

    async def _accept(self, invitation: ProjectInvitation, user: User, project: Project) -> ProjectInvitationAcceptResponse:
        role = await self._member_role(invitation.tenant_id)
        await self._add_membership(invitation, user, role)
        invitation.accepted_at = datetime.now(timezone.utc)
        await self.db.flush()
        await AuditService(self.db).log_action(
            tenant_id=invitation.tenant_id,
            user_id=user.id,
            action="project.invitation.accept",
            resource_type="project_invitation",
            resource_id=invitation.id,
            metadata={"project_id": str(project.id), "email": invitation.email},
        )
        return ProjectInvitationAcceptResponse(
            project_id=project.id,
            project_name=project.name,
            user_id=user.id,
            status="accepted",
        )

    async def accept(self, token: str, current_user: User) -> ProjectInvitationAcceptResponse:
        invitation = await self._active_invitation(token)
        if invitation.tenant_id != current_user.tenant_id:
            raise InvitationError(403, "Invitation belongs to another tenant")
        if invitation.email.casefold() != current_user.email.casefold():
            raise InvitationError(403, "Invitation email does not match signed-in user")
        project = await self._project(invitation)
        return await self._accept(invitation, current_user, project)

    async def activate(
        self,
        token: str,
        data: ProjectInvitationActivationRequest,
    ) -> ProjectInvitationActivationResponse:
        invitation = await self._active_invitation(token)
        project = await self._project(invitation)
        normalized_email = invitation.email.casefold()
        existing = (
            await self.db.execute(
                select(User).where(
                    func.lower(User.email) == normalized_email,
                    User.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing:
            if existing.tenant_id == invitation.tenant_id:
                raise InvitationError(409, "Existing account must sign in to accept this invitation")
            raise InvitationError(409, "Email belongs to another tenant")

        user = await UserService(self.db).create_user(
            UserCreate(
                email=normalized_email,
                full_name=data.full_name,
                password=data.password,
                tenant_id=invitation.tenant_id,
            )
        )
        accepted = await self._accept(invitation, user, project)
        await AuditService(self.db).log_action(
            tenant_id=invitation.tenant_id,
            user_id=user.id,
            action="project.invitation.activate",
            resource_type="project_invitation",
            resource_id=invitation.id,
            metadata={"project_id": str(project.id), "email": invitation.email},
        )
        access_token = create_access_token(
            {
                "sub": str(user.id),
                "email": user.email,
                "tenant_id": str(user.tenant_id),
            }
        )
        return ProjectInvitationActivationResponse(
            **accepted.model_dump(),
            access_token=access_token,
        )
