"""Team access API regression tests."""

import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-identity-team-access-secret"

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.init_schema  # noqa: F401 - registers sqlite compilers for UUID/JSONB
import app.models.identity  # noqa: F401 - registers tenant/user/role tables
import app.models.projects  # noqa: F401 - resolves User.owned_projects relationship
from app.core.security import verify_password
from app.db.base import Base
from app.db.init_schema import deduplicate_indexes
from app.domains.identity.models import AuditLog, TenantApiKey
from app.domains.identity.router import create_user, get_permission_command_center, get_permission_diagnostics, list_audit_logs, list_users, simulate_permission_decision
from app.domains.identity.schemas import FieldPermissionCreate, PermissionSimulationRequest, PolicyCreate, PolicyUpdate, TenantApiKeyCreate, UserCreate
from app.domains.identity.service import FieldPermissionService, PolicyService, TenantApiKeyService
from app.services.permission_evaluator import PermissionEvaluator
from app.models.identity import Role, Tenant, User, UserRole


class StubRequest:
    client = None
    headers = {}


@pytest.fixture
async def db_session():
    deduplicate_indexes()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_list_users_returns_assigned_roles_for_team_permission_center(db_session):
    tenant_id = uuid4()
    admin_id = uuid4()
    member_id = uuid4()
    admin_role_id = uuid4()
    role_id = uuid4()

    tenant = Tenant(id=tenant_id, name="Team Tenant", slug="team-tenant")
    admin = User(
        id=admin_id,
        tenant_id=tenant_id,
        email="admin@example.com",
        full_name="Admin",
        hashed_password="hashed",
    )
    member = User(
        id=member_id,
        tenant_id=tenant_id,
        email="member@example.com",
        full_name="Member",
        hashed_password="hashed",
    )
    role = Role(
        id=role_id,
        tenant_id=tenant_id,
        name="Reviewer",
        description="Can review documents",
        permissions={"documents": ["read", "review"]},
    )
    admin_role = Role(
        id=admin_role_id,
        tenant_id=tenant_id,
        name="Team Reader",
        description="Can read team access data",
        permissions={"team": ["read"]},
    )

    db_session.add_all([
        tenant,
        admin,
        member,
        role,
        admin_role,
        UserRole(user_id=admin_id, role_id=admin_role_id),
        UserRole(user_id=member_id, role_id=role_id),
    ])
    await db_session.flush()

    response = await list_users(user=admin, db=db_session, skip=0, limit=50)

    member_response = next(item for item in response.items if item.id == member_id)
    assert [role.name for role in member_response.roles] == ["Reviewer"]
    assert member_response.roles[0].permissions == {"documents": ["read", "review"]}


@pytest.mark.asyncio
async def test_create_user_returns_conflict_when_email_already_exists(db_session):
    tenant_id = uuid4()
    admin_id = uuid4()
    role_id = uuid4()

    db_session.add_all([
        Tenant(id=tenant_id, name="Conflict Tenant", slug="conflict-tenant"),
        User(
            id=admin_id,
            tenant_id=tenant_id,
            email="admin@example.com",
            full_name="Admin",
            hashed_password="hashed",
        ),
        User(
            tenant_id=tenant_id,
            email="houseguy@163.com",
            full_name="Existing Member",
            hashed_password="hashed",
        ),
        Role(
            id=role_id,
            tenant_id=tenant_id,
            name="Team Manager",
            permissions={"team": ["manage"]},
        ),
        UserRole(user_id=admin_id, role_id=role_id),
    ])
    await db_session.flush()
    admin = await db_session.get(User, admin_id)

    with pytest.raises(HTTPException) as error:
        await create_user(
            data=UserCreate(
                email="houseguy@163.com",
                full_name="Duplicate Member",
                password="temporary-password",
            ),
            user=admin,
            db=db_session,
            request=StubRequest(),
        )

    assert error.value.status_code == 409
    assert error.value.detail == "该邮箱已存在，请使用其他邮箱或管理现有成员"


