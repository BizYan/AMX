#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=""
COMPOSE_PROJECT_NAME_INPUT=""
COMPOSE_CONFIG=""
PRODUCTION_PATH="/home/ubuntu/amx/production/AMX"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --compose-project-name)
      COMPOSE_PROJECT_NAME_INPUT="$2"
      shift 2
      ;;
    --compose-config)
      COMPOSE_CONFIG="$2"
      shift 2
      ;;
    --production-path)
      PRODUCTION_PATH="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$ENV_FILE" ]]; then
  echo "--env-file is required" >&2
  exit 2
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Candidate env file not found: $ENV_FILE" >&2
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

fail() {
  echo "[candidate-safety] $*" >&2
  exit 1
}

case "$ENV_FILE" in
  .env|../.env|*/production/AMX/.env|"$PRODUCTION_PATH/.env")
    fail "candidate env file must not be production .env: $ENV_FILE"
    ;;
esac

PROJECT_NAME="${COMPOSE_PROJECT_NAME_INPUT:-$(read_env_value COMPOSE_PROJECT_NAME)}"
[[ "$PROJECT_NAME" == amx_rc_* ]] || fail "COMPOSE_PROJECT_NAME must start with amx_rc_: $PROJECT_NAME"

AMX_ENV_FILE="$(read_env_value AMX_ENV_FILE)"
[[ -n "$AMX_ENV_FILE" ]] || fail "AMX_ENV_FILE is required"
[[ "$AMX_ENV_FILE" == "$ENV_FILE" || "$AMX_ENV_FILE" == "../$ENV_FILE" ]] \
  || fail "AMX_ENV_FILE must point to the candidate env file"
case "$AMX_ENV_FILE" in
  .env|../.env|*/production/AMX/.env|"$PRODUCTION_PATH/.env")
    fail "AMX_ENV_FILE must not point at production .env: $AMX_ENV_FILE"
    ;;
esac

POSTGRES_DB="$(read_env_value POSTGRES_DB)"
[[ "$POSTGRES_DB" == amx_rc_* ]] || fail "POSTGRES_DB must be candidate scoped"
[[ "$POSTGRES_DB" != "consultant_ai" ]] || fail "POSTGRES_DB must not be production database"

NETWORK="$(read_env_value AMX_RUNTIME_NETWORK)"
[[ "$NETWORK" == amx_rc_* ]] || fail "AMX_RUNTIME_NETWORK must be candidate scoped"

CONTAINER_PREFIX="$(read_env_value AMX_CONTAINER_PREFIX)"
[[ "$CONTAINER_PREFIX" == amx_rc_* ]] || fail "AMX_CONTAINER_PREFIX must be candidate scoped"

POSTGRES_VOLUME="$(read_env_value AMX_POSTGRES_VOLUME)"
REDIS_VOLUME="$(read_env_value AMX_REDIS_VOLUME)"
[[ "$POSTGRES_VOLUME" == amx_rc_* ]] || fail "AMX_POSTGRES_VOLUME must be candidate scoped"
[[ "$REDIS_VOLUME" == amx_rc_* ]] || fail "AMX_REDIS_VOLUME must be candidate scoped"

for entry in \
  "POSTGRES_HOST_PORT:15432" \
  "REDIS_HOST_PORT:16379" \
  "API_HOST_PORT:18000" \
  "WEB_HOST_PORT:3000"; do
  key="${entry%%:*}"
  forbidden="${entry##*:}"
  value="$(read_env_value "$key")"
  [[ -n "$value" ]] || fail "$key is required"
  [[ "$value" != "$forbidden" ]] || fail "$key must not use production port $forbidden"
done

CURRENT_DIR="$(pwd -P)"
[[ "$CURRENT_DIR" != "$PRODUCTION_PATH" ]] || fail "working directory must not be production path"

if [[ -n "$COMPOSE_CONFIG" ]]; then
  [[ -f "$COMPOSE_CONFIG" ]] || fail "compose config not found: $COMPOSE_CONFIG"
  ! grep -Eq '(^|[[:space:]])\.\./\.env([[:space:]]|$)' "$COMPOSE_CONFIG" \
    || fail "candidate compose config must not reference ../.env"
  ! grep -Eq "consultant_ai_(api|web|worker|postgres|redis)" "$COMPOSE_CONFIG" \
    || fail "candidate compose config must not include production container names"
  ! grep -Eq "127\.0\.0\.1:(15432|16379|18000|3000)" "$COMPOSE_CONFIG" \
    || fail "candidate compose config must not bind production ports"
  grep -Fq "name: $NETWORK" "$COMPOSE_CONFIG" || fail "candidate network name missing from rendered compose config"
  grep -Fq "name: $POSTGRES_VOLUME" "$COMPOSE_CONFIG" || fail "candidate postgres volume missing from rendered compose config"
  grep -Fq "name: $REDIS_VOLUME" "$COMPOSE_CONFIG" || fail "candidate redis volume missing from rendered compose config"
  grep -Fq 'restart: "no"' "$COMPOSE_CONFIG" || grep -Fq "restart: 'no'" "$COMPOSE_CONFIG" || grep -Fq "restart: no" "$COMPOSE_CONFIG" \
    || fail "candidate API/worker/web restart policy must be no"
fi

echo "[candidate-safety] passed project=$PROJECT_NAME env=$ENV_FILE db=$POSTGRES_DB network=$NETWORK"
