#!/usr/bin/env bash
set -euo pipefail

BASE_URL="http://localhost:18000"
ENV_FILE=".env"
CURL_BIN="${CURL_BIN:-curl}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
KEEP_EVIDENCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      BASE_URL="${2%/}"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --keep-evidence)
      KEEP_EVIDENCE=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[live-jira] environment file not found: $ENV_FILE" >&2
  exit 1
fi

read_env_value() {
  local key="$1"
  "$PYTHON_BIN" - "$ENV_FILE" "$key" <<'PY'
from pathlib import Path
import os
import sys

path, key = sys.argv[1:]
if os.environ.get(key):
    print(os.environ[key])
    raise SystemExit
for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    name, value = line.split("=", 1)
    if name.strip() == key:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        print(value)
        break
PY
}

json_get() {
  local path="$1"
  "$PYTHON_BIN" - "$path" <<'PY'
import json
import sys

path = sys.argv[1]
data = json.load(sys.stdin)
value = data
for part in path.split("."):
    if not part:
        continue
    if isinstance(value, list):
        value = value[int(part)]
    elif isinstance(value, dict):
        value = value.get(part)
    else:
        value = None
if isinstance(value, (dict, list)):
    print(json.dumps(value, separators=(",", ":"), sort_keys=True))
elif value is None:
    print("")
else:
    print(value)
PY
}

json_len() {
  "$PYTHON_BIN" - <<'PY'
import json
import sys

value = json.load(sys.stdin)
print(len(value))
PY
}

assert_no_token() {
  local payload="$1"
  PAYLOAD="$payload" "$PYTHON_BIN" - "$JIRA_TOKEN" <<'PY'
import os
import sys

token = sys.argv[1]
payload = os.environ.get("PAYLOAD", "")
if token and token in payload:
    print("[live-jira] raw Jira token appeared in API evidence", file=sys.stderr)
    raise SystemExit(1)
PY
}

require_value() {
  local name="$1"
  local value="$2"
  if [[ -z "$value" ]]; then
    echo "[live-jira] $name is required" >&2
    exit 1
  fi
}

BOOTSTRAP_ADMIN_EMAIL="$(read_env_value BOOTSTRAP_ADMIN_EMAIL)"
BOOTSTRAP_ADMIN_PASSWORD="$(read_env_value BOOTSTRAP_ADMIN_PASSWORD)"
if [[ -z "$BOOTSTRAP_ADMIN_EMAIL" || -z "$BOOTSTRAP_ADMIN_PASSWORD" ]]; then
  echo "[live-jira] BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD are required" >&2
  exit 1
fi

JIRA_TOKEN="$(read_env_value AMX_CANDIDATE_JIRA_API_TOKEN)"
JIRA_BASE_URL="$(read_env_value AMX_CANDIDATE_JIRA_BASE_URL)"
JIRA_PROJECT_KEY="$(read_env_value AMX_CANDIDATE_JIRA_PROJECT_KEY)"
require_value "AMX_CANDIDATE_JIRA_API_TOKEN" "$JIRA_TOKEN"
require_value "AMX_CANDIDATE_JIRA_BASE_URL" "$JIRA_BASE_URL"
require_value "AMX_CANDIDATE_JIRA_PROJECT_KEY" "$JIRA_PROJECT_KEY"
echo "::add-mask::$JIRA_TOKEN" 2>/dev/null || true

login_payload="$(
  BOOTSTRAP_ADMIN_EMAIL="$BOOTSTRAP_ADMIN_EMAIL" BOOTSTRAP_ADMIN_PASSWORD="$BOOTSTRAP_ADMIN_PASSWORD" \
    "$PYTHON_BIN" -c 'import json,os; print(json.dumps({"email": os.environ["BOOTSTRAP_ADMIN_EMAIL"], "password": os.environ["BOOTSTRAP_ADMIN_PASSWORD"]}))'
)"
login_response="$(
  "$CURL_BIN" -fsS \
    -H "Content-Type: application/json" \
    -d "$login_payload" \
    "$BASE_URL/api/v1/identity/auth/login"
)"
ACCESS_TOKEN="$(json_get access_token <<<"$login_response")"
if [[ -z "$ACCESS_TOKEN" ]]; then
  echo "[live-jira] login did not return an access token" >&2
  exit 1
