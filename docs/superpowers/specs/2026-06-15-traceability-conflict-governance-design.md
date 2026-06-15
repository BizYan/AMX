# Traceability Conflict Governance Design

Date: 2026-06-15

## Summary

AMX will turn its existing traceability and contradiction capabilities into a
complete conflict-resolution workflow. Auditable rules create and refresh
persisted document conflicts. Owners analyze and decide them. Accepting a
revision creates a linked change-request draft. A conflict closes only after the
change is applied and a traceability rescan confirms resolution. Unresolved
high-risk conflicts block formal delivery unless an authorized risk acceptance
is recorded.

The design extends the existing `change` and traceability domain so conflict
evidence, impact analysis, change execution, audit history, and delivery gates
share one authoritative model.

## Goals

- Make detected document conflicts durable, queryable, assignable, and auditable.
- Provide a governed path from detection through decision, change execution,
  rescan, and closure.
- Preserve human authority over decisions, document changes, risk acceptance, and
  closure.
- Enforce risk-based formal-delivery gates.
- Expose the capability through existing project, collaboration, audit, and
  delivery entry paths.

## Non-Goals

- AI does not create authoritative conflicts, make final decisions, modify
  documents, submit changes, or close conflicts.
- No cross-tenant conflict analysis.
- No replacement of the existing change-request approval or document lifecycle.
- No broad redesign of traceability, collaboration, audit, or delivery pages
  outside the integration needed for this workflow.

## Architecture

The capability belongs in `apps/api/app/domains/change` because that domain
already owns traceability references, impact analysis, sync proposals, change
requests, and audit-oriented release-readiness summaries.

The existing traceability rule engine remains the source of authoritative
conflict findings. A new conflict-governance service persists findings, resolves
assignments, applies status transitions, records decisions, links change
requests, and evaluates closure eligibility.

Existing audit logging, permission checks, project delivery readiness, and
frontend API-client patterns must be reused. No independent conflict permission
system or duplicated delivery-gate engine will be introduced.

## Domain Model

### DocumentConflict

Canonical persisted conflict record:

- tenant and project;
- stable rule key and deterministic fingerprint;
- severity: `high`, `medium`, or `low`;
- status;
- primary and related document IDs and pinned detected versions;
- structured rule evidence and human-readable summary;
- assignee and assignment source;
- first detected, last detected, due, resolved, and closed timestamps;
- linked change-request ID when revision is accepted;
- current risk-acceptance fields where applicable.

The deterministic fingerprint identifies the same logical conflict across
rescans. It is derived from tenant, project, rule key, affected document IDs,
relevant sections, and other rule-stable identifiers. Mutable summaries and
timestamps are excluded.

### ConflictDecision

Append-only decision and history record:

- conflict, tenant, project, actor, and timestamp;
- action;
- previous and resulting status;
- reason or decision note;
- structured supporting evidence;
- linked change request or traceability rescan where relevant.

Assignment changes, AI-analysis requests, accepted revisions, rejections, risk
acceptances, reopen actions, rescan results, and closure decisions all produce
history records.

### Existing Models

- `ChangeRequest` remains the authoritative controlled-change workflow.
- `DocumentReference`, `DocumentImpactAnalysis`, and `DocumentSyncProposal`
  remain authoritative traceability and downstream-impact records.
- Existing audit events remain the system-wide evidence feed.

## Status Model

Primary progression:

`unassigned -> analysis -> decision -> revision_accepted | rejected | risk_accepted -> closed`

Rules:

- A scan creates a conflict as `unassigned` when no owner can be resolved;
  otherwise it creates it as `analysis`.
- Assignment or reassignment moves `unassigned` to `analysis`.
- Completing analysis moves the conflict to `decision`.
- Accepting revision moves it to `revision_accepted` and creates a linked
  change-request draft.
- Rejecting a false or inapplicable finding moves it to `rejected`; rejection
  requires a reason and remains auditable.
- Authorized risk acceptance moves an unresolved conflict to `risk_accepted`;
  it does not erase the finding.
- `revision_accepted` can move to `closed` only after the linked change request is
  applied and a rescan no longer produces the fingerprint.
- `rejected` and `risk_accepted` may close through an authorized explicit close
  action with reason.
- Any closed conflict may be reopened by a later rule scan if the same
  fingerprint reappears.

Invalid transitions return a conflict response and do not mutate state.

## Detection And Rescan

Rule-based detection is authoritative. The first implementation should adapt the
existing traceability conflict rules and add rules only when they are
deterministic and testable.

Scan behavior:

1. evaluate rules within one tenant and project;
2. calculate a deterministic fingerprint per finding;
3. insert new findings;
4. refresh evidence and `last_detected_at` for existing findings;
5. reopen a closed finding if its fingerprint reappears;
6. mark previously active findings as absent from the latest scan without
   automatically closing them;
7. record scan evidence and summary counts.

Concurrent scans must not create duplicate fingerprints. Database uniqueness and
transactional service logic jointly enforce idempotency.

## Assignment

Default assignment order:

1. primary affected document owner;
2. related affected document owner;
3. project lead fallback queue.

Authorized users may manually reassign a conflict. Each assignment records the
previous assignee, new assignee, actor, reason, and assignment source.

The collaboration center exposes assigned conflicts as actionable review work,
but `DocumentConflict` remains authoritative rather than being reduced to a
generic collaboration work item.

## AI Advisory Analysis

