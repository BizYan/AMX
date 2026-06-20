# Live Jira Connector Candidate Verification

Scope: controlled candidate verification for the existing `jira_project_sync_v1`
connector only. This runbook does not productionize another connector and does
not authorize production Jira or customer data access.

## Required Candidate Inputs

The AMX candidate or staging runtime must have these candidate-only values:

- `AMX_CANDIDATE_JIRA_API_TOKEN`
- `AMX_CANDIDATE_JIRA_BASE_URL`
- `AMX_CANDIDATE_JIRA_PROJECT_KEY`

The verification operator also needs the normal authenticated AMX runtime inputs:

- `BOOTSTRAP_ADMIN_EMAIL`
- `BOOTSTRAP_ADMIN_PASSWORD`
- AMX candidate or staging `BASE_URL`

Do not print, paste, persist, or commit the raw Jira token. The AMX integration
configuration must use only `credential_ref`:

```json
{
  "provider_type": "jira",
  "name": "Candidate Live Jira",
  "config_json": {
    "base_url": "https://candidate-jira.example",
    "credential_ref": "env:AMX_CANDIDATE_JIRA_API_TOKEN",
    "sync_path": "/rest/api/2/search",
    "connector_profile": "jira_project_sync_v1",
    "page_size": 1,
    "max_pages": 2,
    "retry_attempts": 1
  }
}
```

## Command

Run only against candidate or staging:

```bash
bash infra/deploy/live-jira-connector-verification.sh \
  --base-url "$BASE_URL" \
  --env-file "$ENV_FILE"
```

Use `--keep-evidence` only when the owner wants to retain the disposable AMX
project and integration records for review. Without it, the script archives the
AMX project and soft-deletes the integration after verification.

## Verified Flow

The script verifies one complete live Jira connector path:

1. Logs in through `/api/v1/identity/auth/login`.
2. Creates one disposable AMX project.
3. Creates one Jira provider with `credential_ref=env:AMX_CANDIDATE_JIRA_API_TOKEN`.
4. Binds that provider to the disposable AMX project with `jira_project_sync_v1`.
5. Runs preview before sync.
6. Verifies preview returns synthetic Jira issues and does not create sync runs.
7. Executes sync.
8. Verifies bounded pagination evidence:
   - `mode=jira_paginated_fetch`
   - `page_size`
   - `max_pages`
   - `pages_fetched`
   - `items_fetched`
   - `bounded=true`
9. Verifies persisted sync evidence through the sync run counts and operations summary.
10. Runs retry through `/api/v1/integrations/sync-runs/{run_id}/retry`.
11. Verifies outbox evidence includes `integration.project_sync.completed`.
12. Verifies failure states:
   - `missing_credential`
   - `expired_credential`
   - `remote_error`

The invalid-token path is produced without storing a raw bad token by using the
same `credential_ref` with an intentionally invalid auth scheme, causing Jira to
reject the request and AMX to record `expired_credential`.

## Audit Evidence

Repository tests verify that sync start, completion, and failure create
`IntegrationInboundEvent` audit records and `OutboxEvent` evidence. The live
script verifies the externally exposed evidence path: sync run details,
operations summary, and outbox events.

If owner review requires direct `IntegrationInboundEvent` evidence in a live
candidate database, collect it through a controlled read-only DB query in the
candidate environment. The evidence must include event type, binding ID, sync
run ID, connector profile, and failure state where applicable. It must not
include raw token values, customer content, or production data.

## Evidence To Record

Record only sanitized values:

- exact AMX git SHA under verification;
- candidate runtime URL label, not secrets;
- AMX project ID;
- integration provider ID;
- project binding ID;
- successful sync run ID;
- preview total;
- `fetch_evidence`;
- retry run status;
- outbox event ID and `integration.project_sync.completed`;
- failure-state run IDs for `missing_credential`, `expired_credential`, and
  `remote_error`;
- cleanup result.

## Pass / Fail Criteria

Pass only if:

- raw Jira token is absent from API responses, logs, artifacts, PR text, and
  runbook evidence;
- provider config persists only `credential_ref`;
- preview precedes sync and does not create sync runs;
- sync completes with at least one persisted synthetic Jira item;
- pagination is bounded;
- retry creates a completed run;
- outbox includes `integration.project_sync.completed`;
- required failure states are recorded;
- teardown archives or retains candidate records according to owner instruction.

Fail closed if any required candidate input is missing, if login fails, if Jira
returns no synthetic candidate issues, if AMX records raw credentials, or if
candidate/staging cannot prove the outbox and failure-state evidence.
