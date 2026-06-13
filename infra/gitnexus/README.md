# GitNexus Foundation

GitNexus is the AMX code-fact and context-compression service. It is not a scheduler and it does not replace CI. It gives Codex, Antigravity, Claude, and the AMX backend a consistent view of repository structure, dependency edges, PR diffs, and code ownership facts.

This integration uses the official GitNexus surfaces:

- `ghcr.io/abhigyanpatwari/gitnexus`: CLI/server backend, HTTP API, MCP, and indexer on port `4747`.
- `ghcr.io/abhigyanpatwari/gitnexus-web`: static Web UI on port `4173`.
- `gitnexus analyze --index-only`: repository graph indexing without rewriting project context files.
- `gitnexus mcp`: agent-facing MCP server.

Production deployment pins the official server and Web images to `1.6.5`. Do not
switch these defaults back to `latest`: the upstream `latest` server image published
on June 9, 2026 is missing a CLI runtime module and cannot refresh the repository
index. Upgrade the pin only after an OCI-compatible analyze smoke test passes.

Governance note: the public OSS project is published under PolyForm Noncommercial. Confirm commercial or enterprise authorization before using it as internal company tooling.

## Deployment Layout

Recommended OCI paths:

```text
/home/ubuntu/amx/gitnexus/
  docker-compose.yml
  .env
```

GitNexus should bind to `127.0.0.1` or a private network by default. Do not expose it publicly unless it has authentication, rate limits, and Cloudflare Access in front of it.

The server container runs as root by default because the official image writes both to `/data/gitnexus` and to the indexed repository's `.gitnexus/` directory. The mounted repository is a dedicated clean GitNexus clone under `/home/ubuntu/amx/gitnexus/workspace`, not the production runtime checkout, and it must not contain `.env` or production secrets.

The AMX API container must call GitNexus through the shared Docker network, not through host loopback. The host-facing URL remains `http://127.0.0.1:4747` for SSH health checks, while the provider-facing URL is `http://gitnexus-server:4747` after both compose stacks are on `AMX_RUNTIME_NETWORK`.

## Install

```bash
cd /home/ubuntu/amx/production/AMX
bash infra/deploy/deploy-gitnexus.sh
```

The deploy script copies the official GitNexus Compose file to `/home/ubuntu/amx/gitnexus`, migrates an existing legacy workspace clone to the Public AMX origin, starts the server and Web UI, checks both health endpoints, and refreshes the graph for `/workspace/AMX`.

## Refresh Main Graph

After every successful deployment to `main`:

```bash
cd /home/ubuntu/amx/production/AMX
bash infra/deploy/refresh-gitnexus.sh
```

The production GitHub Actions deployment calls this automatically after the AMX health check passes.

## Local Agent MCP Setup

On Windows, run:

```powershell
powershell -ExecutionPolicy Bypass -File infra\scripts\setup-gitnexus-mcp.ps1 -RepoPath C:\amx\AMX-main
```

This installs `gitnexus@latest`, indexes the repository, and adds the GitNexus MCP server to `%USERPROFILE%\.codex\config.toml`.

For Antigravity, Claude Code, Cursor, or other tools, use the upstream MCP command:

```bash
npx -y gitnexus@latest mcp
```

All agents must record the exact GitNexus query or MCP tool result used in their task report. If the index is stale or unavailable, the agent must state that explicitly and fall back to `rg` plus tests.

If a local index stays stale after an incremental refresh, run `analyze` with the repository path as the positional argument:

```powershell
gitnexus analyze "C:\amx\AMX-main" --index-only
```

## AMX Provider Registration

After GitNexus is healthy, register it in AMX as a provider with:

```powershell
powershell -ExecutionPolicy Bypass -File infra\scripts\seed-gitnexus-provider.ps1 `
  -BaseUrl https://amx.yuanda.win/api/v1 `
  -Email admin@example.com `
  -Password '<password>' `
  -GitNexusUrl http://gitnexus-server:4747 `
  -GitNexusApiKey '<service-key>' `
  -RepositoryFullName BizYan/AMX
```

The helper stores the connection under provider `config`, using keys consumed by the AMX backend runtime: `endpoint`, `base_url`, `service_key`, `health_path`, `repository`, and `refresh_policy`. It does not put credentials in unsupported top-level fields, and it masks credential values in its console output. Never commit the real key to Git.

Run a live health smoke test during registration only after the AMX API container can resolve `gitnexus-server` on the shared Docker network:

```powershell
powershell -ExecutionPolicy Bypass -File infra\scripts\seed-gitnexus-provider.ps1 `
  -BaseUrl https://amx.yuanda.win/api/v1 `
  -Email admin@example.com `
  -Password '<password>' `
  -GitNexusUrl http://gitnexus-server:4747 `
  -GitNexusApiKey '<service-key>' `
  -RepositoryFullName BizYan/AMX `
  -RunConnectionTest
```

## Operating Policy

- Refresh main graph after every merge to `main`.
- Refresh PR graph after every opened or synchronized PR.
- Use the CLI/MCP graph as the primary agent query interface; use the Web UI for human review and demos.
- Agents may query GitNexus for context; they may not use it as proof that tests passed.
- GitHub Actions remains the merge gate.
