# Invited User Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow a new external user to create a lowest-privilege tenant account and join a project only through a valid project invitation, while preserving the existing signed-in acceptance path.

**Architecture:** Add an invitation application service that owns token preview, activation, account-role-membership creation, and signed-in acceptance under one transaction boundary. Keep public endpoints in the projects router, reuse existing identity/password/JWT primitives, extend the existing invitation page, and prove the workflow with backend lifecycle tests and focused Playwright coverage.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, PostgreSQL/SQLite tests, Next.js App Router, React Query, Playwright, pytest.

---

## File Structure

- Create `apps/api/app/domains/projects/invitation_service.py`: invitation lookup, safe preview, activation, lowest-privilege role assignment, and atomic acceptance.
- Modify `apps/api/app/domains/projects/schemas.py`: preview and activation request/response contracts.
- Modify `apps/api/app/domains/projects/router.py`: thin public preview/activation endpoints and signed-in accept delegation.
- Modify `apps/api/tests/domains/test_project_invitation_lifecycle.py`: backend security, activation, role, membership, idempotency, and rollback coverage.
- Modify `apps/web/src/lib/api-client.ts`: public preview/activation contracts and methods.
- Modify `apps/web/src/app/(app)/invitations/[token]/page.tsx`: invitation state, activation form, existing-user acceptance, and failure states.
- Modify `apps/web/tests/e2e/playwright/fixtures/api-mocks.ts`: deterministic preview and activation responses.
- Modify `apps/web/tests/e2e/playwright/project-invitation-lifecycle.spec.ts`: new-user activation and invalid-state E2E.

No migration is planned: `users.email` is already globally unique, `project_invitations.token` is unique, and `project_members` uses a composite primary key. The service will use invitation row locking plus existing constraints.

### Task 1: Define Invitation Preview And Activation Contracts

**Files:**
- Modify: `apps/api/app/domains/projects/schemas.py`
- Test: `apps/api/tests/domains/test_project_invitation_lifecycle.py`

- [ ] **Step 1: Write failing contract tests**

Add tests that import and validate:

```python
ProjectInvitationPreviewResponse(
    status="active",
    masked_email="i***@example.com",
    project_name="Invitation Project",
    expires_at=expires_at,
    can_activate=True,
    can_accept_existing_user=True,
)
ProjectInvitationActivationRequest(full_name="Invited User", password="secure-password")
```

Also assert invalid previews omit `project_name`, `masked_email`, and `expires_at`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest apps/api/tests/domains/test_project_invitation_lifecycle.py -q
```

Expected: import or validation failure because the contracts do not exist.

- [ ] **Step 3: Add schemas**

Add:

```python
class ProjectInvitationPreviewResponse(BaseModel):
    status: Literal["active", "expired", "accepted", "revoked", "invalid"]
    masked_email: str | None = None
    project_name: str | None = None
    expires_at: datetime | None = None
    can_activate: bool = False
    can_accept_existing_user: bool = False


class ProjectInvitationActivationRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=100)


class ProjectInvitationActivationResponse(ProjectInvitationAcceptResponse):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
```

- [ ] **Step 4: Run tests and verify GREEN**

Run the focused invitation test file and expect all contract tests to pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/app/domains/projects/schemas.py apps/api/tests/domains/test_project_invitation_lifecycle.py
git commit -m "test: define invitation activation contracts"
```

### Task 2: Implement Safe Invitation Preview

**Files:**
- Create: `apps/api/app/domains/projects/invitation_service.py`
- Modify: `apps/api/app/domains/projects/router.py`
- Test: `apps/api/tests/domains/test_project_invitation_lifecycle.py`

- [ ] **Step 1: Write failing preview behavior tests**

Cover:

```python
preview = await project_router.preview_project_invitation(created.token, db_session)
assert preview.status == "active"
assert preview.project_name == project.name
assert preview.masked_email == "i*****e@example.com"
assert preview.can_activate is True

invalid = await project_router.preview_project_invitation("unknown-token", db_session)
assert invalid.status == "invalid"
assert invalid.project_name is None
assert invalid.masked_email is None
```

Add expired, revoked, and accepted preview assertions.

- [ ] **Step 2: Run tests and verify RED**

Expected: preview route does not exist.

- [ ] **Step 3: Implement service preview**

Create `ProjectInvitationService` with:

```python
async def find_by_token(self, token: str, *, for_update: bool = False) -> ProjectInvitation | None:
    query = select(ProjectInvitation).where(
        or_(ProjectInvitation.token == token_digest(token), ProjectInvitation.token == token),
        ProjectInvitation.deleted_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    return (await self.db.execute(query)).scalar_one_or_none()
```

Add private email masking and `preview(token)` that only loads the project for valid known invitations and returns no sensitive fields for invalid tokens.

