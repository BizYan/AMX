# Agent Collaboration Runbook

For the complete design-to-setup handbook, see `docs/runbooks/multi-agent-github-gitnexus-handbook.md`.

Default execution is now Codex single-agent ownership with GitNexus as the code-evidence layer and GitHub CI as the broad validation gate. Antigravity and Claude are temporary specialists, not standing participants on every branch.

## Local Workspace

Use `C:\amx` as the only multi-agent workspace root:

```text
C:\amx\AMX-main
C:\amx\AMX-codex
C:\amx\AMX-antigravity
C:\amx\AMX-claude
C:\amx\gitnexus-data
C:\amx\reports
```

Each agent works in a different checkout or worktree. Agents do not share a dirty tree.

## Role Split

- Codex: default primary engineering agent for task understanding, implementation, focused verification, PR evidence, CI follow-up, release coordination, and incidents.
- Antigravity: on-demand implementation and regression agent for large mechanical edits, batch frontend/test generation, repeated non-critical code changes, and well-scoped execution work.
- Claude: on-demand business acceptance, Chinese documentation, user manuals, product review, release notes, and independent acceptance for high-risk user-facing changes.

Do not assign every task to every agent. Add temporary agents only when their specialized work reduces total risk or total work. All delegated output must return to the task card, PR evidence, or release notes.

## Standard Flow

1. Human or Codex records the requirement in GitHub Issues or `tasks/`.
2. Codex classifies the task as Low, Medium, High, or Release using `docs/runbooks/development-verification-standard.md`.
3. Codex decides whether temporary Antigravity or Claude participation is useful.
4. Codex or the assigned temporary agent creates a branch from the current release train branch.
5. The working agent implements and runs the narrowest local verification that proves the change.
6. The working agent prepares PR evidence, including risk level, focused verification, intentional non-runs, rollback, and GitNexus evidence or fallback.
7. CI runs and remains the broad PR gate.
8. Human approves merge into release branch or `main`.
9. Production deploy runs only after human approval and release validation.

## Delegation Rules

Use Antigravity when the task can be delegated as a large, clear slice with self-testing requirements. Do not delegate tiny fragments where Codex review and validation cost would exceed implementation cost.

Use Claude when the task needs independent business/UX/documentation review. Claude must inspect code paths for acceptance-critical flows; screenshots alone are not enough.

Temporary agents must:

- work in separate worktrees or branches;
- run their own focused verification before handoff;
- record GitNexus freshness and post-change evidence when applicable;
- avoid merging, deploying production, or bypassing Codex review.

## GitNexus Usage

Agents query GitNexus for:

- code ownership facts;
- route and API contract maps;
- changed-file dependency edges;
- PR diff context;
- historical bug patterns.

Agents must still run tests and cite command output. GitNexus context is not test evidence.

Use the cost-control policy in `docs/runbooks/development-verification-standard.md`: `gitnexus status` at task start, focused `query/context/impact` only when it reduces uncertainty, and one final wrapper-generated change record before PR. Do not use GitNexus as a real-time development navigator for every edit.

### Mandatory Agent Protocol

#### Codex / Agent A

Use GitNexus when:

- translating a human requirement into tasks;
- deciding task boundaries and PR size;
- reviewing architecture, security, migrations, workers, and deployment risk;
- investigating CI, staging, production, or rollback failures.

Required outputs:

- affected frontend routes;
- affected API endpoints;
- affected services, models, workers, and migrations;
- existing reusable implementation;
- required regression commands;
- unresolved graph gaps.

Recommended commands:

```powershell
gitnexus status
gitnexus query "<feature or incident>" --goal "identify modules, APIs, services, data, tests" --limit 10
gitnexus impact "<symbol>" --direction upstream --depth 3 --include-tests
powershell -ExecutionPolicy Bypass -File infra\scripts\invoke-gitnexus-change-record.ps1 -RepoPath "<absolute-current-worktree-path>" -Scope compare -BaseRef main
```

#### Antigravity / Agent B

Use Antigravity only when explicitly assigned. Use GitNexus when:

- starting implementation;
- checking whether a service, component, hook, API client, schema, or test already exists;
- validating the blast radius after modifying code;
- preparing a PR report.

Required outputs:

- `GitNexus freshness record`;
- `GitNexus post-change impact record`;
- exact tests selected because of the graph result;
- any fallback `rg` commands if GitNexus was stale or unavailable.

Recommended commands:

```powershell
gitnexus status
gitnexus query "<task>" --goal "find reusable implementation and tests" --limit 10
gitnexus context "<symbol>" --file "<path>"
powershell -ExecutionPolicy Bypass -File infra\scripts\invoke-gitnexus-change-record.ps1 -RepoPath "<absolute-current-worktree-path>" -Scope compare -BaseRef main
gitnexus impact "<changed-symbol>" --direction upstream --depth 3 --include-tests
```

`query`, `context`, and `impact` are conditional tools, not mandatory commands for every branch. The assigned agent must still self-test and review its own output before handoff.

#### Claude / Agent C

Use Claude only when explicitly assigned. Use GitNexus when:

- reviewing a PR for business acceptance;
- checking whether a visible user flow reaches a real API/service/data path;
- validating Chinese copy and UX changes against actual routes and components;
- producing manuals or acceptance reports from code facts.

Required outputs:

- user entry route;
- primary frontend components;
- API endpoint chain;
- backend service/model chain;
- persistence or worker side effects;
- acceptance decision: `PASSED`, `BLOCKED`, or `PASSED_WITH_FOLLOW_UPS`.

Recommended commands:

```powershell
gitnexus status
gitnexus query "<user flow>" --goal "trace frontend to API to service to data" --limit 10
gitnexus context "<route or component symbol>"
gitnexus impact "<business-critical symbol>" --direction upstream --depth 3 --include-tests
```

### Freshness Rule

Every report must include:

```text
GitNexus repository:
Indexed commit:
Current commit:
Status:
Commands or MCP tools used:
```

If `gitnexus status` is not `up-to-date`, refresh with `gitnexus analyze --index-only` before making architectural or review claims.
