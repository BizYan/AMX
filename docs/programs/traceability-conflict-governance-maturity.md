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
- Accepted revision creates a linked draft change request and records durable
  conflict/change linkage.

### Partial

- The contradiction-resolution page can display and locally classify conflicts,
  but is not yet backed by the persisted conflict governance API.
- Existing change requests and sync proposals can execute downstream changes,
  and accepted conflict revisions now create draft change requests, but applied
  change verification and controlled closure are not yet implemented.
- Delivery readiness includes traceability signals, but does not enforce the
  approved high-risk conflict policy.

### Missing

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

- Branch: `feature/conflict-change-request-linkage`
- Current phase: PR 3 linkage implemented locally; ready for PR creation and CI.
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

Merge:

- PR #48 merged to `main` at `3ab88256670f967ed7cbd4efdccbe36fc3bd545c` on
  2026-06-15.

### PR 3: Accepted Revision Change Draft Linkage

Implemented:

- additive `0024_conflict_change_linkage` migration with
  `linked_change_request_id`, `accepted_revision_json`, and
  `revision_accepted_at`;
- conflict response fields for accepted revision linkage;
- `accept_revision` governance service method;
- project-owner-only `decision -> revision_accepted` transition;
- atomic draft `ChangeRequest` creation from accepted revision evidence;
- durable conflict decision history with linked change-request ID;
- authenticated `POST /change/conflicts/{conflict_id}/accept-revision` API;
- audit event `document_conflict.accept_revision`;
- invalid-transition protection with no draft change request and no history row.

Verification:

- focused backend suite:
  `uv run --directory apps/api --extra dev python -m pytest tests/test_persisted_conflict_scan.py tests/test_alembic_migrations.py tests/test_api_router_contract.py -v`
  returned `26 passed`;
- full API suite:
  `uv run --directory apps/api --extra dev python -m pytest` returned
  `552 passed, 15 warnings`;
- `git diff --check origin/main...HEAD`: passed;
- GitNexus change-record wrapper:
  `C:\amx\reports\gitnexus-change-record-20260615-184030.md`;
- GitNexus result: Git changed-file evidence detected for 8 files; symbol mapping
  returned zero indexed symbols, so fallback changed-file evidence is required.

Verification limitation:

- Disposable PostgreSQL migration cycle was not run locally because Docker CLI is
  unavailable in this Windows environment. The migration is additive, avoids
  extra foreign keys that are incompatible with the repository's partial CI
  migration harness, and is covered by source/model contract tests plus full API
  tests. GitHub CI must still prove runtime migration.

Merge:

- PR #49 merged to `main` at `f9e4f681ed5c5d7bf3ce1f21bff6a678d07666f6` on
  2026-06-15.

### PR 4: Applied Change Rescan Closure

Implemented:

- additive `0025_conflict_closure` migration with `closure_scan_id`,
  `closure_verified_at`, and `closure_evidence_json`;
- conflict response fields for closure verification evidence;
- `close_after_rescan` governance service method;
- project-owner-only `revision_accepted -> closed` transition;
- linked change request must be `applied` before closure;
- deterministic project rescan must prove the conflict fingerprint is absent;
- durable conflict decision history with closure scan and change-request IDs;
- authenticated `POST /change/conflicts/{conflict_id}/close-after-rescan` API;
- audit event `document_conflict.close`;
- invalid-transition and still-detected protections with no close history row.

Verification:

- focused backend suite:
  `uv run --directory apps/api --extra dev python -m pytest tests/test_persisted_conflict_scan.py tests/test_alembic_migrations.py tests/test_api_router_contract.py -q`
  returned `31 passed`;

Verification limitation:

- Disposable PostgreSQL migration cycle was not run locally because Docker CLI is
  unavailable in this Windows environment. The migration is additive, avoids
  extra foreign keys that are incompatible with the repository's partial CI
  migration harness, and is covered by source/model contract tests. GitHub CI
  must still prove runtime migration.

Merge:

- PR #50 merged to `main` at `4e640e6ca542b622c8c4b0fa27cd4987df09592f` on
  2026-06-15.

### PR 5: Expiring Conflict Risk Acceptance

Implemented:

- additive `0026_conflict_risk` migration with `risk_accepted_by`,
  `risk_accepted_at`, `risk_acceptance_expires_at`, and
  `risk_acceptance_json`;
- conflict response fields for risk acceptance ownership, expiry, and evidence;
- `accept_risk` governance service method;
- project-owner-only `decision -> risk_accepted` transition;
- required non-empty acceptance reason and mitigation plan;
- required future expiry for risk acceptance;
- durable conflict decision history with accepted-until and mitigation evidence;
- authenticated `POST /change/conflicts/{conflict_id}/accept-risk` API;
- audit event `document_conflict.accept_risk`;
- invalid-transition and expired-risk protections with no risk-acceptance
  history row.

Verification:

- focused backend suite:
  `uv run --directory apps/api --extra dev python -m pytest tests/test_persisted_conflict_scan.py tests/test_alembic_migrations.py tests/test_api_router_contract.py -q`
  returned `35 passed`;

Verification limitation:

- Disposable PostgreSQL migration cycle was not run locally because Docker CLI is
  unavailable in this Windows environment. The migration is additive, avoids
  extra foreign keys that are incompatible with the repository's partial CI
  migration harness, and is covered by source/model contract tests. GitHub CI
  must still prove runtime migration.

Merge and release:

- PR #51 merged to `main` at `c7177e0abe82b254f1ac44054fe518cb793271d2` on
  2026-06-15.
- Release `v0.7.0` was published and deployed to OCI production on 2026-06-15.

### PR 6: Change Audit Command Center Conflict Gates

Implemented:

- extended `ChangeAuditCommandCenterSummary` with persisted conflict counts:
  open conflicts, high open conflicts, expired risk acceptances, and
  accepted-revision conflicts;
- included `DocumentConflict` lifecycle state in `/change/command-center`;
- release gate now blocks for high open persisted conflicts, expired conflict
  risk acceptances, and accepted revisions that still need applied-change rescan
  closure;
- added actionable risk items and priority action routing operators to
  `/documents/contradictions`.

Verification:

- focused RED test first failed because command center incorrectly passed with
  persisted conflict risks;
- focused backend suite:
  `uv run --directory apps/api --extra dev python -m pytest tests/test_change_audit_command_center.py -q`
  returned `3 passed`;
- related backend suite:
  `uv run --directory apps/api --extra dev python -m pytest tests/test_change_audit_command_center.py tests/test_persisted_conflict_scan.py tests/test_api_router_contract.py -q`
  returned `26 passed`;

## Next Actions

1. Push PR 6 and require CI evidence before merge.
2. After PR 6 is merged, continue with frontend command center surfacing and
   operator workflow polish.