AI analysis may summarize likely causes, affected downstream documents, and
candidate revision language. The generated output is stored as advisory evidence
with provider/model metadata where available.

AI output cannot:

- create or remove an authoritative rule finding;
- select the final decision;
- change a document;
- submit or approve a change request;
- accept risk;
- close a conflict.

Provider failure leaves the conflict actionable through rule evidence and human
analysis.

## Change-Request Linkage

Accepting revision performs one transaction that:

1. validates permission and current status;
2. creates a `ChangeRequest` in draft state;
3. includes conflict evidence, affected documents, impact summary, and suggested
   revision in the draft;
4. links the change request to the conflict;
5. records a conflict decision and system audit event;
6. moves the conflict to `revision_accepted`.

The existing change workflow then governs editing, submission, approval,
application, and cancellation.

If the linked change is cancelled or rejected, the conflict returns to
`decision` through an explicit governed action; it does not silently close.

## Closure And Rescan

For an accepted revision, closure eligibility requires:

- linked change request status is `applied`;
- a post-application scan has completed;
- the conflict fingerprint is absent from that scan.

If the fingerprint remains, the conflict stays open and records the failed
rescan evidence. If it disappears, an authorized user may close it and the
closure history records the applied change and confirming scan.

## Delivery Gates

Formal delivery readiness evaluates persisted conflicts:

- unresolved `high` conflicts block formal delivery;
- `high` conflicts with valid authorized risk acceptance do not block, but remain
  visible in delivery evidence;
- unresolved `medium` and `low` conflicts generate warnings;
- closed conflicts do not block but remain in the audit trail.

A valid risk acceptance requires an authorized actor, reason, timestamp, and
supporting evidence. Reopening or materially changing the conflict invalidates
the previous acceptance and requires a new decision.

## API Surface

The change router adds project-scoped conflict endpoints following existing
tenant and project access patterns:

- scan/rescan conflicts;
- list conflicts with project, severity, status, assignee, and overdue filters;
- get conflict detail and history;
- assign or reassign;
- request AI advisory analysis;
- complete human analysis;
- accept revision and create change-request draft;
- reject finding;
- accept risk;
- reopen;
- run closure rescan;
- close when eligible.

Write endpoints enforce permission and state-transition checks. The
accept-revision operation is atomic. List and detail responses include explicit
available actions so the frontend does not infer authorization from status
alone.

## Frontend

The existing `/documents/contradictions` route becomes the persistent
conflict-resolution center.

The list supports:

- project, severity, status, assignee, and overdue filters;
- search over document title, rule, evidence, and decision summary;
- clear loading, empty, error, and rescan states.

The detail panel shows:

- authoritative rule and evidence;
- affected documents and detected versions;
- assignment and due status;
- traceability impact;
- advisory AI analysis;
- decision history;
- linked change request and execution status;
- only the actions currently authorized and valid.

Integration entry points:

- project cockpit shows unresolved conflict counts and highest risk;
- collaboration center shows assigned conflict work;
- audit center includes conflict decisions and risk acceptance;
- delivery readiness shows blockers, warnings, and accepted risks with links.

## Permissions And Audit

Existing project and document permissions are reused where possible:

- readers may view conflicts for accessible projects;
- document owners and authorized reviewers may analyze and propose decisions;
- project leads or equivalent managers may assign and reassign;
- existing change permissions govern the linked change request;
- risk acceptance and final closure require explicit elevated permission aligned
  with delivery approval authority.

Every state-changing operation emits both a conflict history record and the
appropriate system audit event.

## Error Handling

- Duplicate or concurrent scan findings resolve to the same fingerprint record.
- Invalid transitions return a clear conflict response without partial writes.
- Accept-revision transaction failure creates neither a decision nor a change
  request.
- AI advisory failure preserves rule evidence and reports a retryable analysis
  error.
- Missing owners route to the project-lead fallback queue.
- Failed closure rescans preserve the open conflict and record why it remains.
- Delivery-gate evaluation degrades conservatively: inability to verify
  high-risk conflict state blocks formal delivery rather than silently passing.

## Testing

Backend:

- migration upgrade and downgrade for additive models;
- deterministic fingerprint and concurrent scan idempotency;
- rule finding creation, refresh, absence, reopen, and rescan;
- assignment fallback and reassignment audit;
- every valid and invalid status transition;
- tenant, project, and permission isolation;
- atomic accepted-revision change-draft creation;
- closure eligibility after applied change and confirming rescan;
- high-risk blocking, medium/low warning, and authorized risk acceptance.

Frontend:

- API-backed persistent conflict list and detail;
- filters, rescan, assignment, analysis, decisions, and linked-change navigation;
- action visibility based on available actions;
- loading, empty, error, and invalid-transition feedback;
- discoverability through project, collaboration, audit, and delivery paths.

Verification per PR follows the repository development verification standard.
The final program gate includes focused production-path acceptance.

## Delivery Plan

The domain maturity program is delivered through five substantial PRs:

1. persisted conflict model and idempotent rule scan;
2. assignment, status governance, permission, and audit history;
3. change-request linkage, applied-change verification, rescan, and closure;
4. API-backed conflict-resolution center;
5. project, collaboration, audit, delivery-gate integration, and production
   acceptance evidence.

## Rollback

The new models and endpoints are additive. Application behavior and navigation
can be reverted while existing traceability and change workflows continue to
operate. Migration downgrade is permitted only after verifying that no unique
conflict-governance evidence must be retained. Production rollback follows the
repository release and deployment runbook.
