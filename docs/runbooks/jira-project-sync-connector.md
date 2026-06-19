# Jira Project Sync Connector Runbook

Scope: one productionized external connector path, `jira_project_sync_v1`.

## Credential Boundary

Jira connector provider config must not persist raw credentials. Do not store:

- `api_key`
- `api_token`
- `access_token`
- `token`
- `secret`
- `service_key`
- `password`

Use only:

```json
{
  "provider_type": "jira",
  "name": "Delivery Jira",
  "config_json": {
    "base_url": "https://<jira-host>",
    "credential_ref": "env:AMX_CANDIDATE_JIRA_API_TOKEN",
    "sync_path": "/rest/api/2/search",
    "connector_profile": "jira_project_sync_v1",
    "page_size": 50,
    "max_pages": 3,
    "retry_attempts": 1
  }
}
```

The runtime resolves `credential_ref` only when making the outbound request. The resolved token must not be written back to provider config, API responses, sync run details, audit events, outbox payloads, or PR evidence.

## Binding Contract

Create one project binding with:

```json
{
  "name": "Jira requirements",
  "scope": {
    "connector_profile": "jira_project_sync_v1",
    "external_scope": "project = AMX",
    "item_path": "issues",
    "page_size": 50,
    "max_pages": 3,
    "require_preview_before_sync": true
  },
  "field_mapping": {
    "external_id": "key",
    "title": "fields.summary",
    "content": "fields.description",
    "updated_at": "fields.updated",
    "external_url": "self"
  }
}
```

Preview must be executed before sync. Sync without preview fails closed with `failure_state=preview_required`.

## Candidate Verification

Required runtime input:

- `AMX_CANDIDATE_JIRA_API_TOKEN`: Jira candidate-only API token with read-only issue search permission for the scoped test project.
- Synthetic Jira project or fixture project containing non-customer test issues only.
- AMX candidate/staging tenant and disposable project.

Verification command shape:

```bash
export AMX_CANDIDATE_JIRA_API_TOKEN="<owner-provided-candidate-token>"
bash infra/deploy/authenticated-smoke.sh --base-url "$BASE_URL" --env-file "$ENV_FILE"
```

Then use the authenticated API session to:

1. Create Jira integration with `credential_ref=env:AMX_CANDIDATE_JIRA_API_TOKEN`.
2. Create project binding with `connector_profile=jira_project_sync_v1`.
3. Run preview and confirm it returns only synthetic Jira issues.
4. Run sync and verify:
   - `IntegrationSyncRun.status=completed`;
   - `fetch_evidence.mode=jira_paginated_fetch`;
   - bounded pagination evidence: `page_size`, `max_pages`, `pages_fetched`, `items_fetched`;
   - created or updated `IntegrationSyncedAsset`;
   - source file and knowledge entry linkage;
   - provenance and lineage records;
   - audit events `integration.project_sync.started` and `integration.project_sync.completed`;
   - outbox event `integration.project_sync.completed`.

## Failure Evidence

The connector must fail closed with clear states:

- missing runtime secret: `failure_state=missing_credential`;
- expired or rejected credential: `failure_state=expired_credential`;
- HTTP 429: `failure_state=rate_limited`;
- HTTP 5xx or malformed remote response: `failure_state=remote_error`.

## Current Proof Boundary

Repository tests use a fake remote Jira adapter to prove credential boundary, preview gate, bounded pagination, transient retry, sync persistence, audit events, outbox evidence, and failure classification.

Live Jira candidate verification remains pending until the owner provides `AMX_CANDIDATE_JIRA_API_TOKEN` in a candidate or staging runtime. Do not use production customer Jira data for this proof.
