# Development Verification Standard

This standard defines the default verification and GitNexus usage model for future ConsultantAIP development.

The goal is to keep safety evidence strong while avoiding repeated full-suite, full-E2E, and repeated GitNexus work on every small edit.

## Principles

- Codex is the default primary execution agent for implementation, verification, PR evidence, and CI follow-up.
- Verification depth must match change risk.
- Focused tests are the default during development.
- GitHub CI is the default broad validation gate for PRs.
- Full local regression and E2E runs are reserved for high-risk branches, release candidates, and production incidents.
- GitNexus is an impact-record and code-fact tool. It is not a real-time development navigator, not a correctness proof, and not a replacement for `rg`, tests, browser checks, or review.
- Antigravity and Claude are temporary specialists, not default participants on every PR.

## Risk Classification

Classify every task before choosing the workflow and verification depth.

| Risk | Examples | Default handling |
| --- | --- | --- |
| Low | Copy, styles, small helper, focused test assertion, explicit import fix, narrow bug with a traceback | Develop directly; GitNexus query is optional; run the smallest relevant check |
| Medium | Service bug, API client path, one page interaction, local data-read logic, route-level UI behavior | Use GitNexus if module ownership or reuse is unclear; run focused tests and typecheck; run `detect-changes` before PR |
| High | DB migration, auth, permissions, cross-module API, worker/queue behavior, shared type changes, deletes/moves/renames, architecture boundary changes | Use GitNexus before coding; write explicit risk and rollback notes; run focused plus necessary integration/build checks; include impact evidence |
| Release | Production deployment, deploy scripts, production config, release branch validation, incident hotfix rollout | Use release validation; verify health, OCI commit/status, GitNexus service health/index, and smoke paths as needed |

Automatically treat a task as High when it:

- changes database schema or Alembic migrations;
- changes auth, permissions, roles, sessions, or tokens;
- changes global API routing or shared API client behavior;
- changes workers, queues, retries, idempotency, or scheduled jobs;
- deletes, moves, or renames core files;
- changes shared types across multiple modules;
- changes production deployment configuration;
- touches more than 15 files;
- has GitNexus impact across multiple core call chains;
- has unclear module boundaries.

## Verification Levels

### Level 0: Development Loop

Run the smallest commands that prove the behavior being changed.

Use this level while coding:

- Backend service or router change: run the focused pytest file or test case.
- Frontend component or route change: run `pnpm --dir apps/web typecheck` and the focused Playwright spec when interaction behavior changed.
- API client path or payload change: add a focused request-path assertion or page-flow assertion.
- Documentation-only change: run `git diff --check`.

Do not run full backend tests, full deterministic E2E, or production build after every small edit.

### Level 1: PR-Ready Branch Check

Run before pushing or opening a PR:

```powershell
git diff --check
```

Plus the relevant focused checks from Level 0.

Add these only when they are relevant:

```powershell
pnpm --dir apps/web typecheck
pnpm --dir apps/web build
uv run --directory apps/api --extra dev python -m pytest <focused-path>
pnpm --dir apps/web exec playwright test <focused-spec>
```

Run `pnpm --dir apps/web build` when the branch changes Next.js routes, app layout, build-time imports, API client types used by pages, or package/dependency configuration.

Run local full API tests only when the branch changes shared backend contracts, security/auth, data models, migrations, worker/runtime behavior, or when focused tests do not isolate the risk.

Run full local deterministic E2E only when the branch changes cross-page workflow behavior, auth/navigation foundations, layout shells, or destructive user operations that are not sufficiently covered by focused E2E.

## Encoding And Console Output Policy

PowerShell console output on Windows can display valid UTF-8 Chinese text as mojibake. Do not classify a file, E2E fixture, or user-facing page as "garbled" only because `Get-Content`, `git diff`, `Select-String`, pytest output, or Playwright logs look wrong in the terminal.

Before any encoding repair or copy rewrite, run a strict source-level check and, for frontend text, a rendered UI check:

```powershell
$path = "apps/web/src/app/(app)/projects/[projectId]/documents/generate/page.tsx"
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)
$resolved = (Resolve-Path -LiteralPath $path).Path
$text = [System.IO.File]::ReadAllText($resolved, $utf8)
if ($text.Contains([char]0xfffd)) { throw "Replacement character found in $path" }
```

Use browser or focused Playwright assertions to verify user-visible text. If the strict UTF-8 read passes and the browser renders correct Chinese, record the issue as console display mojibake and do not edit the source.

Only perform an encoding or copy fix when at least one of these is true:

- strict UTF-8 decoding fails;
- the file contains replacement characters or known mojibake sequences in source bytes;
- the rendered browser UI or Playwright text assertion shows garbled user-visible text;
- an API response or exported artifact contains garbled text when read as UTF-8.

For suspected encoding issues, the PR or task evidence must state which layer failed: console display, source bytes, API payload, browser rendering, E2E fixture, or exported artifact. Console display alone is not a defect.