fi

api_get() {
  "$CURL_BIN" -fsS -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL$1"
}

api_post() {
  local path="$1"
  local payload="$2"
  "$CURL_BIN" -fsS \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    "$BASE_URL$path"
}

api_patch() {
  local path="$1"
  local payload="$2"
  "$CURL_BIN" -fsS \
    -X PATCH \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    "$BASE_URL$path"
}

api_delete() {
  local path="$1"
  "$CURL_BIN" -fsS -X DELETE -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL$path" >/dev/null || true
}

unique_suffix="$("$PYTHON_BIN" -c 'import uuid; print(uuid.uuid4().hex[:10])')"
project_payload="$(
  UNIQUE_SUFFIX="$unique_suffix" "$PYTHON_BIN" - <<'PY'
import json
import os

suffix = os.environ["UNIQUE_SUFFIX"]
print(json.dumps({
    "name": f"Live Jira Candidate {suffix}",
    "slug": f"live-jira-candidate-{suffix}",
    "description": "Disposable synthetic Jira connector candidate verification project.",
    "status": "active",
}))
PY
)"
project_response="$(api_post "/api/v1/projects" "$project_payload")"
PROJECT_ID="$(json_get id <<<"$project_response")"
require_value "created AMX project id" "$PROJECT_ID"

cleanup() {
  if [[ "$KEEP_EVIDENCE" != "1" ]]; then
    if [[ -n "${INTEGRATION_ID:-}" ]]; then
      api_delete "/api/v1/integrations/$INTEGRATION_ID"
    fi
    if [[ -n "${PROJECT_ID:-}" ]]; then
      api_patch "/api/v1/projects/$PROJECT_ID" '{"status":"archived"}' >/dev/null || true
    fi
  fi
}
trap cleanup EXIT

operations_before="$(api_get "/api/v1/integrations/operations/summary")"
synced_assets_before="$(json_get evidence.synced_asset_count <<<"$operations_before")"
synced_assets_before="${synced_assets_before:-0}"

integration_payload="$(
  JIRA_BASE_URL="$JIRA_BASE_URL" "$PYTHON_BIN" - <<'PY'
import json
import os

print(json.dumps({
    "provider_type": "jira",
    "name": "Candidate Live Jira",
    "config_json": {
        "base_url": os.environ["JIRA_BASE_URL"],
        "credential_ref": "env:AMX_CANDIDATE_JIRA_API_TOKEN",
        "sync_path": "/rest/api/2/search",
        "connector_profile": "jira_project_sync_v1",
        "page_size": 1,
        "max_pages": 2,
        "retry_attempts": 1,
    },
}))
PY
)"
integration_response="$(api_post "/api/v1/integrations" "$integration_payload")"
assert_no_token "$integration_response"
INTEGRATION_ID="$(json_get id <<<"$integration_response")"
require_value "created Jira integration id" "$INTEGRATION_ID"

binding_payload="$(
  PROJECT_ID="$PROJECT_ID" JIRA_PROJECT_KEY="$JIRA_PROJECT_KEY" "$PYTHON_BIN" - <<'PY'
import json
import os