- [ ] **Step 4: Add public preview route**

Add:

```python
@router.get("/invitations/{token}/preview", response_model=ProjectInvitationPreviewResponse)
async def preview_project_invitation(token: str, db: AsyncSession = Depends(get_db)):
    return await ProjectInvitationService(db).preview(token)
```

- [ ] **Step 5: Run tests and verify GREEN**

Run the focused invitation test file.

- [ ] **Step 6: Commit**

```powershell
git add apps/api/app/domains/projects/invitation_service.py apps/api/app/domains/projects/router.py apps/api/tests/domains/test_project_invitation_lifecycle.py
git commit -m "feat: add safe invitation preview"
```

### Task 3: Implement Atomic New-User Activation

**Files:**
- Modify: `apps/api/app/domains/projects/invitation_service.py`
- Modify: `apps/api/app/domains/projects/router.py`
- Test: `apps/api/tests/domains/test_project_invitation_lifecycle.py`

- [ ] **Step 1: Write failing activation tests**

Test that activation:

```python
result = await project_router.activate_project_invitation(
    created.token,
    ProjectInvitationActivationRequest(full_name="New Consultant", password="secure-password"),
    db_session,
)
assert result.status == "accepted"
assert result.project_id == project.id
assert decode_token(result.access_token)["email"] == "new@example.com"
```

Then assert:

- created user belongs to invitation tenant;
- password verifies with `verify_password`;
- `ProjectMember` exists;
- lowest-privilege role is assigned through `UserRole`;
- invitation has `accepted_at`;
- audit contains no password or raw invitation token.

- [ ] **Step 2: Run tests and verify RED**

Expected: activation endpoint/service method does not exist.

- [ ] **Step 3: Implement lowest-privilege role helper**

In `ProjectInvitationService`, define a stable role:

```python
INVITED_PROJECT_MEMBER_ROLE = "project_member"
INVITED_PROJECT_MEMBER_PERMISSIONS = {
    "projects": ["read"],
    "documents": ["read", "comment"],
    "collaboration": ["read", "write"],
}
```

Implement an idempotent tenant-scoped lookup/create and assign `UserRole` only when absent.

- [ ] **Step 4: Implement activation transaction**

Implement `activate(token, data)` to:

1. lock invitation with `for_update=True`;
2. reject invalid, expired, revoked, or accepted invitations;
3. reject any existing global user with the invitation email, returning an existing-account conflict for same tenant and cross-tenant conflict otherwise;
4. create user through `UserService.create_user`;
5. assign the lowest-privilege role;
6. create `ProjectMember`;
7. set `accepted_at`;
8. write `project.invitation.activate` audit metadata without credentials;
9. create JWT using existing `create_access_token`;
10. return activation response.

- [ ] **Step 5: Add public activation route**

Add:

```python
@router.post("/invitations/{token}/activate", response_model=ProjectInvitationActivationResponse)
async def activate_project_invitation(
    token: str,
    data: ProjectInvitationActivationRequest,
    db: AsyncSession = Depends(get_db),
):
    return await ProjectInvitationService(db).activate(token, data)
```

Map service errors to `404`, `409`, `410`, or `422` without exposing internal rows.

- [ ] **Step 6: Run tests and verify GREEN**

Run focused invitation tests and expect activation tests to pass.

- [ ] **Step 7: Commit**

```powershell
git add apps/api/app/domains/projects/invitation_service.py apps/api/app/domains/projects/router.py apps/api/tests/domains/test_project_invitation_lifecycle.py
git commit -m "feat: activate invited project users"
```

### Task 4: Harden Existing-User Acceptance And Failure Cases

**Files:**
- Modify: `apps/api/app/domains/projects/invitation_service.py`
- Modify: `apps/api/app/domains/projects/router.py`
- Test: `apps/api/tests/domains/test_project_invitation_lifecycle.py`

- [ ] **Step 1: Write failing security and idempotency tests**

Cover:

- same-tenant existing user must log in instead of activating;
- cross-tenant same-email activation is rejected;
- wrong signed-in email and tenant are rejected;
- repeated and concurrent consumption do not create duplicate membership;
- simulated failure after user creation rolls back invitation acceptance and membership.

- [ ] **Step 2: Run tests and verify RED**

Expected: at least same-tenant/cross-tenant distinction or atomic acceptance test fails.

- [ ] **Step 3: Delegate signed-in acceptance to service**

Move the current route logic to `ProjectInvitationService.accept_existing(token, current_user)` using the same locked invitation and membership helper used by activation. Keep route response and error status compatibility.

- [ ] **Step 4: Add owner notification without making it transactional**