### Level 2: GitHub CI Gate

After PR creation, rely on GitHub Actions for the standard broad checks:

- `API tests`
- `Web typecheck and build`
- `Docker Compose config`
- `Collaboration governance`

Do not duplicate all CI checks locally unless local evidence is needed to debug a failure or the change is high-risk.

### Level 3: Merge And Release Gate

Run release-level verification only when merging a release branch or deploying production:

- GitHub Actions deploy workflow.
- Production health check.
- OCI git commit and status check.
- GitNexus service health and index refresh.
- Smoke E2E or route smoke only for the release-critical user paths.

Production deployment must still use the `Deploy production` GitHub Actions workflow.

## E2E Policy

Use focused Playwright specs for:

- user-visible cross-page workflows;
- destructive actions such as delete, archive, revoke, or remove;
- route/API integration that unit or type checks cannot prove;
- regressions that previously escaped narrower tests.

Do not run full deterministic E2E by default for:

- copy-only changes;
- isolated backend service fixes;
- simple API helper path fixes when covered by a request assertion;
- docs-only changes.

Full deterministic E2E is a branch or release gate, not an every-edit gate.

## GitNexus Usage Policy

Default lightweight pattern:

1. At task start, run:

   ```powershell
   gitnexus status
   ```

2. If stale and GitNexus facts will be used, refresh once:

   ```powershell
   gitnexus analyze --index-only
   ```

3. During implementation, prefer `rg`, direct file reads, and tests unless the code path is unfamiliar, cross-module, or incident-related.

4. Before PR, run one impact record:

   ```powershell
   powershell -ExecutionPolicy Bypass -File infra\scripts\invoke-gitnexus-change-record.ps1 `
     -RepoPath C:\amx\ConsultantAIP-main `
     -Scope compare `
     -BaseRef main
   ```

5. Record the output in the task card or PR.

Use `gitnexus query`, `context`, and `impact` only when they are likely to reduce uncertainty:

- task boundaries are unclear;
- the flow crosses frontend, API, services, workers, or data models;
- an incident or CI failure needs dependency tracing;
- reviewer needs page-to-API-to-service evidence;
- an agent is unfamiliar with the local implementation.

Avoid repeated GitNexus queries after every edit. Avoid re-running `analyze` after every amend unless final PR evidence must match the final commit.

If multiple worktrees are indexed, use `infra\scripts\invoke-gitnexus-change-record.ps1` instead of calling `gitnexus detect-changes` directly. The wrapper passes `--repo "<absolute-current-worktree-path>"`, records raw `git diff` changed files, records untracked files, compares GitNexus file coverage against Git file coverage, and prints an explicit fallback status so new or unmapped files are not mistaken for "no change" when GitNexus maps zero indexed symbols or only part of the branch.

Do not paste raw `gitnexus detect-changes` output as PR evidence when it says `No changes detected` but `git status`, `git diff`, or `git ls-files --others --exclude-standard` shows changed files. In that case record GitNexus as low-value symbol evidence and use the wrapper report plus focused verification.

If GitNexus FTS/query features are degraded or unavailable, record the limitation and use `rg`, file reads, focused tests, and browser checks as fallback evidence.

## PR Granularity

Prefer PRs that represent one independently reviewable and verifiable functional unit.

Recommended PRs:

- one user-visible workflow closure;
- one backend capability with schema/service/router/tests;
- one API client change with synchronized callers;
- one focused bug fix with a regression test;
- one documentation or governance update with coherent scope.

Avoid PRs that are too small to justify the process cost:

- one field;
- one trivial path;
- one copy tweak;
- one import;
- one isolated test assertion with no independent review value.

Also avoid PRs that bundle unrelated capabilities. A larger PR is acceptable only when the pieces form one business or technical unit and can be reviewed, tested, and rolled back together.

## Temporary Agent Escalation

Default to Codex-only execution. Bring in another agent only when it reduces total risk or total work.

Use Antigravity when:

- a task is large but mechanically repeatable;
- many similar frontend pages, tests, or rename operations must be generated;
- the work is non-critical and easy to verify from diffs and focused tests.

Use Claude when:

- Chinese business documentation or manuals need review;
- a user-facing workflow needs independent business acceptance;
- release notes or PR business-impact summaries need independent review;
- high-risk requirements need a second business judgment.

Temporary agents must not merge, deploy production, or bypass Codex PR evidence. Their output must be summarized in the task card, PR, or release note.

## Default PR Evidence

Every PR still needs:

- purpose;
- scope;
- risk level;
- focused verification commands and results;
- checks intentionally not run locally and why;
- risk and rollback;
- agent attribution;
- GitNexus status and one post-change impact record, or a clear fallback note.

For small docs-only PRs, the GitNexus record can be limited to `gitnexus status` plus a note that no code impact analysis was needed.
