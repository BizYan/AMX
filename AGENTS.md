# AMX Multi-Agent Engineering Rules

This repository follows `docs/architecture.md`, `docs/product-spec.md`, the on-demand agent collaboration model from `docs/runbooks/multi-agent-collaboration.md`, and the verification/GitNexus cost-control standard in `docs/runbooks/development-verification-standard.md`.

## Authority Model

The human owner keeps final authority for product scope, merges to protected branches, releases, and production deployment.

Agents may create branches, commits, tests, reports, and pull requests. Agents must not directly merge `main`, publish production, rewrite protected history, or bypass CI and review gates.

## Required Workspaces

Use `C:\amx` as the only local multi-agent workspace root.

```text
C:\amx\ConsultantAIP-main        main branch and release authority workspace
C:\amx\ConsultantAIP-codex       Codex architecture, integration, review, release engineering
C:\amx\ConsultantAIP-antigravity Antigravity implementation and regression work
C:\amx\ConsultantAIP-claude      Claude business review, documentation, and acceptance
C:\amx\gitnexus-data             GitNexus persistent data
C:\amx\reports                   shared reports and patch handoff artifacts
```

Do not let two agents edit the same worktree. Each task must use a dedicated branch.

## Role Split

Codex is the default primary engineering agent. It owns end-to-end task understanding, implementation, focused verification, PR evidence, CI follow-up, technical review, release coordination, OCI operations, and incident coordination unless a task is explicitly delegated.

Antigravity is an on-demand implementation and regression execution agent. Use it for large mechanical edits, batch frontend/test generation, repeated non-critical code changes, and other well-scoped implementation work. It works on feature branches, writes code and tests, runs local verification, and opens pull requests. It must not self-merge.

Claude is an on-demand business acceptance, Chinese documentation, user-experience, and product review agent. Use it for complex business review, Chinese manuals, release notes, PR business-impact review, and high-risk independent acceptance. It must not approve unverified behavior based only on screenshots or intent.

Default rule: do not keep Antigravity or Claude active on every task. Add them only when their output will reduce risk or total work, and bring their findings back into the task card, PR evidence, or release notes.

## Standard Task Flow

1. Record the requirement in GitHub Issues or `tasks/inbox.md`.
2. Codex classifies risk as Low, Medium, High, or Release and decides whether any temporary agent is useful.
3. Codex or the assigned agent creates a branch from the current release train branch.
4. The working agent checks GitNexus freshness, then uses GitNexus query/context only when it is likely to reduce uncertainty.
5. The working agent implements the task and runs local verification at the narrowest level that proves the change.
6. The working agent prepares PR evidence, including local focused verification, risk/rollback, and a GitNexus impact record or fallback note.
7. The working agent pushes a branch and opens a PR using `.github/pull_request_template.md`.
8. Claude performs business and UX acceptance only when the change needs independent business review or documentation acceptance.
9. GitHub Actions must pass.
10. The human owner decides whether to merge and deploy.

## GitNexus Rules

GitNexus is the shared code-fact and impact-record layer. It does not replace tests, code review, browser verification, `rg`, or human release authority.

All agents must use the same GitNexus index for the repository they are working in. Before relying on graph facts, run:

```powershell
gitnexus status
```

If the index is stale, refresh it before analysis:

```powershell
gitnexus analyze --index-only
```

Default lightweight GitNexus checkpoints:

- Task start: run `gitnexus status`; refresh once with `gitnexus analyze --index-only` only if stale and GitNexus facts will be used.
- Implementation loop: prefer `rg`, direct file reads, focused tests, and browser checks. Use `gitnexus query`, `context`, or `impact` only for unfamiliar, cross-module, incident, or review-traceability work.
- PR preparation: run one post-change impact record with `infra\scripts\invoke-gitnexus-change-record.ps1`; it passes the exact repo path and records raw `git diff` changed files plus GitNexus symbol mapping.
- Review or incident escalation: use `gitnexus query` and `impact` when dependency tracing can reduce uncertainty.

Do not use raw `gitnexus detect-changes` output as the sole PR evidence in local multi-worktree development. The CLI can report `No changes detected` for untracked files or files outside the indexed symbol graph; the wrapper is the authoritative project command because it records Git file evidence and marks GitNexus low-value results explicitly.

Minimum useful command set:

```powershell
gitnexus list
gitnexus status
gitnexus analyze --index-only
gitnexus query "project invitation flow" --goal "find frontend, API, service, models, and tests" --limit 8
gitnexus context create_project --file apps/api/app/domains/projects/service.py
gitnexus impact ProjectService --direction upstream --depth 3 --include-tests
powershell -ExecutionPolicy Bypass -File infra\scripts\invoke-gitnexus-change-record.ps1 -RepoPath C:\amx\ConsultantAIP-main -Scope compare -BaseRef main
```

When an MCP client is available, agents may use the GitNexus MCP tools instead of CLI commands, but the task or PR report must still record the tool name, query, graph freshness, and summarized result.

If GitNexus is unavailable, the agent must explicitly write `GitNexus unavailable` in the task or PR report and use repository search plus tests as fallback evidence.

GitNexus output must be recorded in `docs/runbooks/gitnexus-query-record.md` format or in the equivalent PR section. Vague statements such as "checked GitNexus" are not acceptable.

## Verification Rules

Use `docs/runbooks/development-verification-standard.md` as the source of truth. Run the narrowest command set that proves the task during development, then let GitHub CI provide the standard broad PR gate. Full local API suites and full deterministic E2E are not default per-edit checks.

Do not treat PowerShell console mojibake as source-code mojibake. Before proposing or applying any encoding fix, verify the file with strict UTF-8 decoding and, for user-visible frontend text, verify the rendered browser or Playwright text. Only change encoding or rewrite copy when the strict read, source inspection, or rendered UI proves the bytes or user-visible output are wrong.

Common commands:

```powershell
pnpm --dir apps/web typecheck
pnpm --dir apps/web build
uv run --directory apps/api pytest
docker compose -f infra/docker-compose.yml config
```

For frontend interaction changes, run Playwright or browser verification and include the route list, failures, and screenshots if relevant.

For database or migration changes, verify Alembic upgrade on a disposable database before production deployment.

Production release verification is a separate gate: deploy through GitHub Actions, verify production health, OCI commit/status, GitNexus service health, and release-critical smoke paths.

Do not deploy every merge by default. Multiple stable PRs may be grouped into a release slice and validated together, unless the change is a production hotfix or the human owner requests immediate deployment.

## Branch And Commit Rules

Branch names:

```text
feature/<release-or-task-name>
fix/<issue-or-bug-name>
agent/<agent-purpose>
review/<pr-or-task-name>
infra/<infrastructure-task>
docs/<documentation-task>
```

Commits must be focused and explain the outcome. Do not mix unrelated refactors, formatting churn, and feature work.

Default PR size should be one reviewable and independently verifiable functional unit. Avoid one-field, one-import, one-copy, or one-test-assertion PRs unless the change is a clear hotfix. Avoid bundling unrelated capabilities merely to reduce PR count.

## Prohibited Actions

- Do not commit secrets, tokens, private keys, `.env` files, browser profiles, or generated credentials.
- Do not use `git reset --hard`, destructive checkout, or force-push without explicit human approval.
- Do not delete legacy workspaces without archiving or confirming that unique docs and patches were migrated.
- Do not lower test standards to make a PR pass.
- Do not ship buttons or links with no visible feedback.
- Do not claim production readiness without command evidence and smoke-test evidence.
