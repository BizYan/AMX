#!/usr/bin/env bash
set -euo pipefail

BASE_URL="http://localhost:18000"
ENV_FILE=".env"
CURL_BIN="${CURL_BIN:-curl}"

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
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[authenticated-smoke] environment file not found: $ENV_FILE" >&2
  exit 1
fi

read_env_value() {
  local key="$1"
  python3 - "$ENV_FILE" "$key" <<'PY'
from pathlib import Path
import sys

path, key = sys.argv[1:]
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

BOOTSTRAP_ADMIN_EMAIL="$(read_env_value BOOTSTRAP_ADMIN_EMAIL)"
BOOTSTRAP_ADMIN_PASSWORD="$(read_env_value BOOTSTRAP_ADMIN_PASSWORD)"
export BOOTSTRAP_ADMIN_EMAIL BOOTSTRAP_ADMIN_PASSWORD

if [[ -z "$BOOTSTRAP_ADMIN_EMAIL" || -z "$BOOTSTRAP_ADMIN_PASSWORD" ]]; then
  echo "[authenticated-smoke] BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD are required" >&2
  exit 1
fi

json_value() {
  local key="$1"
  python3 -c 'import json,sys; data=json.load(sys.stdin); value=data.get(sys.argv[1], ""); print(value if value is not None else "")' "$key"
}

validate_json() {
  python3 -c 'import json,sys; json.load(sys.stdin)'
}

check_authenticated_json() {
  local name="$1"
  local path="$2"
  local output

  output="$("$CURL_BIN" -fsS -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL$path")"
  validate_json <<<"$output"
  echo "[authenticated-smoke] $name ok" >&2
  printf '%s' "$output"
}

check_public_json() {
  local name="$1"
  local path="$2"
  local output

  output="$("$CURL_BIN" -fsS "$BASE_URL$path")"
  validate_json <<<"$output"
  echo "[authenticated-smoke] $name ok" >&2
  printf '%s' "$output"
}

assert_provider_readiness() {
  python3 -c '
import json
import sys

data = json.load(sys.stdin)
production_ready = data.get("production_ready") is True
sandbox_count = int(data.get("sandbox_providers") or 0)
mock_count = int(data.get("mock_providers") or 0)
bad_items = [
    item
    for item in data.get("items", [])
    if str(item.get("readiness", "")).lower() in {"sandbox", "mock", "unconfigured", "inactive", "failed"}
]

failed = False
if not production_ready:
    print("[authenticated-smoke] provider readiness is not production-ready", file=sys.stderr)
    failed = True
if sandbox_count or mock_count or bad_items:
    print(
        "[authenticated-smoke] sandbox/mock/test provider evidence cannot satisfy real API smoke",
        file=sys.stderr,
    )
    failed = True
if failed:
    sys.exit(1)
'
}

assert_quota_readiness() {
  python3 -c '
import json
import sys

data = json.load(sys.stdin)
limit = data.get("limit")
try:
    limit_value = int(limit)
except (TypeError, ValueError):
    print("[authenticated-smoke] quota readiness did not return a numeric limit", file=sys.stderr)
    sys.exit(1)
if limit_value <= 0:
    print("[authenticated-smoke] quota readiness returned a non-positive limit", file=sys.stderr)
    sys.exit(1)
'
}

assert_capability_readiness() {
  python3 -c '
import json
import sys

data = json.load(sys.stdin)
if data.get("production_ready") is not True:
    print("[authenticated-smoke] capability readiness is not production-ready", file=sys.stderr)
    sys.exit(1)

blocked_markers = {"placeholder", "mock", "sandbox", "fixture", "test_only", "test-only"}

def contains_blocked_marker(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() == "evidence" and contains_blocked_marker(child):
                return True
            if contains_blocked_marker(child):
                return True
        return False
    if isinstance(value, list):
        return any(contains_blocked_marker(item) for item in value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in blocked_markers or any(marker in normalized for marker in blocked_markers)
    return False

if contains_blocked_marker(data.get("capabilities", [])):
    print("[authenticated-smoke] capability readiness contains placeholder-only evidence", file=sys.stderr)
    sys.exit(1)
'
}

check_public_json "health" "/health"

echo "[authenticated-smoke] logging in through $BASE_URL/api/v1/identity/auth/login"
login_payload="$(
  python3 -c 'import json,os; print(json.dumps({"email": os.environ["BOOTSTRAP_ADMIN_EMAIL"], "password": os.environ["BOOTSTRAP_ADMIN_PASSWORD"]}))'
)"
login_response="$(
  "$CURL_BIN" -fsS \
    -H "Content-Type: application/json" \
    -d "$login_payload" \
    "$BASE_URL/api/v1/identity/auth/login"
)"
ACCESS_TOKEN="$(json_value access_token <<<"$login_response")"

if [[ -z "$ACCESS_TOKEN" ]]; then
  echo "[authenticated-smoke] login did not return an access token" >&2
  exit 1
fi

check_authenticated_json "current user" "/api/v1/identity/auth/me" >/dev/null
check_authenticated_json "projects" "/api/v1/projects?page=1&page_size=5" >/dev/null
check_authenticated_json "documents" "/api/v1/documents?page=1&page_size=5" >/dev/null
provider_readiness="$(check_authenticated_json "provider readiness" "/api/v1/providers/readiness")"
assert_provider_readiness <<<"$provider_readiness"
quota_readiness="$(check_authenticated_json "quota" "/api/v1/ops/quota")"
assert_quota_readiness <<<"$quota_readiness"
capability_readiness="$(check_authenticated_json "capability readiness" "/api/v1/ops/capabilities/readiness")"
assert_capability_readiness <<<"$capability_readiness"
check_authenticated_json "capability commissioning" "/api/v1/ops/capabilities/commissioning" >/dev/null

echo "[authenticated-smoke] all authenticated production checks passed"
