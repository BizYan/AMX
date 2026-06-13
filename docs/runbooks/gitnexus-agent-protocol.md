# GitNexus Agent Protocol

This protocol defines when Codex, Antigravity, and Claude use GitNexus, what they must record, and how to avoid turning GitNexus into a development bottleneck. Codex is the default primary execution agent; Antigravity and Claude follow this protocol only when explicitly assigned.

GitNexus is a code-fact and impact-analysis layer. It is not a scheduler, test runner, reviewer, or production gate.

Follow `docs/runbooks/development-verification-standard.md` for the default lightweight GitNexus, risk classification, PR granularity, and verification policy.

## Freshness Gate

Before analysis:

```powershell
gitnexus status
```

If stale:

```powershell
gitnexus analyze --index-only
```

Reports must include indexed commit, current commit, and status.

## Core Commands

```powershell
gitnexus list
gitnexus status
gitnexus analyze --index-only
gitnexus query "<concept>" --goal "<goal>" --limit 10
gitnexus context "<symbol>" --file "<path>"
gitnexus impact "<symbol>" --direction upstream --depth 3 --include-tests
gitnexus detect-changes --scope compare --base-ref main --repo "<absolute-current-worktree-path>"
```

MCP clients may use equivalent GitNexus MCP tools. Record the tool name, query, result summary, and graph freshness.

Raw `gitnexus detect-changes` is diagnostic only. Do not use it as the sole PR impact record, because it can return `No changes detected` when the branch contains untracked files or files that are not represented by indexed symbols.

For PR evidence on Windows, prefer the repository wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File infra\scripts\invoke-gitnexus-change-record.ps1 `
  -RepoPath C:\amx\AMX-main `
  -Scope compare `
  -BaseRef main
```

The wrapper always passes `--repo` and records both raw `git diff` changed files, untracked files, and GitNexus symbol/process mapping. If GitNexus reports no changed symbols, or reports fewer changed files than Git lists, the wrapper prints `Fallback required: True`; treat GitNexus as a low-value or partial symbol record for that PR and use the changed-file list as fallback impact evidence.

## Cost-Control Rule

Do not run GitNexus query/context/impact as a reflex after every edit. Use them only when they reduce uncertainty:

- unfamiliar code area;
- unclear task boundary;
- frontend-to-API-to-service traceability review;
- shared backend, worker, data-model, or auth/security impact;
- CI, staging, production, or incident diagnosis.

For ordinary implementation, prefer `rg`, direct file reads, focused tests, and type/build checks. For PRs, one final wrapper-generated change record is normally sufficient.

## Health Check Helpers

Local Windows agents can generate a collaboration health report with:

```powershell
powershell -ExecutionPolicy Bypass -File infra\scripts\check-agent-collaboration.ps1 `
  -RepoPath C:\amx\AMX-main `
  -RefreshIfStale
```

OCI or Linux agents can generate the same class of report with:

```bash
REPO_PATH=/home/ubuntu/amx/production/AMX REPORTS_DIR=/home/ubuntu/amx/reports \
  REFRESH_IF_STALE=1 bash infra/scripts/check-agent-collaboration.sh
```

Attach or summarize this report for infrastructure, release, and incident tasks.

## Codex / Agent A

Use before:

- task decomposition;
- architecture decisions;
- technical review;
- CI/staging/production incident diagnosis;
- release and rollback planning.

For straightforward single-agent implementation work, Codex may use the lightweight pattern only: `gitnexus status` at start and `detect-changes` once before PR. Add `query`, `context`, or `impact` only if the code path is unclear or high-risk.

Record:

- affected routes;
- affected API endpoints;
- affected services, models, workers, migrations;
- reusable existing implementation;
- required regression tests;
- risk and rollback notes.

## Antigravity / Agent B

Before implementation, always check freshness:

```powershell
gitnexus status
```

Use query/context only when the task is unfamiliar, cross-module, or likely to duplicate existing implementation:

```powershell
gitnexus query "<task>" --goal "find reusable implementation and tests" --limit 10
```

Use after implementation:

```powershell
gitnexus analyze --index-only
gitnexus detect-changes --scope compare --base-ref main --repo "<absolute-current-worktree-path>"
```

Run `impact` only for changed high-risk symbols. Record post-change impact in the PR.

## Claude / Agent C

Before business acceptance, always check freshness:

```powershell
gitnexus status
```

Use query/context when the reviewer must prove page-to-API-to-service continuity or when screenshot evidence is insufficient:

```powershell
gitnexus query "<user flow>" --goal "trace frontend to API to service to data" --limit 10
gitnexus context "<entry symbol>"
```

Record:

- user entry route;
- frontend component path;
- API endpoint;
- service/model chain;
- persistence or worker side effects;
- business acceptance decision.

## Unavailable GitNexus

If unavailable:

```text
GitNexus unavailable
Reason:
Fallback commands:
Files inspected:
Why fallback is sufficient:
```

Fallback usually requires `rg`, targeted file reads, tests, and browser/E2E evidence. A fallback cannot be used to skip review.
