# Production Deployment Evidence Latest

Date: 2026-07-15

Status: verified production deployment.

## Release Identity

- Tag: v1.0.16.
- Immutable SHA: 1a0e3111b5fa1f128d88f63d8e6ca7cca0785d33.
- Release: [AMX v1.0.16](https://github.com/BizYan/AMX/releases/tag/v1.0.16).
- Candidate verification: [29376255805](https://github.com/BizYan/AMX/actions/runs/29376255805).
- Release quality gates: [29376386614](https://github.com/BizYan/AMX/actions/runs/29376386614).
- Production deployment: [29376624267](https://github.com/BizYan/AMX/actions/runs/29376624267).

## Production Gates

All production workflow gates passed:

- canonical OCI production path validation;
- deploy of ref v1.0.16;
- /health;
- capability activation;
- authenticated smoke;
- GitNexus deployment and refresh;
- deployment provenance.

Authenticated smoke confirmed real login, current-user, projects, documents,
provider readiness, quota readiness, capability readiness, and capability
commissioning. The smoke contract fails closed for missing credentials, failed
login, sandbox/mock/test-only provider readiness, or placeholder-only capability
evidence.

Capability activation found the deployed system already production-ready and did
not execute new activation actions.

## Provenance

~~~text
status: verified
expected_ref: v1.0.16
recorded_ref: v1.0.16
expected_sha: 1a0e3111b5fa1f128d88f63d8e6ca7cca0785d33
deployed_sha: 1a0e3111b5fa1f128d88f63d8e6ca7cca0785d33
tracked_worktree_clean: true
running_services: postgres, redis, api, worker, web
gitnexus_healthy: true
gitnexus_indexed_sha: 1a0e3111b5fa1f128d88f63d8e6ca7cca0785d33
~~~

## Rollback

Immediate rollback target: v1.0.15 /
3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9.

No manual OCI modification was used. Rollback, if required, must use the
existing production deployment workflow with the approved immutable rollback
tag.

## Boundaries

This deployment evidence does not replace the separate staging browser
commercial-delivery evidence, live Jira verification, live agent provider/tool
verification, or a production browser journey. No raw secrets, tokens, or
customer data are included in this record.
