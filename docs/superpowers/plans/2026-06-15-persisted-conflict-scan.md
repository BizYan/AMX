# Persisted Conflict Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver PR 1 of the traceability-conflict-governance maturity program: persist deterministic document conflicts and expose an idempotent project scan plus read API.

**Architecture:** Extend the existing `change` domain with an additive `DocumentConflict` model and a focused `ConflictGovernanceService`. Reuse `TraceabilityService.find_conflicts()` as the initial auditable rule source, normalize each finding into a stable fingerprint, and upsert project findings transactionally without adding assignment, decisions, AI, change-request linkage, or delivery gates yet.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async ORM, Alembic, PostgreSQL JSONB/UUID, SQLite test compatibility, Pydantic v2, pytest/pytest-asyncio.

---

## Scope And Boundaries

This plan produces one independently reviewable backend PR.

Included:

- additive `document_conflicts` table and SQLAlchemy model;
- deterministic fingerprint helper;
- project-scoped rule scan using existing traceability rules;
- idempotent create/refresh/reopen/absent behavior;
- project conflict list, detail, and scan endpoints;
- migration, service, route-contract, and regression tests.

Deferred to later program PRs:

- assignment and reassignment;
- conflict decision history and governed state transitions;
- AI advisory analysis;
- change-request draft linkage;
- closure eligibility;
- collaboration, audit, cockpit, frontend, and delivery-gate integration.

## File Map

- Create `apps/api/alembic/versions/0022_document_conflicts.py`: additive table, constraints, indexes, and downgrade.
- Modify `apps/api/app/domains/change/models.py`: conflict enums and `DocumentConflict` ORM model.
- Modify `apps/api/app/domains/change/schemas.py`: persisted conflict list/detail/scan response contracts.
- Create `apps/api/app/domains/change/conflict_service.py`: fingerprinting, project scan, persistence, list, and detail.
- Modify `apps/api/app/domains/change/router.py`: authenticated project scan/list/detail routes.
- Modify `apps/api/tests/test_alembic_migrations.py`: migration table/constraint contract.
- Create `apps/api/tests/test_persisted_conflict_scan.py`: disposable-database service tests.
- Modify `apps/api/tests/test_api_router_contract.py`: route registration contract.
- Modify `docs/programs/traceability-conflict-governance-maturity.md`: record PR 1 verification and status when implementation is complete.

### Task 1: Define The Migration Contract

**Files:**
- Create: `apps/api/alembic/versions/0022_document_conflicts.py`
- Modify: `apps/api/tests/test_alembic_migrations.py`

- [ ] **Step 1: Write the failing migration contract test**

Append a test that imports the migration module and checks the required table,
unique constraint, and downgrade operations from source:

```python
def test_document_conflicts_migration_defines_idempotent_project_fingerprint():
    migration = (VERSIONS_DIR / "0022_document_conflicts.py").read_text(encoding="utf-8")

    assert 'revision = "0022_document_conflicts"' in migration
    assert 'down_revision = "0021_invitation_delivery"' in migration
    assert 'op.create_table(' in migration
    assert '"document_conflicts"' in migration
    assert '"uq_document_conflicts_tenant_project_fingerprint"' in migration
    assert 'op.drop_table("document_conflicts")' in migration
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
uv run --directory apps/api --extra dev python -m pytest tests/test_alembic_migrations.py::test_document_conflicts_migration_defines_idempotent_project_fingerprint -v
```

Expected: FAIL because `0022_document_conflicts.py` does not exist.

- [ ] **Step 3: Create the additive migration**

Create `0022_document_conflicts.py` with:

```python
"""add persisted document conflicts

Revision ID: 0022_document_conflicts
Revises: 0021_invitation_delivery
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0022_document_conflicts"
down_revision = "0021_invitation_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_conflicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_key", sa.String(length=80), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("primary_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("primary_document_version", sa.Integer(), nullable=False),
        sa.Column("related_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("related_document_version", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("absent_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["primary_document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["related_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "fingerprint",
            name="uq_document_conflicts_tenant_project_fingerprint",
        ),
    )
    op.create_index("ix_document_conflicts_project_id", "document_conflicts", ["project_id"])
    op.create_index("ix_document_conflicts_status", "document_conflicts", ["status"])
    op.create_index("ix_document_conflicts_severity", "document_conflicts", ["severity"])
    op.create_index("ix_document_conflicts_last_scan_id", "document_conflicts", ["last_scan_id"])


def downgrade() -> None:
    op.drop_index("ix_document_conflicts_last_scan_id", table_name="document_conflicts")
    op.drop_index("ix_document_conflicts_severity", table_name="document_conflicts")
    op.drop_index("ix_document_conflicts_status", table_name="document_conflicts")
    op.drop_index("ix_document_conflicts_project_id", table_name="document_conflicts")
    op.drop_table("document_conflicts")
```

