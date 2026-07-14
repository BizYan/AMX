# Current Main Release Evidence

Date: 2026-07-15

Status: proposed release evidence for current main. Owner Go is required before
this document becomes promotion authority. It supersedes stale current-main
statements that predate the successful staging commercial-delivery run.

## Release Position

- Current `origin/main` SHA: `66a09e0dd566df2838ba62766323180d49cc3867`.
- Current-main tag: no tag created.
- Latest verified production: `v1.0.15` /
  `3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9`.
- Production release: [v1.0.15](https://github.com/BizYan/AMX/releases/tag/v1.0.15).
- Verified production candidate run:
  [27876425481](https://github.com/BizYan/AMX/actions/runs/27876425481).
- Verified production deployment run:
  [27876577603](https://github.com/BizYan/AMX/actions/runs/27876577603).
- Immediate rollback target for production: `v1.0.14` /
  `337b41635580e60e6d72e6f208711617738da8b7`.

`docs/releases/v1.0.0.md` remains historical evidence only and must not be used
as authority for this mainline promotion.

## Post-v1.0.15 Delta

Range:

```text
3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9..66a09e0dd566df2838ba62766323180d49cc3867
```

### Runtime And Deployment Impact

- PRs [#172](https://github.com/BizYan/AMX/pull/172) and
  [#175](https://github.com/BizYan/AMX/pull/175) add the read-only release
  evidence console and the real staging commercial journey.
- PRs [#176](https://github.com/BizYan/AMX/pull/176) and
  [#177](https://github.com/BizYan/AMX/pull/177) harden isolated staging
  Compose identity and historical-schema compatibility preparation.
- PRs [#178](https://github.com/BizYan/AMX/pull/178) through
  [#194](https://github.com/BizYan/AMX/pull/194) correct the real delivery
  path: identities, source storage and search, ingestion visibility, customer
  portal lifecycle/download, acceptance ordering, delivery milestones, document
  type alignment, and durable sanitized evidence output.
- PRs [#165](https://github.com/BizYan/AMX/pull/165) through
  [#168](https://github.com/BizYan/AMX/pull/168) contain dependency and CI
  contract maintenance. PRs [#170](https://github.com/BizYan/AMX/pull/170) and
  [#171](https://github.com/BizYan/AMX/pull/171) record evidence boundaries.

The delta changes runtime, staging/deployment verification, UI delivery paths,
tests, dependencies, and documentation. It is not docs-only and requires a new
exact-SHA candidate verification before production promotion.

## Evidence By Boundary

### CI Evidence

Merged PRs passed their required checks before merge. This is regression and
contract evidence; it is not a substitute for a runtime deployment gate.

### Candidate API Runtime Evidence

The latest completed candidate verification applies only to `v1.0.15` SHA
`3cadf5d0e3f4e3402e02cc5eaf1053277ae901b9`. No candidate verification has
yet been recorded for `66a09e0dd566df2838ba62766323180d49cc3867`.

### Staging Browser Commercial Delivery Evidence

The exact current SHA completed a real non-mocked browser journey in an isolated
staging runtime:

- Run: [Deploy staging 29375316574](https://github.com/BizYan/AMX/actions/runs/29375316574).
- SHA: `66a09e0dd566df2838ba62766323180d49cc3867`.
- Result: success, including isolation, historical migration compatibility
  baseline, health, browser journey, sanitized artifact upload, and teardown.
- Detail: `docs/programs/browser-commercial-delivery-evidence-latest.md`.

This is real staging evidence, not production-browser evidence.

### Production Deployment Evidence

Only `v1.0.15` has verified production evidence. Run `27876577603` deployed the
tagged SHA, passed health, capability activation, authenticated smoke, GitNexus
refresh, and deployment provenance. It does not prove the current main SHA.

### Historical Release Evidence

`v1.0.0` and `v1.0.13` evidence remain historical release records. They are
known rollback/reference points, not current-main evidence.

## Current Gaps And Decision

| Gate | Current-main status |
| --- | --- |
| Exact-SHA candidate verification | Not recorded |
| Staging real browser commercial journey | Passed for `66a09e0...` |
| Current-main production deployment | Not recorded |
| Current-main production health/smoke/provenance | Not recorded |
| Live Jira success drill | Not recorded |
| Live agent provider/tool interaction | Not recorded |
| Production ops-dashboard evidence export | Not recorded |

Release decision: do not promote current main yet. The next required action is
to run candidate verification for the exact immutable promotion SHA after this
evidence update is merged. If it passes and Owner Go remains in force, create a
new patch release tag, deploy only through the production workflow, and update
this document with its production evidence. Do not reuse or move existing tags.
