# Current Main Release Evidence

Date: 2026-06-20

Status: proposed current-main evidence package. Owner Go is required before this
document is treated as release authority for any future promotion.

## Current Main

- Current `origin/main` SHA after PR #155:
  `f6de1ceae1aedb25fb6cc16beef537c22ff54b2f`
- Current main includes PR #155, which is documentation/process-only and was
  not tagged or deployed.
- No tag was created for
  `f6de1ceae1aedb25fb6cc16beef537c22ff54b2f` in this task.
- No deployment was performed in this task.

## Latest Verified Production Release

- Release tag used for the latest verified production deployment: `v1.0.13`
- Release URL: <https://github.com/BizYan/AMX/releases/tag/v1.0.13>
- Tagged/deployed SHA:
  `c45f56c6a1f6681f92eafba7f94fced12ef17d4b`
- `v1.0.13` is the latest non-prerelease GitHub Release.
- `v1.0.11` and `v1.0.12` are prerelease records from failed or superseded
  production promotion attempts and must not be used as rollback targets.

## PR Reconciliation

| PR | Merge SHA | Classification | Notes |
| --- | --- | --- | --- |
| [#139](https://github.com/BizYan/AMX/pull/139) | `7fc1fdbec9f078aa3db45bf91e8f1d2d15c92bb6` | Release/candidate gate hardening | Hardened real API authenticated smoke evidence boundary. |
| [#140](https://github.com/BizYan/AMX/pull/140) | `847262b3f336af8c8434905dc19640a46bcb6411` | Product capability completion | Source to Knowledge production loop. |
| [#141](https://github.com/BizYan/AMX/pull/141) | `d8f331382ad1038e9bda121671542d22aa4f951d` | Product capability completion | Provider-backed document generation/export evidence loop. |
| [#142](https://github.com/BizYan/AMX/pull/142) | `80b9784e7fe697d32602b864c5c49a339ecc568b` | Product capability completion | Customer delivery and acceptance closure evidence. |
| [#143](https://github.com/BizYan/AMX/pull/143) | `6fe84256305667f8e172595a4ae6d1594a8ac200` | Release/candidate gate hardening | Candidate provider readiness commissioning. |
| [#144](https://github.com/BizYan/AMX/pull/144) | `9d127f150c0b95c108267b11ac8f9c0f4ddbe9a2` | Release/candidate gate hardening | Non-secret candidate provider support. |
| [#145](https://github.com/BizYan/AMX/pull/145) | `7de34bcb9fbe7a6c9899745f581b7638fa9813a2` | Release/candidate gate hardening | Candidate readiness summary output fix. |
| [#146](https://github.com/BizYan/AMX/pull/146) | `7eb53be27ca3e90399af686431d29f02625b55fb` | Release/candidate gate hardening | Candidate capability evidence activation. |
| [#147](https://github.com/BizYan/AMX/pull/147) | `ce9634b94a0414911b1a24076d5e298847f27481` | Product capability completion | Agent workflow runtime evidence loop. |
| [#148](https://github.com/BizYan/AMX/pull/148) | `8e935abed7adbcc50a82187190ee481a26bd1fbc` | Product capability completion | Jira project sync connector path. |
| [#149](https://github.com/BizYan/AMX/pull/149) | `9c8817eab0ba19f40e81ef7cbd2c6ad3e6e3c7ad` | Production deployment hotfix | Production provider readiness gate alignment. |
| [#150](https://github.com/BizYan/AMX/pull/150) | `89d8975deb8aa47c10f6e6a3b5221de2cc7ba1cf` | Production deployment hotfix | Avoided provider bootstrap relationship load. |
| [#151](https://github.com/BizYan/AMX/pull/151) | `e52a14c52d642a9f247ae2106293e9597df94ebb` | Schema compatibility hotfix | Provider runs schema alignment. |
| [#152](https://github.com/BizYan/AMX/pull/152) | `9dc27e74f93c4e41e060eecb410fc3e910542e48` | Schema compatibility hotfix | Ops metric schema alignment for activation. |
| [#153](https://github.com/BizYan/AMX/pull/153) | `fb1d3984e9bc3110707c4fd6c871d4b1dcd5e371` | Schema compatibility hotfix | Legacy evidence column nullability. |
| [#154](https://github.com/BizYan/AMX/pull/154) | `c45f56c6a1f6681f92eafba7f94fced12ef17d4b` | Production deployment hotfix | Production capability activation before smoke. |
| [#155](https://github.com/BizYan/AMX/pull/155) | `f6de1ceae1aedb25fb6cc16beef537c22ff54b2f` | Documentation/process improvement | Forward-fix incident lesson in continuous improvement registry. |

## CI Evidence

Current-main CI evidence is PR #155 because it is the merge that produced
`f6de1ceae1aedb25fb6cc16beef537c22ff54b2f`.

- PR #155: <https://github.com/BizYan/AMX/pull/155>
- API tests: success
- Web typecheck and build: success
- Web deterministic E2E: success
- Docker Compose config: success
- PR agent and GitNexus evidence: success
- Agent collaboration contract: success

PR #154, the latest production-affecting merge before `v1.0.13`, also passed
required CI and governance checks before it was merged.

## Candidate API Runtime Evidence

Candidate verification exists for the deployed release SHA, not for the
docs-only current-main SHA after PR #155.

- Candidate verification run:
  <https://github.com/BizYan/AMX/actions/runs/27859671545>
- Run ID: `27859671545`
- Conclusion: success
- Verified SHA:
  `c45f56c6a1f6681f92eafba7f94fced12ef17d4b`
- Important successful steps:
  - exact SHA and main lineage verification;
  - isolated candidate names and candidate-only environment;
  - rendered candidate Compose config inspection;
  - isolated candidate stack startup;
  - historical migration compatibility baseline verification;
  - candidate API server startup;
  - candidate `/health`;
  - candidate provider readiness commissioning;
  - candidate capability activation;
  - candidate authenticated smoke;
  - sanitized log collection;
  - teardown and artifact upload.

No candidate verification run was dispatched for
`f6de1ceae1aedb25fb6cc16beef537c22ff54b2f` because PR #155 was documentation
only and this task explicitly forbids tag creation and deployment.

## Production Deployment Evidence

- Production deployment run:
  <https://github.com/BizYan/AMX/actions/runs/27859794863>
- Run ID: `27859794863`
- Conclusion: success
- Deployed ref: `v1.0.13`
- Deployed SHA:
  `c45f56c6a1f6681f92eafba7f94fced12ef17d4b`
- Successful deployment steps:
  - canonical Public AMX path validation;
  - OCI deployment;
  - production health check;
  - production capability evidence activation;
  - authenticated production smoke;
  - GitNexus deploy and refresh;
  - deployment provenance verification.

Production was not redeployed after PR #155. That is intentional: PR #155 is
documentation/process-only and does not change runtime behavior.

## Production Readiness Results

Read-only production checks were executed against the deployed `v1.0.13` runtime
on OCI using the local API bind address.

| Gate | Result | Evidence |
| --- | --- | --- |
| `/health` | Pass | `{"status":"healthy","version":"1.0.0"}` |
| Capability activation | Pass / idempotent | Deployment run step succeeded; later read-only repeat returned `executed=false` because readiness was already satisfied. |
| Authenticated production smoke | Pass | `infra/deploy/authenticated-smoke.sh --base-url http://127.0.0.1:18000` completed successfully. |
| Provider readiness | Pass | `production_ready=true`, `live_providers=1`, `missing_required_types=[]`, required LLM type ready. |
| Quota readiness | Pass | `limit=1000`, numeric positive quota limit. |
| Capability readiness | Pass | `production_ready=true`, `overall_status=ready`, `overall_score=93`, `capability_count=11`. |
| Capability commissioning | Pass | `production_usable=true`, `overall_status=ready`, `overall_score=100`. |
| GitNexus deploy/refresh | Pass | Deployment workflow step `Deploy and refresh GitNexus` succeeded. |
| Deployment provenance | Pass | `status=verified`, deployed SHA equals expected SHA, tracked worktree clean, GitNexus indexed SHA equals deployed SHA. |

Deployment provenance verified:

```text
expected_ref: v1.0.13
recorded_ref: v1.0.13
expected_sha: c45f56c6a1f6681f92eafba7f94fced12ef17d4b
deployed_sha: c45f56c6a1f6681f92eafba7f94fced12ef17d4b
tracked_worktree_clean: true
running_services: api, postgres, redis, web, worker
gitnexus_healthy: true
gitnexus_indexed_sha: c45f56c6a1f6681f92eafba7f94fced12ef17d4b
```

## Evidence Boundaries

### CI Evidence

CI evidence proves repository tests, governance checks, deterministic E2E, and
Docker Compose config checks for the PR merge boundary. CI does not prove that a
specific production ref was deployed.

### Candidate API Runtime Evidence

Candidate evidence proves isolated API runtime startup, migration compatibility
baseline verification, provider readiness commissioning, capability activation,
authenticated smoke, and teardown for the exact candidate SHA
`c45f56c6a1f6681f92eafba7f94fced12ef17d4b`.

### Production Deployment Evidence

Production evidence proves OCI deployment, production health, activation,
authenticated smoke, GitNexus refresh, and provenance for `v1.0.13` /
`c45f56c6a1f6681f92eafba7f94fced12ef17d4b`.

### Browser Commercial Delivery Evidence

No new browser commercial-delivery validation was produced by this documentation
task. Earlier PRs include deterministic Playwright and focused UI evidence, but
that is regression or workflow evidence, not a fresh full frontend
commercial-delivery validation for current main.

### Historical Release Evidence

`docs/releases/v1.0.0.md` is historical Batch 10 release evidence tied to older
SHAs and older release decisions. It must not be reused as the current release
authority for `f6de1ceae1aedb25fb6cc16beef537c22ff54b2f` or `v1.0.13`.

The file remains explicitly marked as historical evidence in its
`Post-Promotion Governance Note`.

## Rollback Target

For any future promotion from current main, the rollback target should be the
latest verified production release:

- Rollback target: `v1.0.13`
- Rollback SHA:
  `c45f56c6a1f6681f92eafba7f94fced12ef17d4b`

Do not select `v1.0.8`, `v1.0.9`, `v1.0.10`, `v1.0.11`, or `v1.0.12` as
rollback targets for this evidence package; they are failed, superseded, or
prerelease promotion records from the forward-fix sequence.

## Unresolved Gaps

- Current `origin/main` after PR #155 has no tag and no candidate/deployment run
  of its own. This is acceptable only because PR #155 is documentation/process
  improvement and no runtime behavior changed.
- No fresh browser commercial-delivery validation was produced in this task.
- Runtime `/health` still reports application version `1.0.0` while the GitHub
  release tag is `v1.0.13`; this is a version-reporting gap, not a deployment
  provenance mismatch.
- Production logs still show a non-blocking SQLAlchemy cartesian product warning
  on document listing. It did not block authenticated smoke or provenance but
  should be handled in a separate focused PR.

## Decision

This document is ready for Owner review as a current-main release evidence
package. It should not be treated as authoritative release approval until Owner
Go is explicitly granted.
