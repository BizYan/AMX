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
  echo "[capability-activation] environment file not found: $ENV_FILE" >&2
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
  echo "[capability-activation] BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD are required" >&2
  exit 1
fi

json_value() {
  local key="$1"
  python3 -c 'import json,sys; data=json.load(sys.stdin); value=data.get(sys.argv[1], ""); print(value if value is not None else "")' "$key"
}

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
  echo "[capability-activation] login did not return an access token" >&2
  exit 1
fi

activation_response="$(
  "$CURL_BIN" -fsS \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"dry_run":false,"confirm":true}' \
    "$BASE_URL/api/v1/ops/capabilities/activation-run"
)"

python3 -c '
import json
import sys

data = json.load(sys.stdin)
after = data.get("readiness_after") or {}
actions = data.get("actions") or []
completed = [str(item.get("key")) for item in actions if item.get("status") == "completed"]
skipped = [str(item.get("key")) for item in actions if item.get("status") == "skipped"]
failed = [str(item.get("key")) for item in actions if item.get("status") == "failed"]
print(
    "[capability-activation] executed={} production_ready={} completed_actions={} skipped_actions={} failed_actions={}".format(
        data.get("executed"),
        after.get("production_ready"),
        ",".join(completed),
        ",".join(skipped),
        ",".join(failed),
    )
)
if after.get("production_ready") is not True:
    sys.exit(1)
' <<<"$activation_response"