After successful core flush, call `UserNotificationService.create_notification` for the project owner. Catch notification failure, log it, and preserve the successful membership transaction.

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```powershell
python -m pytest apps/api/tests/domains/test_project_invitation_lifecycle.py apps/api/tests/test_api_router_contract.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add apps/api/app/domains/projects/invitation_service.py apps/api/app/domains/projects/router.py apps/api/tests/domains/test_project_invitation_lifecycle.py
git commit -m "fix: harden invitation acceptance"
```

### Task 5: Add Frontend API And Activation Experience

**Files:**
- Modify: `apps/web/src/lib/api-client.ts`
- Modify: `apps/web/src/app/(app)/invitations/[token]/page.tsx`
- Test: `apps/web/tests/e2e/playwright/project-invitation-lifecycle.spec.ts`

- [ ] **Step 1: Write failing Playwright activation test**

Mock preview and activation endpoints, visit the invitation route without an auth token, fill name/password/confirmation, submit, then assert:

```typescript
await expect(page.getByText('账号已激活并加入项目')).toBeVisible()
await expect.poll(() => page.evaluate(() => localStorage.getItem('auth_token'))).toBe('activation-jwt')
```

Also add an invalid invitation test that proves project/email information is absent.

- [ ] **Step 2: Run focused E2E and verify RED**

Run:

```powershell
corepack pnpm exec playwright test tests/e2e/playwright/project-invitation-lifecycle.spec.ts
```

Expected: activation controls are missing.

- [ ] **Step 3: Add API client contracts**

Add `ProjectInvitationPreview`, `ProjectInvitationActivation`, `previewInvitation(token)`, and `activateInvitation(token, payload)` to `projectMembersApi`.

- [ ] **Step 4: Implement invitation page states**

Use one preview query and separate activation/accept mutations. The page must:

- render active, expired, revoked, accepted, and invalid states;
- show the activation form only when unauthenticated and `can_activate`;
- show signed-in acceptance only when authenticated;
- validate password confirmation before mutation;
- call `setToken(result.access_token)` after activation;
- redirect only after successful acceptance/activation;
- avoid rendering project name or email for invalid tokens.

- [ ] **Step 5: Run focused E2E and typecheck**

Run:

```powershell
corepack pnpm exec playwright test tests/e2e/playwright/project-invitation-lifecycle.spec.ts
corepack pnpm typecheck
```

- [ ] **Step 6: Commit**

```powershell
git add apps/web/src/lib/api-client.ts apps/web/src/app/(app)/invitations/[token]/page.tsx apps/web/tests/e2e/playwright/project-invitation-lifecycle.spec.ts
git commit -m "feat: add invited user activation experience"
```

### Task 6: Complete Deterministic Mocks, Verification, And PR

**Files:**
- Modify: `apps/web/tests/e2e/playwright/fixtures/api-mocks.ts`
- Modify: `apps/web/src/app/(app)/projects/[projectId]/members/page.tsx`
- Modify: `docs/superpowers/specs/2026-06-14-invited-user-activation-design.md` only if implementation evidence exposes a necessary clarification.

- [ ] **Step 1: Extend deterministic API mocks**

Add preview and activation handlers that preserve the existing signed-in acceptance mock. Ensure raw token values exist only in deterministic test fixtures.

- [ ] **Step 2: Add owner-facing security guidance**

Update the project member invitation page copy to state that external users can activate accounts through the link, links are sensitive, and renewal invalidates the previous link.

- [ ] **Step 3: Run focused backend and frontend verification**

Run:

```powershell
python -m pytest apps/api/tests/domains/test_project_invitation_lifecycle.py apps/api/tests/test_api_router_contract.py apps/api/tests/test_alembic_migrations.py -q
corepack pnpm typecheck
corepack pnpm build
corepack pnpm exec playwright test tests/e2e/playwright/project-invitation-lifecycle.spec.ts
git diff --check
```

- [ ] **Step 4: Run final impact record**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File infra/scripts/invoke-gitnexus-change-record.ps1 -RepoPath C:\amx\AMX-invited-user-activation -Scope compare -BaseRef main
```

Record GitNexus fallback if the isolated worktree is not indexed.

- [ ] **Step 5: Commit final evidence changes**

```powershell
git add apps/web/tests/e2e/playwright/fixtures/api-mocks.ts apps/web/src/app/(app)/projects/[projectId]/members/page.tsx
git commit -m "test: verify invited user activation flow"
```

- [ ] **Step 6: Push and create PR**

Create a PR containing:

- focused verification evidence;
- identity and permission risk;
- rollback plan;
- Agent Attribution;
- GitNexus impact or fallback record.

- [ ] **Step 7: Watch CI and fix failures**

All API, Web build, deterministic E2E, Docker Compose, and governance checks must pass before release handoff.