project_key = os.environ["JIRA_PROJECT_KEY"]
print(json.dumps({
    "project_id": os.environ["PROJECT_ID"],
    "name": "Candidate Jira requirements",
    "scope": {
        "connector_profile": "jira_project_sync_v1",
        "external_scope": f"project = {project_key}",
        "item_path": "issues",
        "page_size": 1,
        "max_pages": 2,
        "require_preview_before_sync": True,
    },
    "field_mapping": {
        "external_id": "key",
        "title": "fields.summary",
        "content": "fields.description",
        "updated_at": "fields.updated",
        "external_url": "self",
    },
    "is_enabled": True,
}))
PY
)"
binding_response="$(api_post "/api/v1/integrations/$INTEGRATION_ID/project-bindings" "$binding_payload")"
BINDING_ID="$(json_get id <<<"$binding_response")"
require_value "created Jira binding id" "$BINDING_ID"

preview_response="$(api_post "/api/v1/integrations/project-bindings/$BINDING_ID/preview?limit=10" "{}")"
assert_no_token "$preview_response"
preview_total="$(json_get total <<<"$preview_response")"
if [[ "${preview_total:-0}" -lt 1 ]]; then
  echo "[live-jira] Jira preview returned no synthetic candidate issues" >&2
  exit 1
fi

runs_after_preview="$(api_get "/api/v1/integrations/project-bindings/$BINDING_ID/runs")"
if [[ "$(json_len <<<"$runs_after_preview")" != "0" ]]; then
  echo "[live-jira] preview unexpectedly created sync runs" >&2
  exit 1
fi

sync_response="$(api_post "/api/v1/integrations/project-bindings/$BINDING_ID/sync" "{}")"
assert_no_token "$sync_response"
run_status="$(json_get status <<<"$sync_response")"
if [[ "$run_status" != "completed" ]]; then
  echo "[live-jira] sync did not complete: status=$run_status failure_state=$(json_get details_json.failure_state <<<"$sync_response")" >&2
  exit 1
fi
RUN_ID="$(json_get id <<<"$sync_response")"
created_count="$(json_get created_count <<<"$sync_response")"
updated_count="$(json_get updated_count <<<"$sync_response")"
unchanged_count="$(json_get unchanged_count <<<"$sync_response")"
total_count="$(json_get total_count <<<"$sync_response")"
items_persisted=$(( ${created_count:-0} + ${updated_count:-0} + ${unchanged_count:-0} ))
if [[ "$items_persisted" -lt 1 || "${total_count:-0}" -lt 1 ]]; then
  echo "[live-jira] sync completed without persisted item evidence" >&2
  exit 1
fi
if [[ "$(json_get details_json.fetch_evidence.mode <<<"$sync_response")" != "jira_paginated_fetch" ]]; then
  echo "[live-jira] missing Jira paginated fetch evidence" >&2
  exit 1
fi
if [[ "$(json_get details_json.fetch_evidence.bounded <<<"$sync_response")" != "True" && "$(json_get details_json.fetch_evidence.bounded <<<"$sync_response")" != "true" ]]; then
  echo "[live-jira] fetch evidence is not bounded" >&2
  exit 1
fi

retry_response="$(api_post "/api/v1/integrations/sync-runs/$RUN_ID/retry" "{}")"
assert_no_token "$retry_response"
if [[ "$(json_get status <<<"$retry_response")" != "completed" ]]; then
  echo "[live-jira] retry run did not complete" >&2
  exit 1
fi

operations_after="$(api_get "/api/v1/integrations/operations/summary")"
synced_assets_after="$(json_get evidence.synced_asset_count <<<"$operations_after")"
if [[ "${synced_assets_after:-0}" -lt "$synced_assets_before" ]]; then
  echo "[live-jira] synced asset count regressed after sync" >&2
  exit 1
fi

outbox_response="$(api_get "/api/v1/integrations/outbox/events?page=1&page_size=20")"
if ! OUTBOX_RESPONSE="$outbox_response" "$PYTHON_BIN" - "$BINDING_ID" <<'PY'; then
import json
import os
import sys

binding_id = sys.argv[1]
data = json.loads(os.environ.get("OUTBOX_RESPONSE") or "{}")
for item in data.get("items", []):
    if (
        item.get("event_type") == "integration.project_sync.completed"
        and str(item.get("aggregate_id")) == binding_id
    ):
        raise SystemExit(0)
