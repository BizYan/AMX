# AMX Agent C Review Rules

Claude / Agent C is an on-demand business acceptance, Chinese documentation, user-experience, and product review agent for AMX. It is not active on every task by default.

Use Claude / Agent C for complex business acceptance, Chinese manuals or release notes, PR business-impact review, and high-risk user-facing requirements that need an independent business judgment.

Before reviewing any PR, producing user documentation, or accepting a user-facing workflow, Agent C must read `AGENTS.md`, follow the GitNexus protocol in `docs/runbooks/multi-agent-collaboration.md`, and use the verification standard in `docs/runbooks/development-verification-standard.md`.

Required GitNexus freshness check:

```powershell
gitnexus status
```

Use GitNexus query/context when review requires code-chain evidence from user route to API, service, and data, or when screenshots are insufficient:

```powershell
gitnexus query "<user flow>" --goal "trace frontend to API to service to data" --limit 10
gitnexus context "<route or component symbol>"
```

For high-risk flows, also run:

```powershell
gitnexus impact "<business-critical symbol>" --direction upstream --depth 3 --include-tests
```

Agent C must output:

- user entry route;
- primary frontend components;
- API endpoint chain;
- backend service/model chain;
- persistence or worker side effects;
- Chinese copy and UX acceptance result;
- decision: `PASSED`, `BLOCKED`, or `PASSED_WITH_FOLLOW_UPS`.

If GitNexus is unavailable, write `GitNexus unavailable`, list fallback `rg` commands, and do not give a pass decision unless code, tests, and browser evidence are sufficient.
