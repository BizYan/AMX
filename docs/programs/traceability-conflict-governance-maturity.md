# Traceability Conflict Governance Maturity Program

Updated: 2026-06-15

## Objective

Advance the traceability, contradiction, and change-control domain to a complete,
auditable resolution loop: persist rule-detected document conflicts, assign
ownership, record governed decisions, create linked change-request drafts, and
enforce delivery gates according to unresolved conflict risk.

## Current Maturity

### Completed

- Persistent document references, impact analyses, and downstream sync proposals.
- Project-level traceability coverage and repair suggestions.
- Change-request approval and application lifecycle.
- Audit-oriented change and traceability command-center summaries.
- A visible contradiction-resolution page with document-derived conflict cues.
- Delivery-readiness and customer-acceptance gate infrastructure.
- Idempotent persisted conflict scan and read API.
- Automatic primary document owner assignment, manual reassignment, governed
  analysis/rejection transitions, and append-only decision history.

### Partial

- The contradiction-resolution page can display and locally classify conflicts,
  but is not yet backed by the persisted conflict governance API.
- Existing change requests and sync proposals can execute downstream changes,
  but accepting a conflict revision does not create a linked change-request draft.
- Delivery readiness includes traceability signals, but does not enforce the
  approved high-risk conflict policy.

### Missing

- Linked change-request draft creation from an accepted revision.
- Conflict closure gated by applied change and successful traceability rescan.
- High-risk conflict delivery blocking and audited risk acceptance.
- Cross-entry visibility in project cockpit, collaboration, audit, and delivery
  readiness.

## Approved Scope

Included:

- auditable rule-based conflict detection;
- AI-generated analysis and revision suggestions as advisory output only;
- automatic assignment to document owners with manual reassignment;
- project-lead fallback queue when no document owner exists;
- persisted conflict decisions and status history;
- automatic creation of a linked change-request draft after accepting revision;
- closure only after linked change application and traceability rescan;
- high-risk unresolved conflict delivery blocking;
- warning-only treatment for unresolved medium- and low-risk conflicts;
- audited, authorized risk acceptance;
- user-visible integration through the normal product entry paths.

Excluded:

- AI-created final decisions, direct document modifications, or automatic closure;
- cross-tenant conflict analysis;
- rewriting the existing change approval or document lifecycle;
- treating semantic AI output as an authoritative conflict detector.

## Key Decisions

- Extend the existing `change` and traceability domain rather than create a
  separate conflict-governance domain.
- Rule detection is authoritative and auditable; AI is advisory.
- Conflict assignment defaults to the primary affected document owner, then the
  related document owner when rule evidence exposes one, then project owner
  fallback; project owners may manually reassign.
- Accepting revision creates a change-request draft rather than submitting or
  applying it automatically.
- High-risk unresolved conflicts block formal delivery unless an authorized,
  reasoned risk acceptance is recorded.
- Medium- and low-risk unresolved conflicts warn without blocking delivery.

## Planned PRs

1. Persisted conflict model, migration, idempotent rule scan, and domain tests.
2. Assignment, governed status transitions, permissions, and decision audit
   history.
3. Accepted-revision linkage to change-request drafts, applied-change verification,
   traceability rescan, and controlled closure.
4. Real API-backed contradiction-resolution center with filters, details,
   decisions, and linked-change navigation.
5. Project cockpit, collaboration, audit, delivery-gate integration, and production
   acceptance evidence.

Each PR must be independently reviewable and testable. Scope may be regrouped
only when doing so preserves a coherent functional unit and avoids overlapping
work.

## Acceptance

- Repeated scans update the same conflict rather than creating duplicates.
- Every conflict exposes its rule, severity, evidence, affected documents and
  versions, owner, status, and decision history.
- Unauthorized users cannot assign, decide, accept risk, or close conflicts.
- Accepting revision atomically records the decision and creates a linked
  change-request draft.
- A conflict cannot close until its linked change is applied and a rescan confirms
  the conflict is no longer present.
- High-risk unresolved conflicts block formal delivery.
- Authorized risk acceptance unblocks delivery while preserving reason, actor,
  timestamp, and evidence.
- Medium- and low-risk unresolved conflicts remain visible warnings.
- The capability is discoverable from normal project, collaboration, audit, and
  delivery paths.

## Verification And Release Boundary