- [ ] **Step 4: Run migration contract tests**

Run:

```powershell
uv run --directory apps/api --extra dev python -m pytest tests/test_alembic_migrations.py -v
```

Expected: all migration contract tests PASS and Alembic reports one head.

- [ ] **Step 5: Commit the migration contract**

```powershell
git add apps/api/alembic/versions/0022_document_conflicts.py apps/api/tests/test_alembic_migrations.py
git commit -m "feat: add persisted document conflict migration"
```

### Task 2: Add The Persisted Conflict Model And Schemas

**Files:**
- Modify: `apps/api/app/domains/change/models.py`
- Modify: `apps/api/app/domains/change/schemas.py`
- Create: `apps/api/tests/test_persisted_conflict_scan.py`

- [ ] **Step 1: Write the failing model and schema test**

Create the disposable SQLite test module, set test environment variables before
app imports, register models, and add:

```python
@pytest.mark.asyncio
async def test_document_conflict_model_persists_rule_evidence(db_session):
    conflict = DocumentConflict(
        tenant_id=uuid4(),
        project_id=uuid4(),
        rule_key="missing_parent",
        fingerprint="a" * 64,
        severity="high",
        status="analysis",
        primary_document_id=uuid4(),
        primary_document_version=2,
        summary="PRD is missing an upstream document",
        evidence_json={"potential_parent_count": 1},
        first_detected_at=datetime.now(timezone.utc),
        last_detected_at=datetime.now(timezone.utc),
        last_scan_id=uuid4(),
    )
    db_session.add(conflict)
    await db_session.flush()

    payload = DocumentConflictResponse.model_validate(conflict)
    assert payload.rule_key == "missing_parent"
    assert payload.evidence_json == {"potential_parent_count": 1}
```

The fixture must create real `Tenant`, `Project`, and `Document` rows before
inserting the conflict so foreign-key behavior remains representative.

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
uv run --directory apps/api --extra dev python -m pytest tests/test_persisted_conflict_scan.py::test_document_conflict_model_persists_rule_evidence -v
```

Expected: FAIL because `DocumentConflict` and `DocumentConflictResponse` do not exist.

- [ ] **Step 3: Add model enums and `DocumentConflict`**

Add enums:

```python
class ConflictSeverity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConflictStatus(str, Enum):
    UNASSIGNED = "unassigned"
    ANALYSIS = "analysis"
    DECISION = "decision"
    REVISION_ACCEPTED = "revision_accepted"
    REJECTED = "rejected"
    RISK_ACCEPTED = "risk_accepted"
    CLOSED = "closed"
```

Add `DocumentConflict` using `UuidMixin`, `TimestampMixin`, and `TenantMixin`.
Its columns and indexes must match migration `0022_document_conflicts.py`.
Use separate relationships for `primary_document` and `related_document`.

- [ ] **Step 4: Add API schemas**

Add:

```python
class DocumentConflictResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID
    rule_key: str
    fingerprint: str
    severity: str
    status: str
    primary_document_id: UUID
    primary_document_version: int
    related_document_id: UUID | None
    related_document_version: int | None
    summary: str
    evidence_json: dict[str, Any]
    first_detected_at: datetime
    last_detected_at: datetime
    last_scan_id: UUID
    absent_since: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentConflictListResponse(BaseModel):
    items: list[DocumentConflictResponse]
    total: int


class ConflictScanResponse(BaseModel):
    scan_id: UUID
    project_id: UUID
    detected: int
    created: int
    refreshed: int
    reopened: int
    marked_absent: int
    items: list[DocumentConflictResponse]