@pytest.mark.asyncio
async def test_create_user_without_password_returns_server_generated_temporary_password(db_session):
    tenant_id = uuid4()
    admin_id = uuid4()
    role_id = uuid4()

    db_session.add_all([
        Tenant(id=tenant_id, name="Temporary Password Tenant", slug="temporary-password-tenant"),
        User(
            id=admin_id,
            tenant_id=tenant_id,
            email="admin@example.com",
            full_name="Admin",
            hashed_password="hashed",
        ),
        Role(
            id=role_id,
            tenant_id=tenant_id,
            name="Team Manager",
            permissions={"team": ["manage"]},
        ),
        UserRole(user_id=admin_id, role_id=role_id),
    ])
    await db_session.flush()
    admin = await db_session.get(User, admin_id)

    response = await create_user(
        data=UserCreate(
            email="new.member@example.com",
            full_name="New Member",
        ),
        user=admin,
        db=db_session,
        request=StubRequest(),
    )

    temporary_password = response.temporary_password
    assert isinstance(temporary_password, str)
    assert len(temporary_password) >= 24
    assert "2026" not in temporary_password

    created_user = await db_session.scalar(select(User).where(User.email == "new.member@example.com"))
    assert created_user is not None
    assert created_user.hashed_password != temporary_password
    assert verify_password(temporary_password, created_user.hashed_password)

    users = await list_users(user=admin, db=db_session, skip=0, limit=50)
    created_response = next(item for item in users.items if item.email == "new.member@example.com")
    assert not hasattr(created_response, "temporary_password")


@pytest.mark.asyncio
async def test_team_manage_permission_satisfies_legacy_role_assignment_check(db_session):
    tenant_id = uuid4()
    admin_id = uuid4()
    role_id = uuid4()

    db_session.add_all([
        Tenant(id=tenant_id, name="Permission Tenant", slug="permission-tenant"),
        User(
            id=admin_id,
            tenant_id=tenant_id,
            email="admin@example.com",
            full_name="Admin",
            hashed_password="hashed",
        ),
        Role(
            id=role_id,
            tenant_id=tenant_id,
            name="Team Manager",
            description="Can manage tenant team permissions",
            permissions={"team": ["manage"]},
        ),
        UserRole(user_id=admin_id, role_id=role_id),
    ])
    await db_session.flush()

    admin = await db_session.get(User, admin_id)
    evaluator = PermissionEvaluator(db_session)

    assert await evaluator.has_permission(admin, "manage", "team", tenant_id) is True
    assert await evaluator.has_permission(admin, "roles.assign", "roles", tenant_id) is True


def test_permission_evaluator_applies_standard_contract_to_project_role_payload():
    evaluator = PermissionEvaluator(None)

    assert evaluator.permissions_allow(
        {"documents": ["review", "approve", "publish"]},
        "approve",
        "documents",
    ) is True
    assert evaluator.permissions_allow(
        {"documents": ["review"]},
        "publish",
        "documents",
    ) is False
    assert evaluator.permissions_allow({"*": True}, "archive", "documents") is True


