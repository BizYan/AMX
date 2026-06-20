# Current Main Release Evidence

Date: 2026-06-21

Status: proposed current-main release evidence package. Owner Go is required
before this document is treated as release authority for any future promotion.

This document replaces the stale post-PR-155 evidence package. It reconciles PR
#156 through #169, compares the requested `v1.0.13` baseline with current main,
and records the newer verified production release evidence that now exists.

## Current Main

- Current `origin/main` SHA after PR #169:
  `50e2d5ee4405a31797297cf13a78f70bd196d2c6`
- Current main includes PR #156 through PR #169.
- Current main is ahead of latest verified production by PR #164 through PR
  #169.
- Latest verified production remains `v1.0.15` /
  `3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9`.
- No tag or deployment was created by this documentation task.

## Requested Comparison Baseline

The task requested comparison against latest verified production release
`v1.0.13` / `c45f56c6a1f6681f92eafba7f94fced12ef17d4b`.

- Release: <https://github.com/BizYan/AMX/releases/tag/v1.0.13>
- Release workflow run:
  <https://github.com/BizYan/AMX/actions/runs/27859715478>
- Candidate verification run:
  <https://github.com/BizYan/AMX/actions/runs/27859671545>
- Production deployment run:
  <https://github.com/BizYan/AMX/actions/runs/27859794863>
- Deployment conclusion: success

That baseline is no longer the latest verified production state. It remains a
known-good historical rollback point, but current production has since advanced.

## Latest Verified Production Release

- Latest verified production release: `v1.0.15`
- Release URL: <https://github.com/BizYan/AMX/releases/tag/v1.0.15>
- Release workflow run:
  <https://github.com/BizYan/AMX/actions/runs/27876474255>
- Candidate verification run:
  <https://github.com/BizYan/AMX/actions/runs/27876425481>
- Production deployment run:
  <https://github.com/BizYan/AMX/actions/runs/27876577603>
- Deployed ref: `v1.0.15`
- Deployed SHA:
  `3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9`
- Deployment conclusion: success

The deployment provenance verified:

```text
status: verified
expected_ref: v1.0.15
recorded_ref: v1.0.15
expected_sha: 3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9
deployed_sha: 3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9
tracked_worktree_clean: true
running_services: api, postgres, redis, web, worker
gitnexus_healthy: true
gitnexus_indexed_sha: 3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9
```

## PR Reconciliation: #156 Through #169