print("[live-jira] completed project sync outbox event not found", file=sys.stderr)
raise SystemExit(1)
PY
  exit 1
fi

missing_payload="$(
  JIRA_BASE_URL="$JIRA_BASE_URL" "$PYTHON_BIN" - <<'PY'
import json
import os

print(json.dumps({
    "name": "Candidate Live Jira missing credential",
    "config_json": {
        "base_url": os.environ["JIRA_BASE_URL"],
        "credential_ref": "env:AMX_CANDIDATE_JIRA_MISSING_TOKEN",
        "sync_path": "/rest/api/2/search",
        "connector_profile": "jira_project_sync_v1",
        "retry_attempts": 0,
    },
}))
PY
)"
api_patch "/api/v1/integrations/$INTEGRATION_ID" "$missing_payload" >/dev/null
missing_failure="$(api_post "/api/v1/integrations/project-bindings/$BINDING_ID/sync" "{}")"
if [[ "$(json_get status <<<"$missing_failure")" != "failed" || "$(json_get details_json.failure_state <<<"$missing_failure")" != "missing_credential" ]]; then
  echo "[live-jira] missing credential failure state was not recorded" >&2
  exit 1
fi

invalid_auth_payload="$(
  JIRA_BASE_URL="$JIRA_BASE_URL" "$PYTHON_BIN" - <<'PY'
import json
import os

print(json.dumps({
    "name": "Candidate Live Jira invalid auth",
    "config_json": {
        "base_url": os.environ["JIRA_BASE_URL"],
        "credential_ref": "env:AMX_CANDIDATE_JIRA_API_TOKEN",
        "auth_scheme": "InvalidCandidateScheme",
        "sync_path": "/rest/api/2/search",
        "connector_profile": "jira_project_sync_v1",
        "retry_attempts": 0,
    },
}))
PY
)"
api_patch "/api/v1/integrations/$INTEGRATION_ID" "$invalid_auth_payload" >/dev/null
invalid_failure="$(api_post "/api/v1/integrations/project-bindings/$BINDING_ID/sync" "{}")"
if [[ "$(json_get status <<<"$invalid_failure")" != "failed" || "$(json_get details_json.failure_state <<<"$invalid_failure")" != "expired_credential" ]]; then
  echo "[live-jira] invalid token/auth failure state was not recorded" >&2
  exit 1
fi

remote_error_payload="$(
  JIRA_BASE_URL="$JIRA_BASE_URL" "$PYTHON_BIN" - <<'PY'
import json
import os

print(json.dumps({
    "name": "Candidate Live Jira remote error",
    "config_json": {
        "base_url": os.environ["JIRA_BASE_URL"],
        "credential_ref": "env:AMX_CANDIDATE_JIRA_API_TOKEN",
        "sync_path": "/rest/api/2/search-amx-candidate-missing",
        "connector_profile": "jira_project_sync_v1",
        "retry_attempts": 0,
    },
}))
PY
)"
api_patch "/api/v1/integrations/$INTEGRATION_ID" "$remote_error_payload" >/dev/null
remote_failure="$(api_post "/api/v1/integrations/project-bindings/$BINDING_ID/sync" "{}")"
if [[ "$(json_get status <<<"$remote_failure")" != "failed" || "$(json_get details_json.failure_state <<<"$remote_failure")" != "remote_error" ]]; then
  echo "[live-jira] remote error failure state was not recorded" >&2
  exit 1
fi

echo "[live-jira] verification passed"
echo "[live-jira] project_id=$PROJECT_ID integration_id=$INTEGRATION_ID binding_id=$BINDING_ID sync_run_id=$RUN_ID preview_total=$preview_total synced_assets_before=$synced_assets_before synced_assets_after=$synced_assets_after"
