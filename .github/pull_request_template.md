## Purpose

Describe the business or infrastructure outcome of this PR.

Risk level: Low / Medium / High / Release

Owner Go required before merge: Yes / No

Low-risk documentation-only PRs may set Owner Go required to `No` after
required checks pass. Product, API, security, migration, Docker, workflow,
release, deployment, and production PRs must set it to `Yes`.

## Scope

- [ ] Backend
- [ ] Frontend
- [ ] Infrastructure
- [ ] Documentation
- [ ] Tests only

State the reviewable unit of work. Avoid one-field or unrelated bundled PRs.

## Evidence

Paste the exact focused commands and results:

```text
git diff --check
uv run --directory apps/api --extra dev python -m pytest <focused-path>
pnpm --dir apps/web typecheck
pnpm --dir apps/web build  # if Next routes/pages/build-time imports changed
pnpm --dir apps/web exec playwright test <focused-spec>  # if user interaction changed
powershell -ExecutionPolicy Bypass -File infra\scripts\invoke-gitnexus-change-record.ps1 -RepoPath C:\amx\AMX-main -Scope compare -BaseRef main
```

Not run locally, with reason:

- Full API tests:
- Full deterministic E2E:
- Docker Compose config:

## Risk And Rollback

State the production risk, migration impact, and rollback command or Git ref.

For release or deployment PRs, state how candidate verification, exact SHA
evidence, health, authenticated smoke, provenance, teardown, and rollback
verification will be satisfied. A successful API candidate gate must not be
described as full frontend commercial-delivery validation unless a real
browser/user journey is also verified.

If this PR is a forward fix after a repeated production gate failure, identify
the preserved failing evidence, compare candidate and production gates, classify
the failure, explain why additional rollback loops were stopped, and state the
Owner Go required before retrying deployment. This does not weaken normal
rollback for unrelated catastrophic failures.

## Agent Attribution

State whether Codex, Antigravity, Claude, or a human authored the change. Include branch names for any agent side branches and summarize any temporary agent handoff.

## GitNexus Impact Record

- [ ] `gitnexus status` was checked at task start.
- [ ] `gitnexus analyze --index-only` was run only if stale or needed for evidence, or unavailable fallback is documented.
- [ ] `gitnexus status` output is summarized with indexed commit and current commit.
- [ ] Relevant MCP/CLI query/context/impact commands and results are summarized, or reason they were unnecessary is stated.
- [ ] Impacted pages, APIs, services, models, workers, data tables, and tests are listed.
- [ ] `infra\scripts\invoke-gitnexus-change-record.ps1` output is summarized, including Git evidence status, GitNexus symbol status, fallback status, or an equivalent explicit-`--repo` GitNexus/MCP result plus raw `git diff` and untracked-file list is summarized.
- [ ] GitNexus result was used as context only; tests and review remain the correctness gate.

## Batch Completion Checklist

- Batch number:
- PRs included:
- Acceptance items:
- Verification evidence:
- Unresolved gaps:
- Next-Batch decision:
- [ ] This PR is not being treated as Batch completion unless all Batch acceptance items above are complete.

## Engineering Consistency

- [ ] Existing service, util, API client, component, or schema was reused where appropriate.
- [ ] Duplicate implementation was avoided.
- [ ] Module boundaries were preserved or the boundary change is explained.
- [ ] ADR need was considered for architecture, API style, DB model, auth, worker, deployment, or core dependency changes.