- Focused API domain, migration, permission, and idempotency tests per backend PR.
- Web typecheck/build and focused Playwright flows per affected frontend PR.
- Delivery-gate regression for blocking, warning, and risk-acceptance behavior.
- Final stage verification includes production-path acceptance before declaring
  the maturity objective achieved.
- Release cadence follows workspace policy; this program does not require
  deployment after every merge.

Rollback boundary:

- revert application behavior and product entry points;
- downgrade the additive conflict-governance migration when safe;
- preserve the existing traceability, change-request, and delivery workflows.

## Active Work

- Branch: `feature/conflict-assignment-governance`
- Current phase: PR 2 implemented locally; ready for PR creation and CI.
- Design: `docs/superpowers/specs/2026-06-15-traceability-conflict-governance-design.md`
- Implementation plan: `docs/superpowers/plans/2026-06-15-conflict-assignment-governance.md`
- Open PRs for this program: none at local evidence update time.

### PR 1: Persisted Conflict Scan

Implemented:

- additive `document_conflicts` migration and matching SQLAlchemy model;
- deterministic conflict fingerprints and uniqueness recovery;
- project-level idempotent scan, refresh, absent marking, and reopen behavior;
- tenant-isolated conflict list and detail reads;
- authenticated project scan, list, and detail API routes;
- structured evidence added to existing deterministic traceability rules.

Verification:

- focused conflict, traceability, migration, and router tests: `28 passed`;
- full API suite: `540 passed`;
- `git diff --check`: passed;
- GitHub CI: API tests, web typecheck/build, deterministic E2E, Docker Compose,
  collaboration contract, and PR evidence checks passed for PR #47;
- GitNexus change-record wrapper: Git changed-file evidence detected; dedicated
  worktree was not indexed, so symbol impact was unavailable and fallback evidence
  is required.

Verification limitation:

- Disposable Alembic upgrade/downgrade/upgrade was not run because this Windows
  environment has no Docker CLI and the repository-isolated PostgreSQL endpoint
  `127.0.0.1:15432` was not listening. The migration has a single-head contract,
  model/migration constraint-index consistency tests, and full API coverage, but
  CI or a disposable PostgreSQL environment must still prove the runtime
  migration cycle before merge.

Merge:

- PR #47 merged to `main` at `a0b2ec35f3dae62c241135a9ee3fca308903e18a` on
  2026-06-15.

### PR 2: Conflict Assignment Governance

Implemented:

- additive assignment-governance migration with assignment columns and
  `document_conflict_decisions` history table;
- SQLAlchemy `DocumentConflictDecision` model and conflict assignment fields;
- response and mutation schemas for assignment, analysis completion, and
  rejection;
- scan-time primary document owner assignment with append-only history;
- manual project-owner reassignment;
- assignee or project-owner `analysis -> decision` transition;
- project-owner `decision -> rejected` transition with required reason;
- tenant isolation, permission checks, invalid-transition protection, and
  no-history-on-failed-transition behavior;
- authenticated API endpoints for assign, complete-analysis, and reject;
- audit events for successful API mutations:
  `document_conflict.assign`, `document_conflict.complete_analysis`, and
  `document_conflict.reject`.

Verification:

- focused backend suite:
  `uv run --directory apps/api --extra dev python -m pytest tests/test_persisted_conflict_scan.py tests/test_alembic_migrations.py tests/test_api_router_contract.py -v`
  returned `22 passed`;
- full API suite:
  `uv run --directory apps/api --extra dev python -m pytest` returned
  `548 passed, 15 warnings`;
- `git diff --check origin/main...HEAD`: passed;
- GitNexus change-record wrapper:
  `C:\amx\reports\gitnexus-change-record-20260615-182302.md`;
- GitNexus result: Git changed-file evidence detected for 9 files; symbol mapping
  returned zero indexed symbols, so fallback changed-file evidence is required.

Verification limitation:

- Disposable PostgreSQL Alembic upgrade/downgrade/upgrade was not run locally
  because Docker CLI is unavailable in this Windows environment. Migration
  revision length, single-head, source contract, model contract, and full API
  tests passed locally; CI or a disposable PostgreSQL environment must still
  prove runtime migration before merge.

## Next Actions

1. Push PR 2 and require CI plus disposable PostgreSQL migration evidence before
   merge.
2. After PR 2 is ready or merged, plan PR 3 accepted-revision linkage to
   change-request drafts, applied-change verification, rescan, and controlled
   closure.
