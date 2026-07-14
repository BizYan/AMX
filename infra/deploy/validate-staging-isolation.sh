#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=""
COMPOSE_PROJECT_NAME=""
WORKING_DIRECTORY=""
STAGING_ROOT=""
COMPOSE_FILE="infra/docker-compose.yml"
APPROVED_STAGING_ROOT="${AMX_APPROVED_STAGING_ROOT:-/home/ubuntu/amx/staging}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --compose-project-name)
      COMPOSE_PROJECT_NAME="$2"
      shift 2
      ;;
    --working-directory)
      WORKING_DIRECTORY="$2"
      shift 2
      ;;
    --staging-root)
      STAGING_ROOT="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

for required in ENV_FILE COMPOSE_PROJECT_NAME WORKING_DIRECTORY STAGING_ROOT; do
  if [[ -z "${!required}" ]]; then
    echo "Missing required staging isolation argument: $required" >&2
    exit 2
  fi
done

working_directory="$(realpath -m "$WORKING_DIRECTORY")"
staging_root="$(realpath -m "$STAGING_ROOT")"
env_file="$(realpath -m "$ENV_FILE")"

[[ "$staging_root" == "$APPROVED_STAGING_ROOT" ]]
case "$working_directory" in
  "$staging_root"/*) ;;
  *) echo "working directory must be inside the approved staging root" >&2; exit 1 ;;
esac
[[ "$working_directory" != "/home/ubuntu/amx/production/AMX" ]]
[[ "$env_file" == "$working_directory/.env" ]]
[[ "$env_file" != "/home/ubuntu/amx/production/AMX/.env" ]]
[[ -f "$env_file" ]]
[[ "$COMPOSE_PROJECT_NAME" =~ ^amx_staging_[a-z0-9_]{1,51}$ ]]

read_env_value() {
  local key="$1"
  awk -v key="$key" '
    index($0, key "=") == 1 {
      sub(/^[^=]*=/, "")
      sub(/\r$/, "")
      print
      exit
    }
  ' "$env_file"
}

assert_env_equals() {
  local key="$1"
  local expected="$2"
  local actual
  actual="$(read_env_value "$key")"
  if [[ "$actual" != "$expected" ]]; then
    echo "staging isolation mismatch: $key" >&2
    exit 1
  fi
}

assert_env_equals COMPOSE_PROJECT_NAME "$COMPOSE_PROJECT_NAME"
assert_env_equals AMX_CONTAINER_PREFIX "$COMPOSE_PROJECT_NAME"
assert_env_equals AMX_RUNTIME_NETWORK "${COMPOSE_PROJECT_NAME}_network"
assert_env_equals POSTGRES_DB "$COMPOSE_PROJECT_NAME"
assert_env_equals AMX_ENV_FILE "$env_file"
assert_env_equals AMX_RESTART_POLICY "no"

declare -A seen_ports=()
for key in POSTGRES_HOST_PORT REDIS_HOST_PORT API_HOST_PORT WEB_HOST_PORT; do
  port="$(read_env_value "$key")"
  [[ "$port" =~ ^[0-9]{4,5}$ ]]
  ((port >= 1024 && port <= 65535))
  case "$port" in
    15432|16379|18000|3000)
      echo "staging must not use a production port: $key" >&2
      exit 1
      ;;
  esac
  if [[ -n "${seen_ports[$port]:-}" ]]; then
    echo "staging ports must be unique" >&2
    exit 1
  fi
  seen_ports[$port]=1
done

cd "$working_directory"
rendered_config="$(mktemp)"
trap 'rm -f "$rendered_config"' EXIT
docker compose \
  --env-file "$env_file" \
  -p "$COMPOSE_PROJECT_NAME" \
  -f "$COMPOSE_FILE" \
  config > "$rendered_config"

for service in postgres redis api worker web; do
  grep -Fq "container_name: ${COMPOSE_PROJECT_NAME}_${service}" "$rendered_config"
done
grep -Fq "name: ${COMPOSE_PROJECT_NAME}_network" "$rendered_config"
grep -Fq "name: ${COMPOSE_PROJECT_NAME}_postgres_data" "$rendered_config"
grep -Fq "name: ${COMPOSE_PROJECT_NAME}_redis_data" "$rendered_config"
[[ "$(grep -Fc 'restart: "no"' "$rendered_config")" -eq 3 ]]
[[ "$(grep -Fc "$env_file" "$rendered_config")" -ge 3 ]]
for key in POSTGRES_HOST_PORT REDIS_HOST_PORT API_HOST_PORT WEB_HOST_PORT; do
  port="$(read_env_value "$key")"
  grep -Fq "published: \"$port\"" "$rendered_config"
done
if grep -Fq 'container_name: consultant_ai_' "$rendered_config"; then
  echo "rendered staging config references production resources" >&2
  exit 1
fi

if [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")" ]]; then
  echo "staging Compose project already has containers" >&2
  exit 1
fi
if docker network inspect "${COMPOSE_PROJECT_NAME}_network" >/dev/null 2>&1; then
  echo "staging network already exists" >&2
  exit 1
fi
if [[ -n "$(docker volume ls --format '{{.Name}}' | grep -E "^${COMPOSE_PROJECT_NAME}_(postgres_data|redis_data)$" || true)" ]]; then
  echo "staging volumes already exist" >&2
  exit 1
fi

for container in consultant_ai_postgres consultant_ai_redis consultant_ai_api consultant_ai_worker consultant_ai_web; do
  if docker inspect "$container" >/dev/null 2>&1; then
    production_working_dir="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$container")"
    if [[ "$production_working_dir" == "$staging_root"/* ]]; then
      echo "production container is owned by a staging working directory: $container" >&2
      exit 1
    fi
  fi
done

echo "staging_isolation=passed"
