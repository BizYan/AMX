#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=""
COMPOSE_PROJECT_NAME=""
COMPOSE_FILE="infra/docker-compose.yml"
HISTORICAL_REVISION="0021_invitation_delivery"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE_FILE="$SCRIPT_DIR/fixtures/historical-migration-baseline-0021.sql"

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
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$ENV_FILE" || -z "$COMPOSE_PROJECT_NAME" ]]; then
  echo "--env-file and --compose-project-name are required" >&2
  exit 2
fi
[[ -f "$ENV_FILE" ]]
[[ -f "$FIXTURE_FILE" ]]
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
  ' "$ENV_FILE"
}

POSTGRES_USER="$(read_env_value POSTGRES_USER)"
POSTGRES_DB="$(read_env_value POSTGRES_DB)"
[[ -n "$POSTGRES_USER" && -n "$POSTGRES_DB" ]]
[[ "$POSTGRES_DB" == "$COMPOSE_PROJECT_NAME" ]]

compose=(
  docker compose
  --env-file "$ENV_FILE"
  -p "$COMPOSE_PROJECT_NAME"
  -f "$COMPOSE_FILE"
)

"${compose[@]}" up -d postgres redis
for attempt in {1..30}; do
  if "${compose[@]}" exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null; then
    break
  fi
  if [[ "$attempt" == "30" ]]; then
    echo "historical baseline PostgreSQL did not become ready" >&2
    exit 1
  fi
  sleep 2
done

"${compose[@]}" build api
"${compose[@]}" exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  < "$FIXTURE_FILE"
"${compose[@]}" run --rm --no-deps api \
  /app/.venv/bin/alembic stamp "$HISTORICAL_REVISION"
"${compose[@]}" run --rm --no-deps api \
  /app/.venv/bin/alembic upgrade head

echo "migration_gate=historical migration compatibility baseline verification"
echo "baseline_fixture=$HISTORICAL_REVISION plus projects/documents ORM smoke columns"
echo "scope=not a clean empty-database full-history migration proof"
echo "migration_upgrade=head"
