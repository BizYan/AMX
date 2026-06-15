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

### Partial

- Conflict detection exists in backend traceability helpers and frontend-derived
  document comparisons, but there is no canonical persisted conflict record.
- The contradiction-resolution page can display and locally classify conflicts,
  but decisions are not durable domain events.
- Existing change requests and sync proposals can execute downstream changes,
  but accepting a conflict revision does not create a linked change-request draft.
- Delivery readiness includes traceability signals, but does not enforce the
  approved high-risk conflict policy.

### Missing

- Idempotent persisted conflict scan and rescan.
- Conflict assignment to document owners with project-lead fallback.
- Governed conflict status transitions and durable decision history.
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
- Conflict assignment defaults to the related document owner and may be manually
  reassigned.
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

- Branch: `feature/traceability-conflict-governance`
- Current phase: PR 1 implementation complete; final branch verification and PR preparation.
- Design: `docs/superpowers/specs/2026-06-15-traceability-conflict-governance-design.md`
- Implementation plan: `docs/superpowers/plans/2026-06-15-persisted-conflict-scan.md`
- Open PRs for this program: none.

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

## External Dependency

- PR #46, `infra: add evidence-driven continuous improvement loop`, is green and
  awaiting human merge authority. It is not a functional dependency for this
  program.

## Next Actions

1. Run final focused and full API verification after the evidence update.
2. Push PR 1 and require CI plus disposable PostgreSQL migration evidence before
   merge.
3. After PR 1 is ready or merged, plan PR 2 assignment, status governance,
   permissions, and audit history.