```

- [ ] **Step 5: Run the focused model test**

Run:

```powershell
uv run --directory apps/api --extra dev python -m pytest tests/test_persisted_conflict_scan.py::test_document_conflict_model_persists_rule_evidence -v
```

Expected: PASS.

- [ ] **Step 6: Commit the model and schema**

```powershell
git add apps/api/app/domains/change/models.py apps/api/app/domains/change/schemas.py apps/api/tests/test_persisted_conflict_scan.py
git commit -m "feat: model persisted document conflicts"
```

### Task 3: Implement Stable Conflict Fingerprints

**Files:**
- Create: `apps/api/app/domains/change/conflict_service.py`
- Modify: `apps/api/tests/test_persisted_conflict_scan.py`

- [ ] **Step 1: Write failing fingerprint tests**

Add:

```python
def test_conflict_fingerprint_is_stable_when_summary_changes():
    first = build_conflict_fingerprint(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        rule_key="missing_parent",
        primary_document_id=DOCUMENT_ID,
        related_document_id=None,
        evidence={"candidate_parent_ids": [str(PARENT_ID)], "summary": "first"},
    )
    second = build_conflict_fingerprint(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        rule_key="missing_parent",
        primary_document_id=DOCUMENT_ID,
        related_document_id=None,
        evidence={"candidate_parent_ids": [str(PARENT_ID)], "summary": "changed"},
    )
    assert first == second


def test_conflict_fingerprint_changes_for_different_related_document():
    first = build_conflict_fingerprint(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        rule_key="inconsistent_link",
        primary_document_id=DOCUMENT_ID,
        related_document_id=PARENT_ID,
        evidence={},
    )
    second = build_conflict_fingerprint(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        rule_key="inconsistent_link",
        primary_document_id=DOCUMENT_ID,
        related_document_id=OTHER_PARENT_ID,
        evidence={},
    )
    assert first != second
```

- [ ] **Step 2: Run fingerprint tests and verify they fail**

Run:

```powershell
uv run --directory apps/api --extra dev python -m pytest tests/test_persisted_conflict_scan.py -k fingerprint -v
```

Expected: FAIL because `build_conflict_fingerprint` does not exist.

- [ ] **Step 3: Implement normalized SHA-256 fingerprinting**

Create `conflict_service.py` with:

```python
import hashlib
import json
from typing import Any
from uuid import UUID


MUTABLE_EVIDENCE_KEYS = {"summary", "description", "detected_at", "last_detected_at"}


def build_conflict_fingerprint(
    *,
    tenant_id: UUID,
    project_id: UUID,
    rule_key: str,
    primary_document_id: UUID,
    related_document_id: UUID | None,
    evidence: dict[str, Any],
) -> str:
    stable_evidence = {
        key: value
        for key, value in evidence.items()
        if key not in MUTABLE_EVIDENCE_KEYS
    }
    canonical = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "project_id": str(project_id),
            "rule_key": rule_key,
            "primary_document_id": str(primary_document_id),
            "related_document_id": str(related_document_id) if related_document_id else None,
            "evidence": stable_evidence,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

Before finalizing, ensure rule evidence uses sorted ID lists so input ordering
cannot change the fingerprint.

- [ ] **Step 4: Run fingerprint tests**

Run:

```powershell
uv run --directory apps/api --extra dev python -m pytest tests/test_persisted_conflict_scan.py -k fingerprint -v
```

Expected: both fingerprint tests PASS.

- [ ] **Step 5: Commit fingerprinting**

```powershell
git add apps/api/app/domains/change/conflict_service.py apps/api/tests/test_persisted_conflict_scan.py
git commit -m "feat: add stable conflict fingerprints"
```

### Task 4: Persist Idempotent Project Scans

**Files:**
- Modify: `apps/api/app/domains/change/conflict_service.py`
- Modify: `apps/api/app/domains/change/service.py`
- Modify: `apps/api/app/domains/change/schemas.py`
- Modify: `apps/api/tests/test_persisted_conflict_scan.py`
- Modify: `apps/api/tests/test_traceability.py`

- [ ] **Step 1: Write failing project-scan tests**

Add service tests that prove:

```python
@pytest.mark.asyncio
async def test_project_scan_creates_and_refreshes_same_conflict(db_session, project_graph):
    service = ConflictGovernanceService(db_session)

    first = await service.scan_project(
        tenant_id=project_graph.tenant_id,
        project_id=project_graph.project_id,
    )
    second = await service.scan_project(
        tenant_id=project_graph.tenant_id,
        project_id=project_graph.project_id,
    )

    assert first.created == 1
    assert second.created == 0
    assert second.refreshed == 1
    assert second.items[0].id == first.items[0].id


@pytest.mark.asyncio
async def test_project_scan_marks_missing_fingerprint_absent_without_closing(db_session, project_graph):
    service = ConflictGovernanceService(db_session)
    first = await service.scan_project(
        tenant_id=project_graph.tenant_id,
        project_id=project_graph.project_id,
    )
    project_graph.child.parent_document_id = project_graph.parent.id
    await db_session.flush()

    second = await service.scan_project(
        tenant_id=project_graph.tenant_id,
        project_id=project_graph.project_id,
    )
    conflict = await service.get_conflict(
        tenant_id=project_graph.tenant_id,
        conflict_id=first.items[0].id,
    )

    assert second.marked_absent == 1
    assert conflict.absent_since is not None
    assert conflict.status != "closed"
```

Also add a test proving a closed conflict is reopened when the same fingerprint
reappears. The test may set `status="closed"` directly because governed closure
is deferred to PR 3.

- [ ] **Step 2: Run scan tests and verify they fail**

Run:

```powershell
uv run --directory apps/api --extra dev python -m pytest tests/test_persisted_conflict_scan.py -k "project_scan" -v
```

Expected: FAIL because `ConflictGovernanceService.scan_project` does not exist.

- [ ] **Step 3: Extract auditable findings from existing traceability rules**

Keep `TraceabilityService.find_conflicts()` backward compatible. Add a project
method that loads all non-deleted project documents and invokes the existing
per-document rule method:

```python
async def find_project_conflicts(
    self,
    *,
    project_id: UUID,
    tenant_id: UUID,
) -> list[ConflictItem]:
    result = await self.db.execute(
        select(Document.id).where(
            Document.project_id == project_id,
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
        )
    )
    findings: list[ConflictItem] = []
    for document_id in result.scalars().all():
        analysis = await self.find_conflicts(document_id=document_id, tenant_id=tenant_id)
        findings.extend(analysis.conflicts)
    return findings
```

Extend `ConflictItem` with optional structured fields needed for persistence:

```python
rule_key: str | None = None
severity: str = "medium"
related_document_id: UUID | None = None
related_document_version: int | None = None
evidence: dict[str, Any] = Field(default_factory=dict)
```

Populate these fields for every existing rule without removing legacy response
fields.

- [ ] **Step 4: Implement `ConflictGovernanceService.scan_project`**

The method must:

1. create one `scan_id`;
2. call `TraceabilityService.find_project_conflicts`;
3. normalize and fingerprint every finding;
4. load existing project conflicts by fingerprint;
5. insert new findings as `analysis`;
6. refresh evidence, versions, summary, severity, `last_detected_at`,
   `last_scan_id`, and clear `absent_since` on existing findings;
7. reopen `closed` findings to `analysis`;
8. mark active records not observed in this scan with `absent_since`;
9. flush once and return `ConflictScanResponse`;
10. convert a uniqueness collision from a concurrent scan into a refresh of the
    existing fingerprint rather than a duplicate row.

Use `datetime.now(timezone.utc)` and never automatically close absent findings.

- [ ] **Step 5: Run persisted scan and legacy traceability tests**

Run:

```powershell
uv run --directory apps/api --extra dev python -m pytest tests/test_persisted_conflict_scan.py tests/test_traceability.py -v
```

Expected: all tests PASS, including legacy `find_conflicts` behavior.

- [ ] **Step 6: Commit persisted scanning**

```powershell
git add apps/api/app/domains/change/conflict_service.py apps/api/app/domains/change/service.py apps/api/app/domains/change/schemas.py apps/api/tests/test_persisted_conflict_scan.py apps/api/tests/test_traceability.py
git commit -m "feat: persist idempotent project conflict scans"
```

### Task 5: Expose Project Conflict Scan And Read APIs