@pytest.mark.asyncio
async def test_permission_diagnostics_surfaces_rbac_abac_and_field_evidence(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    role_id = uuid4()

    db_session.add_all([
        Tenant(id=tenant_id, name="Diagnostics Tenant", slug="diagnostics-tenant"),
        User(
            id=user_id,
            tenant_id=tenant_id,
            email="diagnostics@example.com",
            full_name="Diagnostics User",
            hashed_password="hashed",
        ),
        Role(
            id=role_id,
            tenant_id=tenant_id,
            name="Delivery Reviewer",
            description="Can review delivery documents and read team evidence",
            permissions={"team": ["read"], "documents": ["read", "review", "export"], "projects": ["read"]},
        ),
        UserRole(user_id=user_id, role_id=role_id),
    ])
    await db_session.flush()

    await PolicyService(db_session).create_policy(
        PolicyCreate(
            name="Draft export deny",
            description="Draft documents must not enter delivery packages",
            effect="deny",
            actions=["export"],
            resources=["documents"],
            conditions={"tenant_id": "{{tenant_id}}"},
        ),
        tenant_id=tenant_id,
    )
    await FieldPermissionService(db_session).set_field_permission(
        FieldPermissionCreate(
            role_id=role_id,
            resource_type="document",
            field_name="commercial_terms",
            permission="none",
        ),
        tenant_id=tenant_id,
    )

    user = await db_session.get(User, user_id)
    response = await get_permission_diagnostics(user=user, db=db_session)

    checks = {item.key: item for item in response.checks}
    assert checks["projects.read"].allowed is True
    assert checks["team.read"].allowed is True
    assert checks["team.manage"].allowed is False
    assert checks["documents.export"].allowed is False
    assert checks["documents.export"].reason == "deny_policy"
    assert response.summary["allowed"] == 3
    assert response.summary["denied"] == 3
    assert response.field_controls[0].field_name == "commercial_terms"
    assert response.field_controls[0].permission == "none"


@pytest.mark.asyncio
async def test_permission_command_center_blocks_release_for_unassigned_users_and_deny_policies(db_session):
    tenant_id = uuid4()
    admin_id = uuid4()
    reviewer_id = uuid4()
    unassigned_id = uuid4()
    admin_role_id = uuid4()
    reviewer_role_id = uuid4()

    db_session.add_all([
        Tenant(id=tenant_id, name="Governance Tenant", slug="governance-tenant"),
        User(
            id=admin_id,
            tenant_id=tenant_id,
            email="admin@example.com",
            full_name="Admin",
            hashed_password="hashed",
        ),
        User(
            id=reviewer_id,
            tenant_id=tenant_id,
            email="reviewer@example.com",
            full_name="Reviewer",
            hashed_password="hashed",
        ),
        User(
            id=unassigned_id,
            tenant_id=tenant_id,
            email="unassigned@example.com",
            full_name="Unassigned",
            hashed_password="hashed",
        ),
        Role(
            id=admin_role_id,
            tenant_id=tenant_id,
            name="Team Admin",
            description="Can manage permissions",
            permissions={"team": ["read", "manage"], "documents": ["publish", "export"]},
        ),
        Role(
            id=reviewer_role_id,
            tenant_id=tenant_id,
            name="Reviewer",
            description="Can review documents",
            permissions={"team": ["read"], "documents": ["read", "review"]},
        ),
        UserRole(user_id=admin_id, role_id=admin_role_id),
        UserRole(user_id=reviewer_id, role_id=reviewer_role_id),
        AuditLog(
            tenant_id=tenant_id,
            user_id=admin_id,
            action="team.role_assigned",
            resource_type="role",
            resource_id=reviewer_role_id,
        ),
    ])
    await db_session.flush()

    await PolicyService(db_session).create_policy(
        PolicyCreate(
            name="Draft export deny",
            description="Draft documents must not enter delivery packages",
            effect="deny",
            actions=["export"],
            resources=["documents"],
            conditions={"tenant_id": "{{tenant_id}}"},
        ),
        tenant_id=tenant_id,
    )
    await FieldPermissionService(db_session).set_field_permission(
        FieldPermissionCreate(
            role_id=reviewer_role_id,
            resource_type="document",
            field_name="commercial_terms",
            permission="none",
        ),
        tenant_id=tenant_id,
    )

    admin = await db_session.get(User, admin_id)
    response = await get_permission_command_center(user=admin, db=db_session)

    assert response.release_gate.status == "blocked"
    assert response.summary["total_users"] == 3
    assert response.summary["users_without_roles"] == 1
    assert response.summary["deny_policy_count"] == 1
    assert response.summary["field_restricted_count"] == 1
    assert response.summary["high_privilege_roles"] == 1
    assert response.summary["audit_log_count"] == 1
    assert {item.code for item in response.risk_items} >= {
        "users_without_roles",
        "deny_policies",
        "field_restrictions",
    }
    assert response.priority_actions[0].href == "/team"
    assert response.diagnostic_snapshot["denied"] >= 1


@pytest.mark.asyncio
async def test_permission_simulation_returns_decision_evidence_and_audit_log(db_session):
    tenant_id = uuid4()
    admin_id = uuid4()
    target_user_id = uuid4()
    admin_role_id = uuid4()
    delivery_role_id = uuid4()

    db_session.add_all([
        Tenant(id=tenant_id, name="Simulation Tenant", slug="simulation-tenant"),
        User(
            id=admin_id,
            tenant_id=tenant_id,
            email="admin@example.com",
            full_name="Admin",
            hashed_password="hashed",
        ),
        User(
            id=target_user_id,
            tenant_id=tenant_id,
            email="consultant@example.com",
            full_name="Consultant",
            hashed_password="hashed",
        ),
        Role(
            id=admin_role_id,
            tenant_id=tenant_id,
            name="Team Reader",
            description="Can inspect team permissions",
            permissions={"team": ["read"]},
        ),
        Role(
            id=delivery_role_id,
            tenant_id=tenant_id,
            name="Delivery Exporter",
            description="Can export approved documents",
            permissions={"documents": ["read", "export"]},
        ),
        UserRole(user_id=admin_id, role_id=admin_role_id),
        UserRole(user_id=target_user_id, role_id=delivery_role_id),
    ])
    await db_session.flush()

    await PolicyService(db_session).create_policy(
        PolicyCreate(
            name="Block draft package export",
            description="Export is blocked until delivery readiness is proven",
            effect="deny",
            actions=["export"],
            resources=["documents"],
            conditions={"tenant_id": "{{tenant_id}}"},
        ),
        tenant_id=tenant_id,
    )
    await FieldPermissionService(db_session).set_field_permission(
        FieldPermissionCreate(
            role_id=delivery_role_id,
            resource_type="document",
            field_name="commercial_terms",
            permission="none",
        ),
        tenant_id=tenant_id,
    )

    admin = await db_session.get(User, admin_id)
    response = await simulate_permission_decision(
        data=PermissionSimulationRequest(
            user_id=target_user_id,
            resource="documents",
            action="export",
            resource_type="document",
            field_name="commercial_terms",
        ),
        user=admin,
        db=db_session,
    )

    assert response.target_user_id == target_user_id
    assert response.allowed is False
    assert response.reason == "deny_policy"
    assert response.roles[0].name == "Delivery Exporter"
    assert response.policy_evidence[0].name == "Block draft package export"
    assert response.field_controls[0].field_name == "commercial_terms"
    assert response.field_controls[0].permission == "none"

    audit_log = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "permission.simulate",
            AuditLog.resource_id == target_user_id,
        )
    )
    assert audit_log is not None
    assert audit_log.extra_data["reason"] == "deny_policy"


