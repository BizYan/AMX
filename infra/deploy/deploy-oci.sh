#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT="production"
BASE_PATH=""
REF="main"
COMPOSE_FILE="infra/docker-compose.yml"
ENV_FILE=".env"
COMPOSE_PROJECT_NAME_OVERRIDE=""
ENV_FILE_EXPLICIT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      ENVIRONMENT="$2"
      shift 2
      ;;
    --base-path)
      BASE_PATH="$2"
      shift 2
      ;;
    --ref)
      REF="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      ENV_FILE_EXPLICIT=1
      shift 2
      ;;
    --compose-project-name)
      COMPOSE_PROJECT_NAME_OVERRIDE="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$BASE_PATH" ]]; then
  echo "--base-path is required" >&2
  exit 2
fi

cd "$BASE_PATH"
export ENVIRONMENT

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Compose file not found at $BASE_PATH/$COMPOSE_FILE" >&2
  exit 1
fi

if [[ "$ENV_FILE" != /* ]]; then
  ENV_FILE="$BASE_PATH/$ENV_FILE"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Deployment env file is required: $ENV_FILE" >&2
  exit 1
fi

if [[ -n "$COMPOSE_PROJECT_NAME_OVERRIDE" ]] &&
  [[ ! "$COMPOSE_PROJECT_NAME_OVERRIDE" =~ ^[a-z0-9][a-z0-9_-]{0,62}$ ]]; then
  echo "Invalid Compose project name" >&2
  exit 2
fi

if [[ "$ENVIRONMENT" != "production" ]]; then
  if [[ "$ENV_FILE_EXPLICIT" != "1" || -z "$COMPOSE_PROJECT_NAME_OVERRIDE" ]]; then
    echo "Non-production deployment requires explicit --env-file and --compose-project-name" >&2
    exit 2
  fi
  case "$COMPOSE_PROJECT_NAME_OVERRIDE" in
    infra|consultant_ai|production|amx_production*)
      echo "Non-production Compose project name must not use a production identity" >&2
      exit 2
      ;;
  esac
  resolved_base_path="$(realpath -m "$BASE_PATH")"
  resolved_env_file="$(realpath -m "$ENV_FILE")"
  case "$resolved_env_file" in
    "$resolved_base_path"/*) ;;
    *) echo "Non-production env file must stay inside its deployment path" >&2; exit 2 ;;
  esac
fi

echo "[deploy] environment=$ENVIRONMENT ref=$REF base_path=$BASE_PATH"
git fetch origin --prune --tags
case "$REF" in
  origin/*)
    BRANCH_NAME="${REF#origin/}"
    git checkout -B "$BRANCH_NAME" "$REF"
    git reset --hard "$REF"
    ;;
  main|release/*|feature/*|fix/*|infra/*)
    git checkout --force "$REF"
    git reset --hard "origin/$REF"
    ;;
  *)
    git checkout --force "$REF"
    git reset --hard "$REF"
    ;;
esac

bash infra/deploy/validate-runtime-security.sh \
  --environment "$ENVIRONMENT" \
  --env-file "$ENV_FILE"

echo "$REF" > .deploy-ref
date -u +"%Y-%m-%dT%H:%M:%SZ" > .deploy-at

COMPOSE_COMMAND=(docker compose --env-file "$ENV_FILE")
if [[ -n "$COMPOSE_PROJECT_NAME_OVERRIDE" ]]; then
  COMPOSE_COMMAND+=(-p "$COMPOSE_PROJECT_NAME_OVERRIDE")
fi
COMPOSE_COMMAND+=(-f "$COMPOSE_FILE")

"${COMPOSE_COMMAND[@]}" config --quiet
"${COMPOSE_COMMAND[@]}" build
"${COMPOSE_COMMAND[@]}" up -d --remove-orphans
"${COMPOSE_COMMAND[@]}" ps

validator_args=(
  --environment "$ENVIRONMENT"
  --env-file "$ENV_FILE"
  --verify-running
  --compose-file "$COMPOSE_FILE"
)
if [[ -n "$COMPOSE_PROJECT_NAME_OVERRIDE" ]]; then
  validator_args+=(--compose-project-name "$COMPOSE_PROJECT_NAME_OVERRIDE")
fi
bash infra/deploy/validate-runtime-security.sh "${validator_args[@]}"

echo "[deploy] completed"
