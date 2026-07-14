# Current Main Release Evidence

Date: 2026-07-15

Status: verified release authority for v1.0.16. This record supersedes the
pre-promotion proposal. The documentation commit that carries this record is
not part of the released runtime; the release target below is immutable.

## Authoritative Release

- Release tag: v1.0.16.
- Release SHA: 1a0e3111b5fa1f128d88f63d8e6ca7cca0785d33.
- GitHub Release: [AMX v1.0.16](https://github.com/BizYan/AMX/releases/tag/v1.0.16).
- Candidate verification: [29376255805](https://github.com/BizYan/AMX/actions/runs/29376255805).
- Release quality gates: [29376386614](https://github.com/BizYan/AMX/actions/runs/29376386614).
- Production deployment: [29376624267](https://github.com/BizYan/AMX/actions/runs/29376624267).
- Production deployed ref/SHA: v1.0.16 /
  1a0e3111b5fa1f128d88f63d8e6ca7cca0785d33.
- Release conclusion: success.

The tag is annotated, exists remotely, and its peeled commit equals the deployed
SHA. At release time, origin/main resolved to that same SHA.

## Gate Evidence

### Candidate Runtime

Candidate run 29376255805 succeeded for the exact release SHA.

- Exact SHA and origin/main ancestry passed.
- Candidate project: amx_rc_1a0e3111b5fa.
- Candidate database: amx_rc_1a0e3111b5fa.
- Candidate network and volumes were SHA-derived and isolated.
- Rendered configuration never retained the raw candidate environment or compose
  configuration.
- Historical migration compatibility baseline verification passed. This is not a
  clean empty-database full-history migration proof.
- API health, provider commissioning, capability activation, authenticated smoke,
  sanitized log collection, and teardown passed.
- Runtime-started scope was PostgreSQL, Redis, and API. Worker and web remained
  configuration-isolated but were not candidate runtime-started.

### Release Quality Gates

Release run 29376386614 passed semantic-tag validation, mainline ancestry,
delivery-state validation, Docker Compose validation, API tests, schema
compatibility, web typecheck/build, deterministic E2E, and GitHub Release
publication.

API result: 702 passed. Warnings recorded by the test runner did not fail the
release gate.

### Production Deployment

Production run 29376624267 passed every required step:

- canonical production path validation;
- OCI deployment of v1.0.16;
- /health;
- capability activation;
- authenticated production smoke;
- GitNexus deployment and refresh;
- deployment provenance.

Authenticated smoke verified health, browser-independent login, current-user,
project list, document list, provider readiness, quota readiness, capability
readiness, and capability commissioning. It rejects missing credentials, failed
login, sandbox/mock/test-only provider readiness, and placeholder-only capability
evidence.

Capability activation reported production_ready=true without executing new
activation actions because the deployed runtime was already ready.

Deployment provenance verified:

~~~text
expected_ref: v1.0.16
recorded_ref: v1.0.16
expected_sha: 1a0e3111b5fa1f128d88f63d8e6ca7cca0785d33
deployed_sha: 1a0e3111b5fa1f128d88f63d8e6ca7cca0785d33
tracked_worktree_clean: true
running_services: postgres, redis, api, worker, web
gitnexus_healthy: true
gitnexus_indexed_sha: 1a0e3111b5fa1f128d88f63d8e6ca7cca0785d33
~~~

## Staging Commercial Delivery Evidence

The released runtime also has real non-mocked browser evidence in isolated
staging, at [run 29375316574](https://github.com/BizYan/AMX/actions/runs/29375316574).

- Staging runtime SHA: 66a09e0dd566df2838ba62766323180d49cc3867, an
  ancestor of the release SHA.
- The journey covered source upload, ingestion, knowledge/provenance, document
  delivery, review/approval, export, token-scoped portal download, acceptance,
  closeout, blocked paths, and teardown.
- Sanitized details: docs/programs/browser-commercial-delivery-evidence-latest.md.

This is staging browser evidence. It is not a claim that a production browser
journey has been executed.

## Release Delta

v1.0.16 includes the post-v1.0.15 runtime and verification work from
PRs [#172](https://github.com/BizYan/AMX/pull/172) and
[#175](https://github.com/BizYan/AMX/pull/175) through
[#195](https://github.com/BizYan/AMX/pull/195): ops evidence, isolated staging,
historical-schema compatibility, real source-to-delivery UI path corrections,
customer portal and acceptance closure, and durable sanitized evidence.

Open PR [#174](https://github.com/BizYan/AMX/pull/174) is not included in this
release.

## Rollback

Immediate rollback target: v1.0.15 /
3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9.

v1.0.14 and earlier releases remain older known-good references.
docs/releases/v1.0.0.md remains historical evidence only.

## Remaining Boundaries

- No real production browser commercial journey has been run.
- Live Jira success and live agent provider/tool interaction evidence remain
  separate, unrecorded validation scopes.
- A production ops-dashboard evidence export is not attached to this release
  package.
- Runtime /health reports application version 1.0.0; tag/SHA provenance is
  the authoritative release identity.

Any future runtime, dependency, workflow, migration, or deployment change needs
a new candidate verification and promotion record. Documentation-only evidence
updates do not alter the deployed runtime.