@pytest.mark.asyncio
async def test_permission_simulation_rejects_cross_tenant_target_user(db_session):
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    admin_id = uuid4()
    target_user_id = uuid4()
    admin_role_id = uuid4()

    db_session.add_all([
        Tenant(id=tenant_id, name="Simulation Tenant", slug="simulation-tenant"),
        Tenant(id=other_tenant_id, name="Other Simulation Tenant", slug="other-simulation-tenant"),
        User(
            id=admin_id,
            tenant_id=tenant_id,
            email="admin@example.com",
            full_name="Admin",
            hashed_password="hashed",
        ),
        User(
            id=target_user_id,
            tenant_id=other_tenant_id,
            email="other@example.com",
            full_name="Other User",
            hashed_password="hashed",
        ),
        Role(
            id=admin_role_id,
            tenant_id=tenant_id,
            name="Team Reader",
            description="Can inspect team permissions",
            permissions={"team": ["read"]},
        ),
        UserRole(user_id=admin_id, role_id=admin_role_id),
    ])
    await db_session.flush()

    admin = await db_session.get(User, admin_id)
    with pytest.raises(Exception) as exc_info:
        await simulate_permission_decision(
            data=PermissionSimulationRequest(
                user_id=target_user_id,
                resource="documents",
                action="read",
            ),
            user=admin,
            db=db_session,
        )

    assert getattr(exc_info.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_list_users_rejects_user_without_team_permission(db_session):
    tenant_id = uuid4()
    user_id = uuid4()

    tenant = Tenant(id=tenant_id, name="Restricted Tenant", slug="restricted-tenant")
    user = User(
        id=user_id,
        tenant_id=tenant_id,
        email="user@example.com",
        full_name="User",
        hashed_password="hashed",
    )
    db_session.add_all([tenant, user])
    await db_session.flush()

    with pytest.raises(Exception) as exc_info:
        await list_users(user=user, db=db_session, skip=0, limit=50)

    assert getattr(exc_info.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_team_reader_can_list_only_own_tenant_audit_logs(db_session):
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    user_id = uuid4()
    role_id = uuid4()

    db_session.add_all([
        Tenant(id=tenant_id, name="Audit Tenant", slug="audit-tenant"),
        Tenant(id=other_tenant_id, name="Other Audit Tenant", slug="other-audit-tenant"),
        User(
            id=user_id,
            tenant_id=tenant_id,
            email="auditor@example.com",
            full_name="Auditor",
            hashed_password="hashed",
        ),
        Role(
            id=role_id,
            tenant_id=tenant_id,
            name="Team Reader",
            description="Can read tenant team audit logs",
            permissions={"team": ["read"]},
        ),
        UserRole(user_id=user_id, role_id=role_id),
        AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action="role.assign",
            resource_type="role",
            resource_id=role_id,
        ),
        AuditLog(
            tenant_id=other_tenant_id,
            user_id=user_id,
            action="role.assign",
            resource_type="role",
            resource_id=role_id,
        ),
    ])
    await db_session.flush()

    user = await db_session.get(User, user_id)
    response = await list_audit_logs(
        user=user,
        db=db_session,
        tenant_id=None,
        user_id=None,
        action=None,
        resource_type=None,
        resource_id=None,
        start_date=None,
        end_date=None,
        page=1,
        page_size=50,
    )

    assert response.total == 1
    assert response.items[0].tenant_id == tenant_id

    with pytest.raises(Exception) as exc_info:
        await list_audit_logs(
            user=user,
            db=db_session,
            tenant_id=other_tenant_id,
            user_id=None,
            action=None,
            resource_type=None,
            resource_id=None,
            start_date=None,
            end_date=None,
            page=1,
            page_size=50,
        )

    assert getattr(exc_info.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_role_service_rejects_cross_tenant_role_assignment(db_session):
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    admin_id = uuid4()
    member_id = uuid4()
    role_id = uuid4()

    db_session.add_all([
        Tenant(id=tenant_id, name="Team Tenant", slug="team-tenant"),
        Tenant(id=other_tenant_id, name="Other Tenant", slug="other-tenant"),
        User(
            id=admin_id,
            tenant_id=tenant_id,
            email="admin@example.com",
            full_name="Admin",
            hashed_password="hashed",
        ),
        User(
            id=member_id,
            tenant_id=other_tenant_id,
            email="member@example.com",
            full_name="Member",
            hashed_password="hashed",
        ),
        Role(
            id=role_id,
            tenant_id=tenant_id,
            name="Tenant Admin",
            description="Tenant scoped admin",
            permissions={"team": ["manage"]},
        ),
    ])
    await db_session.flush()

    from app.domains.identity.service import RoleService

    assigned = await RoleService(db_session).assign_role_to_user(
        user_id=member_id,
        role_id=role_id,
        tenant_id=tenant_id,
    )

    assignments = await db_session.execute(
        UserRole.__table__.select().where(
            UserRole.user_id == member_id,
            UserRole.role_id == role_id,
        )
    )
    assert assigned is False
    assert assignments.first() is None


@pytest.mark.asyncio
async def test_role_service_revokes_role_and_blocks_deleting_assigned_role(db_session):
    tenant_id = uuid4()
    member_id = uuid4()
    assigned_role_id = uuid4()
    unused_role_id = uuid4()

    db_session.add_all([
        Tenant(id=tenant_id, name="Role Tenant", slug="role-tenant"),
        User(
            id=member_id,
            tenant_id=tenant_id,
            email="member@example.com",
            full_name="Member",
            hashed_password="hashed",
        ),
        Role(
            id=assigned_role_id,
            tenant_id=tenant_id,
            name="Reviewer",
            description="Assigned role",
            permissions={"documents": ["review"]},
        ),
        Role(
            id=unused_role_id,
            tenant_id=tenant_id,
            name="Unused",
            description="Unused role",
            permissions={"documents": ["read"]},
        ),
        UserRole(user_id=member_id, role_id=assigned_role_id),
    ])
    await db_session.flush()

    from app.domains.identity.service import RoleService

    service = RoleService(db_session)

    assert await service.delete_role(assigned_role_id, tenant_id=tenant_id) is False
    assert await service.revoke_role_from_user(member_id, assigned_role_id, tenant_id=tenant_id) is True
    assert await service.revoke_role_from_user(member_id, assigned_role_id, tenant_id=tenant_id) is True
    assert await service.delete_role(unused_role_id, tenant_id=tenant_id) is True


@pytest.mark.asyncio
async def test_policy_service_updates_policy_for_team_permission_center(db_session):
    tenant_id = uuid4()
    db_session.add(Tenant(id=tenant_id, name="Policy Tenant", slug="policy-tenant"))
    await db_session.flush()

    service = PolicyService(db_session)
    policy = await service.create_policy(
        PolicyCreate(
            name="Tenant scoped access",
            description="Allow current tenant access",
            effect="allow",
            actions=["read"],
            resources=["documents:*"],
            conditions={"tenant_id": "{{tenant_id}}"},
        ),
        tenant_id=tenant_id,
    )

    updated = await service.update_policy(
        policy.id,
        PolicyUpdate(effect="deny", actions=["export"], resources=["documents:draft"]),
        tenant_id=tenant_id,
    )

    assert updated is not None
    assert updated.effect == "deny"
    assert updated.actions == ["export"]
    assert updated.resources == ["documents:draft"]


@pytest.mark.asyncio
async def test_field_permission_service_upserts_role_field_permission(db_session):
    tenant_id = uuid4()
    role_id = uuid4()
    db_session.add_all([
        Tenant(id=tenant_id, name="Field Tenant", slug="field-tenant"),
        Role(
            id=role_id,
            tenant_id=tenant_id,
            name="Consultant",
            description="Field controlled role",
            permissions={"documents": ["read"]},
        ),
    ])
    await db_session.flush()

    service = FieldPermissionService(db_session)
    created = await service.set_field_permission(
        FieldPermissionCreate(
            role_id=role_id,
            resource_type="document",
            field_name="commercial_terms",
            permission="read",
        ),
        tenant_id=tenant_id,
    )
    updated = await service.set_field_permission(
        FieldPermissionCreate(
            role_id=role_id,
            resource_type="document",
            field_name="commercial_terms",
            permission="none",
        ),
        tenant_id=tenant_id,
    )

    permissions = await service.get_field_permissions_for_role(
        role_id=role_id,
        resource_type="document",
        tenant_id=tenant_id,
    )

    assert created.id == updated.id
    assert len(permissions) == 1
    assert permissions[0].permission == "none"


@pytest.mark.asyncio
async def test_field_permission_service_rejects_cross_tenant_role(db_session):
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    role_id = uuid4()
    db_session.add_all([
        Tenant(id=tenant_id, name="Field Tenant", slug="field-tenant"),
        Tenant(id=other_tenant_id, name="Other Field Tenant", slug="other-field-tenant"),
        Role(
            id=role_id,
            tenant_id=other_tenant_id,
            name="Other Tenant Role",
            description="Must not be editable from another tenant",
            permissions={"documents": ["read"]},
        ),
    ])
    await db_session.flush()

    service = FieldPermissionService(db_session)

    with pytest.raises(ValueError, match="Role not found"):
        await service.set_field_permission(
            FieldPermissionCreate(
                role_id=role_id,
                resource_type="document",
                field_name="commercial_terms",
                permission="none",
            ),
            tenant_id=tenant_id,
        )


@pytest.mark.asyncio
async def test_tenant_api_key_service_creates_lists_and_revokes_audited_keys(db_session):
    tenant_id = uuid4()
    user_id = uuid4()
    role_id = uuid4()
    db_session.add_all([
        Tenant(id=tenant_id, name="API Key Tenant", slug="api-key-tenant"),
        User(
            id=user_id,
            tenant_id=tenant_id,
            email="api-admin@example.com",
            full_name="API Admin",
            hashed_password="hashed",
        ),
        Role(
            id=role_id,
            tenant_id=tenant_id,
            name="Team Manager",
            description="Can manage tenant API keys",
            permissions={"team": ["manage"]},
        ),
        UserRole(user_id=user_id, role_id=role_id),
    ])
    await db_session.flush()

    service = TenantApiKeyService(db_session)
    created, plain_key = await service.create_api_key(
        TenantApiKeyCreate(
            name="GitNexus Provider 联调",
            permissions=["providers:read", "providers:write", "audit:read"],
        ),
        tenant_id=tenant_id,
        created_by_id=user_id,
    )

    assert plain_key.startswith("amx_")
    assert created.key_prefix == plain_key[:12]
    assert created.key_hash != plain_key
    assert created.status == "active"

    listed, total = await service.list_api_keys(tenant_id=tenant_id)
    assert total == 1
    assert listed[0].name == "GitNexus Provider 联调"
    assert listed[0].key_prefix == plain_key[:12]
    assert listed[0].permissions == ["providers:read", "providers:write", "audit:read"]

    verified = await service.verify_api_key(plain_key)
    assert verified is not None
    assert verified.id == created.id

    assert await service.revoke_api_key(created.id, tenant_id=tenant_id, revoked_by_id=user_id) is True
    assert await service.verify_api_key(plain_key) is None

    stored = await db_session.get(TenantApiKey, created.id)
    assert stored.status == "revoked"
    assert stored.revoked_by_id == user_id
    assert stored.revoked_at is not None

    audit_logs = list(
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.resource_type == "api_key",
                ).order_by(AuditLog.created_at, AuditLog.action)
            )
        ).scalars()
    )
    assert {log.action for log in audit_logs} == {"api_key.create", "api_key.revoke"}
    assert all(plain_key not in str(log.extra_data) for log in audit_logs)
    create_log = next(log for log in audit_logs if log.action == "api_key.create")
    assert create_log.extra_data["key_prefix"] == plain_key[:12]
