# AMX Antigravity / Gemini Development Rules

Antigravity / Gemini is an on-demand implementation and regression execution agent for AMX. It is not active on every task by default.

Use Antigravity / Gemini for large mechanical edits, batch frontend or test generation, repeated non-critical code changes, and well-scoped implementation slices where it can self-test before handoff. Do not use it for tiny fragments where Codex review and validation would cost more than the implementation.

Before coding, read `AGENTS.md`, the active task card, the GitNexus protocol in `docs/runbooks/multi-agent-collaboration.md`, and the verification standard in `docs/runbooks/development-verification-standard.md`.

Before handoff, run the focused verification required by the task and summarize what was not run locally and why. Do not hand off code that has not been self-reviewed.

Required GitNexus freshness check before implementation:

```powershell
gitnexus status
```

Use GitNexus search only when it will reduce uncertainty, such as unfamiliar code, cross-module work, or reusable implementation discovery:

```powershell
gitnexus query "<task>" --goal "find reusable implementation, API contracts, components, hooks, schemas, and tests" --limit 10
gitnexus context "<main symbol or route>" --file "<path when needed>"
```

Required GitNexus steps before PR handoff:

```powershell
gitnexus status
powershell -ExecutionPolicy Bypass -File infra\scripts\invoke-gitnexus-change-record.ps1 -RepoPath "<absolute-current-worktree-path>" -Scope compare -BaseRef main
```

Run `gitnexus impact` only for changed high-risk symbols.

Every PR report must include:

- GitNexus freshness: indexed commit, current commit, and status;
- coding-before search record if query/context was used;
- post-change impact record;
- tests selected because of the graph result, or focused verification selected by code changes;
- fallback `rg` commands if GitNexus was unavailable.

Do not use GitNexus as proof of correctness. Code, typecheck, build, tests, browser/E2E evidence, and review are still required.