**Files:**
- Modify: `apps/api/app/domains/change/router.py`
- Modify: `apps/api/tests/test_api_router_contract.py`
- Modify: `apps/api/tests/test_persisted_conflict_scan.py`

- [ ] **Step 1: Write failing route contract tests**

Add expected paths:

```python
def test_persisted_conflict_routes_are_registered_under_v1_api():
    paths = {route.path for route in api_router.routes}

    assert "/changes/conflicts/projects/{project_id}/scan" in paths
    assert "/changes/conflicts/projects/{project_id}" in paths
    assert "/changes/conflicts/{conflict_id}" in paths
```

Add service-level list/detail isolation tests proving another tenant receives no
conflict records.

- [ ] **Step 2: Run route and isolation tests and verify they fail**

Run:

```powershell
uv run --directory apps/api --extra dev python -m pytest tests/test_api_router_contract.py tests/test_persisted_conflict_scan.py -k "route or tenant" -v
```

Expected: FAIL because routes and list/detail methods do not exist.

- [ ] **Step 3: Add list and detail service methods**

Implement:

```python
async def list_project_conflicts(
    self,
    *,
    tenant_id: UUID,
    project_id: UUID,
    severity: str | None = None,
    status: str | None = None,
) -> DocumentConflictListResponse:
    filters = [
        DocumentConflict.tenant_id == tenant_id,
        DocumentConflict.project_id == project_id,
    ]
    if severity:
        filters.append(DocumentConflict.severity == severity)
    if status:
        filters.append(DocumentConflict.status == status)
    result = await self.db.execute(
        select(DocumentConflict)
        .where(*filters)
        .order_by(DocumentConflict.last_detected_at.desc())
    )
    items = list(result.scalars().all())
    return DocumentConflictListResponse(items=items, total=len(items))


async def get_conflict(
    self,
    *,
    tenant_id: UUID,
    conflict_id: UUID,
) -> DocumentConflict | None:
    result = await self.db.execute(
        select(DocumentConflict).where(
            DocumentConflict.id == conflict_id,
            DocumentConflict.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()
```

Both queries must filter `tenant_id`. Project list must also filter
`project_id`; order by severity priority then `last_detected_at` descending.

- [ ] **Step 4: Add authenticated router endpoints**

Add routes before any broad `/{change_request_id}` route that could shadow them:

```python
@router.post("/conflicts/projects/{project_id}/scan", response_model=ConflictScanResponse)
async def scan_project_conflicts(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
    conflict = await ConflictGovernanceService(db).get_conflict(
        tenant_id=current_user.tenant_id,
        conflict_id=conflict_id,
    )
    if not conflict:
        raise HTTPException(status_code=404, detail="Document conflict not found")
    return conflict
```

PR 1 reuses current authenticated tenant isolation. Fine-grained scan permission
enforcement is explicitly delivered in PR 2.

- [ ] **Step 5: Run route and service tests**

Run:

```powershell
uv run --directory apps/api --extra dev python -m pytest tests/test_api_router_contract.py tests/test_persisted_conflict_scan.py tests/test_traceability.py -v
```

Expected: all focused route, persisted conflict, and legacy traceability tests PASS.

- [ ] **Step 6: Commit API routes**

```powershell
git add apps/api/app/domains/change/router.py apps/api/tests/test_api_router_contract.py apps/api/tests/test_persisted_conflict_scan.py
git commit -m "feat: expose persisted conflict scan api"
```

### Task 6: Verify Migration And Full Backend Risk Boundary

**Files:**
- Modify: `docs/programs/traceability-conflict-governance-maturity.md`

- [ ] **Step 1: Run focused conflict and migration verification**

```powershell
uv run --directory apps/api --extra dev python -m pytest tests/test_persisted_conflict_scan.py tests/test_traceability.py tests/test_alembic_migrations.py tests/test_api_router_contract.py -v
```

Expected: all selected tests PASS.

- [ ] **Step 2: Run the full API suite because this PR changes shared models and migrations**

```powershell
uv run --directory apps/api --extra dev python -m pytest
```

Expected: full API suite PASS with zero failures.

- [ ] **Step 3: Verify Alembic upgrade and downgrade on a disposable database**

Use the repository-supported disposable PostgreSQL environment. Run:

```powershell
uv run --directory apps/api alembic upgrade head
uv run --directory apps/api alembic downgrade 0021_invitation_delivery
uv run --directory apps/api alembic upgrade head
```

Expected: each command exits `0`; the final database is at `0022_document_conflicts`.
Do not run downgrade against production or any database containing unique
conflict-governance evidence.

- [ ] **Step 4: Run repository diff checks**

```powershell
git diff --check origin/main...HEAD
```

Expected: exit `0` with no output.

- [ ] **Step 5: Record GitNexus fallback and impact evidence**

Current dedicated worktree reports `Repository not indexed`. Do not treat this
as blocking. Run:

```powershell
powershell -ExecutionPolicy Bypass -File infra\scripts\invoke-gitnexus-change-record.ps1 `
  -RepoPath C:\amx\AMX-traceability-conflict-governance `
  -Scope compare `
  -BaseRef origin/main
```

Record the raw Git changed-file evidence and the explicit GitNexus unavailable or
low-value fallback in the PR. Do not claim graph coverage.

- [ ] **Step 6: Update the maturity program**

In `docs/programs/traceability-conflict-governance-maturity.md`:

- mark planned PR 1 as implemented and verified;
- record the branch, commit, focused/full test evidence, migration evidence, and
  GitNexus fallback;
- set the next action to PR 1 review/CI, then PR 2 assignment and status
  governance.

- [ ] **Step 7: Commit verification evidence**

```powershell
git add docs/programs/traceability-conflict-governance-maturity.md
git commit -m "docs: record persisted conflict scan evidence"
```

### Task 7: Prepare The PR

**Files:**
- No new source files unless verification finds defects.

- [ ] **Step 1: Review the final diff**

```powershell
git status --short --branch
git diff --stat origin/main...HEAD
git log --oneline origin/main..HEAD
```

Expected: only PR 1 scope files plus the approved program/design/plan documents.

- [ ] **Step 2: Run final verification after the last code change**

```powershell
git diff --check origin/main...HEAD
uv run --directory apps/api --extra dev python -m pytest tests/test_persisted_conflict_scan.py tests/test_traceability.py tests/test_alembic_migrations.py tests/test_api_router_contract.py -v
```

Expected: all commands exit `0`.

- [ ] **Step 3: Push and create the PR**

```powershell
git push -u origin feature/traceability-conflict-governance
$body = @'
## Purpose
Persist deterministic document conflicts and expose an idempotent project scan and read API.

Risk level: High

## Scope
- Backend model and additive Alembic migration
- Conflict fingerprint and project scan service
- Authenticated project scan/list/detail endpoints
- Migration, service, route-contract, and legacy regression tests

## Evidence
Record the exact focused suite, full API suite, disposable migration cycle, git diff check, and GitNexus fallback results produced by Task 6.

## Risk And Rollback
The migration is additive. Revert the application commit first; downgrade to 0021_invitation_delivery only after confirming no unique conflict evidence must be retained.

## Agent Attribution
Codex authored the branch.

## GitNexus Impact Record
The dedicated worktree was not indexed at plan time. Include the final change-record wrapper output and raw Git changed-file evidence.
'@
gh pr create --base main --head feature/traceability-conflict-governance --title "feat: persist document conflict scans" --body $body
```

PR body must classify risk as High and include:

- purpose and exact PR 1 scope;
- migration and rollback boundary;
- focused and full API results;
- intentionally omitted frontend checks because PR 1 has no frontend changes;
- GitNexus worktree-unindexed fallback;
- changed models, tables, routes, services, and tests;
- attribution: Codex.

- [ ] **Step 4: Inspect CI and review findings**

```powershell
gh pr checks <pr-number> --watch
gh pr view <pr-number> --json mergeStateStatus,reviewDecision,statusCheckRollup,url
```

Expected: required checks green. Fix any failure or actionable review finding
before calling PR 1 ready. Repository rules reserve merge authority for the
human owner.

## Program Continuation After PR 1

Once PR 1 is ready or merged, create a separate implementation plan for PR 2
using the now-stable persisted conflict contract. PR 2 must add assignment,
decision history, state-transition permissions, and audit events without
changing the fingerprint or scan semantics established here.
