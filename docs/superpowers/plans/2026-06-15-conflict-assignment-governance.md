# Conflict Assignment Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver PR 2 of the traceability-conflict-governance maturity program: assign persisted document conflicts, govern early status transitions, enforce project-owner/assignee permissions, and record append-only decision history plus audit events.

**Architecture:** Extend the existing `change` domain instead of creating a new domain. Add assignment columns to `document_conflicts`, add a `document_conflict_decisions` history table, and keep `ConflictGovernanceService` as the single mutation boundary for assignment and status changes. Router endpoints call service methods and convert `PermissionError` to 403 and invalid transitions to 400.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async ORM, Alembic, PostgreSQL JSONB/UUID, SQLite test compatibility, Pydantic v2, pytest/pytest-asyncio.

---

## Scope And Boundaries

Included:

- additive `0023_conflict_assignment_governance` migration;
- `DocumentConflictDecision` model;
- conflict assignment fields: `assignee_user_id`, `assignment_source`, `assigned_at`, `due_at`;
- scan-time default assignment to primary document owner, related document owner, then project owner;
- manual assignment and reassignment by project owner;
- `complete_analysis` transition from `analysis` to `decision` by assignee or project owner;
- `reject` transition from `decision` to `rejected` by project owner with a required reason;
- append-only decision records for assignment and status changes;
- system audit events for state-changing API endpoints;
- focused migration, service, route-contract, and regression tests.

Deferred:

- AI advisory analysis;
- accepting revisions and creating linked change-request drafts;
- applied-change verification, closure rescan, and final close;
- risk acceptance and delivery-gate enforcement;
- frontend persistent conflict-resolution center.

## File Map

- Create `apps/api/alembic/versions/0023_conflict_assignment_governance.py`: additive columns and decision-history table.
- Modify `apps/api/app/domains/change/models.py`: assignment columns and `DocumentConflictDecision`.
- Modify `apps/api/app/domains/change/schemas.py`: assignment fields, decision response, and mutation request/response schemas.
- Modify `apps/api/app/domains/change/conflict_service.py`: assignment resolution, permission checks, history creation, and transition methods.
- Modify `apps/api/app/domains/change/router.py`: assignment, complete-analysis, and reject endpoints.
- Modify `apps/api/tests/test_alembic_migrations.py`: migration/model contract tests.
- Modify `apps/api/tests/test_persisted_conflict_scan.py`: focused service and mutation tests.
- Modify `apps/api/tests/test_api_router_contract.py`: route registration tests.
- Modify `docs/programs/traceability-conflict-governance-maturity.md`: record PR 2 status and evidence.

### Task 1: Add Migration And Models

- [ ] Write failing migration/model tests asserting `0023_conflict_assignment_governance.py` exists, `DocumentConflict` has assignment columns, and `DocumentConflictDecision` has tenant/project/conflict/action/status/evidence fields.
- [ ] Run `uv run --directory apps/api --extra dev python -m pytest tests/test_alembic_migrations.py -k conflict_assignment -v` and confirm failure.
- [ ] Add the migration with additive nullable assignment columns and `document_conflict_decisions`.
- [ ] Add `DocumentConflictDecision` and relationships in `models.py`.
- [ ] Run the focused migration/model tests and confirm pass.
- [ ] Commit with `feat: add conflict assignment history model`.

### Task 2: Expose Schemas

- [ ] Write failing schema assertions in `tests/test_persisted_conflict_scan.py` validating conflict responses include assignment fields and decision history can serialize.
- [ ] Run the focused schema test and confirm failure.
- [ ] Add `DocumentConflictDecisionResponse`, `ConflictAssignmentRequest`, `ConflictAnalysisCompletionRequest`, and `ConflictRejectionRequest`.
- [ ] Extend `DocumentConflictResponse` with assignment fields.
- [ ] Run the focused schema test and confirm pass.
- [ ] Commit with `feat: expose conflict governance schemas`.

### Task 3: Resolve Default Assignment During Scan

- [ ] Write failing service tests proving scans assign conflicts to primary document `created_by`, fall back to related document `created_by`, then project `owner_id`, and leave status `unassigned` if no owner exists.
- [ ] Run `uv run --directory apps/api --extra dev python -m pytest tests/test_persisted_conflict_scan.py -k "assignment" -v` and confirm failure.
- [ ] Implement default assignment resolution in `ConflictGovernanceService.scan_project` without changing existing fingerprint semantics.
- [ ] Record assignment decision history only when a new conflict is created or assignment changes.
- [ ] Run the assignment tests and existing scan tests.
- [ ] Commit with `feat: assign detected document conflicts`.

### Task 4: Add Governed Mutations

- [ ] Write failing tests for manual assignment, `complete_analysis`, rejected invalid transitions, rejection requiring reason, tenant isolation, and append-only decision history.
- [ ] Run focused mutation tests and confirm failure.
- [ ] Implement `assign_conflict`, `complete_analysis`, and `reject_conflict` service methods with project-owner and assignee checks.
- [ ] Keep invalid transitions atomic: no conflict mutation and no decision row.
- [ ] Run mutation tests and scan regression tests.
- [ ] Commit with `feat: govern conflict assignment transitions`.

### Task 5: Add API Endpoints And Audit

- [ ] Write failing route-contract tests for:
  - `POST /change/conflicts/{conflict_id}/assign`
  - `POST /change/conflicts/{conflict_id}/complete-analysis`
  - `POST /change/conflicts/{conflict_id}/reject`
- [ ] Add endpoint tests or service-backed router tests that verify 403 for unauthorized assignment and audit event creation for successful mutations.
- [ ] Implement router endpoints before broad `/{change_request_id}` routes.
- [ ] Log audit actions: `document_conflict.assign`, `document_conflict.complete_analysis`, and `document_conflict.reject`.
- [ ] Run route, service, and audit tests.
- [ ] Commit with `feat: expose conflict governance actions`.

### Task 6: Verify And Prepare PR

- [ ] Run `git diff --check origin/main...HEAD`.
- [ ] Run focused backend verification:

```powershell
uv run --directory apps/api --extra dev python -m pytest tests/test_persisted_conflict_scan.py tests/test_alembic_migrations.py tests/test_api_router_contract.py -v
```

- [ ] Run the full API suite because this PR changes shared models, router contracts, and migrations:

```powershell
uv run --directory apps/api --extra dev python -m pytest
```

- [ ] Run GitNexus change record:

```powershell
powershell -ExecutionPolicy Bypass -File infra\scripts\invoke-gitnexus-change-record.ps1 -RepoPath C:\amx\AMX-main -Scope compare -BaseRef origin/main
```

- [ ] Update `docs/programs/traceability-conflict-governance-maturity.md` with PR 2 scope, verification, risk, and next PR 3 action.
- [ ] Commit docs evidence with `docs: record conflict assignment governance evidence`.
- [ ] Push branch and open PR titled `feat: govern document conflict assignment`.
- [ ] Watch GitHub checks; fix failures before handing to merge/release workflow.

## Self-Review

- Spec coverage: this plan covers PR 2 assignment, status governance, permissions, and audit history. It intentionally defers PR 3 linkage/closure and PR 5 delivery gates.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type consistency: service, schema, migration, and route names consistently use conflict assignment governance terminology.