| PR | Merge SHA | Classification | Runtime impact | Notes |
| --- | --- | --- | --- | --- |
| [#156](https://github.com/BizYan/AMX/pull/156) | `1d86e02044faf7d19792ee438d45ba5f300ae748` | Documentation/process improvement | None | Rebuilt current-main release evidence after production forward fixes. |
| [#157](https://github.com/BizYan/AMX/pull/157) | `7fd12d507660e103adaad4d0e6fa862baa8e95fe` | Release/candidate gate hardening | CI/migration governance only | Added production-like historical schema compatibility gate and runbook. |
| [#158](https://github.com/BizYan/AMX/pull/158) | `2916b15e0a028b76d95d1cafc1c97893c9dc325b` | Production deployment hotfix | Deployment gate script | Made production capability activation evidence idempotent for already-ready runtime state. |
| [#159](https://github.com/BizYan/AMX/pull/159) | `e63fd4961cce01ec127f73ddbb7a4dc318bb571c` | Release/candidate gate hardening | Test selectors only | Added gated real-backend browser commercial delivery validation path. |
| [#160](https://github.com/BizYan/AMX/pull/160) | `337b41635580e60e6d72e6f208711617738da8b7` | Productized ops/agent validation milestone | Agent runtime evidence and Agent Ops UI | Added provider/tool interaction evidence, retry/cancel evidence, and cockpit visibility. |
| [#161](https://github.com/BizYan/AMX/pull/161) | `754865b7c0f3ac1a89f6fb6dfe85180c4adab14b` | Release/candidate gate hardening | Verification script/test only | Added live Jira connector candidate verification path; no live Jira success claimed. |
| [#162](https://github.com/BizYan/AMX/pull/162) | `27d05a7d9cd8e4cd066777cd9dd0dd7f3713ba2e` | Productized ops evidence surface | Read-only ops API and dashboard UI | Added ops readiness dashboard aggregation, display, and sanitized evidence export. |
| [#163](https://github.com/BizYan/AMX/pull/163) | `3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9` | Documentation/process improvement | None | Adopted forward-fix release incident governance from IMP-007. |
| [#164](https://github.com/BizYan/AMX/pull/164) | `224bac6525a3260c94ac0f562576a37b559e3d11` | Documentation/process improvement | None | Rebuilt post-PR-163 release evidence; superseded by this current-main update after later merges. |
| [#167](https://github.com/BizYan/AMX/pull/167) | `1370ca9c9220741f9863ae520ba0d728224a8dcf` | Release/candidate gate hardening | Pull request governance only | Fixed Dependabot dependency delta validation to compare from merge-base. |
| [#166](https://github.com/BizYan/AMX/pull/166) | `a9ddf26dcf9a3810c2fdada72cfb62ae0657a995` | Dependency maintenance | Dev/test dependency only | Updated `@playwright/test` from `1.60.0` to `1.61.0`. |
| [#168](https://github.com/BizYan/AMX/pull/168) | `b3294447ed90b4854aa0ed5e3034acc59ab1f808` | Release/candidate gate hardening | Test governance only | Allowed same-major bcrypt maintenance upper-bound updates while preserving explicit upper-bound enforcement. |
| [#165](https://github.com/BizYan/AMX/pull/165) | `24446cd40ad96936cef477b93d53c6a7516c84ba` | Dependency maintenance | API dependency range | Updated `bcrypt` requirement from `<4.1` to `<4.3`; full PR CI passed before merge. |
| [#169](https://github.com/BizYan/AMX/pull/169) | `50e2d5ee4405a31797297cf13a78f70bd196d2c6` | Documentation/process improvement | None | Refreshed current-main release evidence after dependency merges. |

## Post-v1.0.15 Main Delta

Comparison range:

```text
3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9..50e2d5ee4405a31797297cf13a78f70bd196d2c6
```

Changed files:

- `.github/workflows/collaboration-governance.yml`
- `apps/api/pyproject.toml`
- `apps/api/tests/test_dependency_automation_contract.py`
- `apps/web/package.json`
- `apps/web/pnpm-lock.yaml`
- `docs/releases/current-main-release-evidence.md`

Impact:

- Runtime impact: `bcrypt` allowed maintenance range changed from `<4.1` to
  `<4.3`; no application code changed.
- Test-only impact: dependency automation contract now validates explicit
  same-major bcrypt upper bounds instead of hardcoding `<4.1`.
- Docs-only impact: current-main release evidence refreshed after post-PR-163
  merges.
- Deployment impact: none yet. No candidate verification, tag, release, or
  production deployment has been run for
  `50e2d5ee4405a31797297cf13a78f70bd196d2c6`.

## Post-v1.0.13 Release Delta

Comparison range:

```text
c45f56c6a1f6681f92eafba7f94fced12ef17d4b..50e2d5ee4405a31797297cf13a78f70bd196d2c6
```

### Runtime Impact

- `apps/api/app/domains/agent/service.py`: agent workflow interaction evidence,
  redaction, retry/cancel evidence.
- `apps/api/app/domains/ops/readiness_dashboard.py`: new read-only ops readiness
  aggregation service.
- `apps/api/app/domains/ops/router.py` and `schemas.py`: new ops dashboard
  endpoint and response schema.
- `apps/web/src/app/(app)/agent-ops/page.tsx`: Agent Ops run evidence display.
- `apps/web/src/app/(app)/health/page.tsx`: ops readiness dashboard evidence UI.
- `apps/web/src/lib/api-client.ts`: ops readiness dashboard client contract.
- `infra/deploy/activate-capability-evidence.sh`: idempotent production
  activation gate handling.

### Test-Only Impact

- Production-like schema compatibility test:
  `apps/api/tests/test_production_schema_compatibility.py`.
- Agent runtime evidence tests:
  `apps/api/tests/test_agent_runtime_production_loop.py`.
- Authenticated smoke contract test update:
  `apps/api/tests/test_authenticated_smoke_contract.py`.
- Jira verification contract tests:
  `apps/api/tests/test_integration_project_sync.py`.
- Ops readiness dashboard tests:
  `apps/api/tests/test_ops_readiness_dashboard.py`.
- Playwright coverage:
  `agent-orchestration.spec.ts`,
  `ops-readiness-dashboard.spec.ts`,
  `real-browser-commercial-delivery.spec.ts`.
- Playwright mock fixtures updated for ops dashboard evidence.

### Docs-Only Impact

- `docs/releases/current-main-release-evidence.md`.
- `docs/runbooks/development-verification-standard.md`.
- `docs/runbooks/live-jira-connector-verification.md`.
- `docs/runbooks/production-schema-compatibility.md`.
- `docs/runbooks/oci-operations.md`.
- `docs/runbooks/release-management.md`.
- `docs/continuous-improvement/registry.json`.
- `AGENTS.md`.
- `.github/pull_request_template.md`.

### Deployment And CI Impact

- `.github/workflows/ci.yml` now runs the production-like schema compatibility
  gate.
- `infra/deploy/activate-capability-evidence.sh` changes production deployment
  gate behavior only by accepting an already-ready production state when the
  readiness evidence is still `production_ready=true`.
- `infra/deploy/live-jira-connector-verification.sh` adds a candidate/staging
  verification path; it does not alter production deployment behavior.
- Production deployment has already been completed for latest verified
  production `v1.0.15` in run `27876577603`.
- Current main after PR #169 has not yet been candidate verified, tagged,
  released, or deployed.

## Evidence By Boundary

### CI Evidence

Each PR #156 through #169 passed required PR checks before merge. Release
workflow `27876474255` for latest verified production `v1.0.15` also passed:

- Validate release tag;
- API tests;
- Docker Compose config;
- Web deterministic E2E;
- Web typecheck and build;
- Publish GitHub release.

### Candidate API Runtime Evidence

Candidate verification for latest verified production:

- Run: <https://github.com/BizYan/AMX/actions/runs/27876425481>
- Conclusion: success
- Verified SHA:
  `3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9`
- Evidence included:
  - exact SHA and origin/main lineage;
  - isolated Compose project `amx_rc_3cadf5d0e3f4`;
  - isolated database `amx_rc_3cadf5d0e3f4`;
  - rendered config inspection;
  - historical migration compatibility baseline verification;
  - candidate API health;
  - provider readiness commissioning;
  - capability activation;
  - authenticated smoke;
  - sanitized log collection;
  - teardown and artifact upload.

### Production Deployment Evidence

Production deployment for latest verified production:

- Run: <https://github.com/BizYan/AMX/actions/runs/27876577603>
- Conclusion: success
- Deployed ref: `v1.0.15`
- Deployed SHA:
  `3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9`
- Successful gates:
  - canonical Public AMX path validation;
  - OCI deployment;
  - production `/health`;
  - production capability activation evidence;
  - authenticated production smoke;
  - GitNexus deploy and refresh;
  - deployment provenance.

Production smoke evidence included:

```text
health ok
current user ok
projects ok
documents ok
provider readiness ok
quota ok
capability readiness ok
capability commissioning ok
all authenticated production checks passed
```

### Browser Commercial Delivery Evidence

PR #159 added the gated real-backend Playwright path. It has not yet produced a
successful real candidate or production browser journey. Deterministic
Playwright E2E remains regression evidence, not commercial-delivery proof.

Latest attempt:

- Evidence boundary:
  `docs/programs/browser-commercial-delivery-evidence-latest.md`.
- Command attempted with `RUN_REAL_BROWSER_DELIVERY_TEST=true`:
  `pnpm --dir apps/web exec playwright test tests/e2e/playwright/real-browser-commercial-delivery.spec.ts --reporter=list`.
- Result: failed closed before live execution because `E2E_WEB_URL`,
  `E2E_API_URL`, `E2E_USER_EMAIL`, and `E2E_PASSWORD` were not present in the
  local execution environment.
- No production browser readiness is claimed.

### Historical Release Evidence

`docs/releases/v1.0.0.md` remains historical release evidence tied to earlier
SHAs and must not be reused as current release authority.

## Release Path Decision

The requested decision was between:

- `v1.0.14` as post-v1.0 evidence hardening patch; or
- `v1.1.0-rc1` as productized ops/agent validation milestone.

Recommendation: choose the post-v1.0 evidence hardening patch path, not
`v1.1.0-rc1`.

Reason:

- PR #156, #157, #158, #159, #161, and #163 are evidence, test, deployment-gate,
  or governance hardening.
- PR #160 and #162 add meaningful ops/agent evidence surfaces, but their live
  commercial proof gaps remain open.
- A `v1.1.0-rc1` milestone should wait until live browser delivery, live Jira
  success, live agent provider/tool execution, and populated ops dashboard
  evidence are all produced and reviewed.

Important current-state correction:

- `v1.0.14` already exists and points to
  `337b41635580e60e6d72e6f208711617738da8b7`.
- Main after PR #163 was released and deployed as `v1.0.15`.
- Current main after PR #169 is ahead of `v1.0.15` and has not yet been
  candidate verified, tagged, released, or deployed.
- Do not create or reuse `v1.0.14` for current main.
- The forward-looking recommendation is: keep `v1.0.15` as the verified
  post-v1.0 hardening release; use `v1.1.0-rc1` only after the remaining live
  validation gaps are closed.

## Live Evidence Gaps

Current status:

| Evidence item | Status | Notes |
| --- | --- | --- |
| Real browser commercial delivery run | Not yet produced | PR #159 added the gated path; no successful real candidate/production run is recorded. |
| Live Jira success drill | Not yet produced | PR #161 added the candidate-safe script and runbook; live Jira credentials/environment evidence is still pending. |
| Live agent workflow provider/tool run | Not yet produced | PR #160 added synthetic provider/tool evidence and UI; live candidate/staging provider/tool run remains pending. |
| Ops dashboard populated runtime evidence | Partially produced | PR #162 added the dashboard; production deployment/smoke/GitNexus evidence exists, but a recorded dashboard export from production is not yet attached as release evidence. |
| Candidate verification for current main after PR #169 | Not yet produced | Current main is `50e2d5ee4405a31797297cf13a78f70bd196d2c6`; no candidate run is recorded for this SHA. |
| Production deployment for current main after PR #169 | Not yet produced | Latest deployment remains `v1.0.15` / `3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9`. |
| Production deployment for post-PR-163 ref | Produced | Run `27876577603` deployed `v1.0.15` / `3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9`. |

## Rollback Target

The task asked to confirm `v1.0.13` remains the rollback target unless Owner
approves a newer release.

Current fact:

- A newer release was approved, tagged, and deployed after PR #163.
- Current production is `v1.0.15` /
  `3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9`.
- Immediate rollback target for current production should be the previous
  verified production release:
  `v1.0.14` / `337b41635580e60e6d72e6f208711617738da8b7`.
- `v1.0.13` /
  `c45f56c6a1f6681f92eafba7f94fced12ef17d4b` remains an older known-good
  rollback point and the requested comparison baseline.

## Unresolved Gaps

- The release evidence document still requires Owner review before becoming
  release authority.
- Runtime `/health` still reports application version `1.0.0`; deployment
  provenance verifies the actual tag/SHA separately.
- No successful real browser commercial-delivery run is recorded.
- Latest real browser attempt failed closed because the target environment and
  required `E2E_*` runtime inputs were not available.
- No successful live Jira drill is recorded.
- No successful live agent workflow provider/tool run is recorded.
- No production ops dashboard export artifact is attached to this release
  evidence package.
- No candidate verification, tag, release, or production deployment is recorded
  for current main
  `50e2d5ee4405a31797297cf13a78f70bd196d2c6`.

## Decision

This document is ready for Owner review as the post-PR-163 current-main release
evidence package, refreshed after PR #169. It should not be treated as release
authority until Owner Go is explicitly granted.
