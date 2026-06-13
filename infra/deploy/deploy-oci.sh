#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT="production"
BASE_PATH=""
REF="main"
COMPOSE_FILE="infra/docker-compose.yml"

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

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Compose file not found at $BASE_PATH/$COMPOSE_FILE" >&2
  exit 1
fi

if [[ ! -f ".env" ]]; then
  echo ".env is required in $BASE_PATH before deployment" >&2
  exit 1
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

echo "$REF" > .deploy-ref
date -u +"%Y-%m-%dT%H:%M:%SZ" > .deploy-at

docker compose -f "$COMPOSE_FILE" config >/tmp/amx-compose-config.yml
docker compose -f "$COMPOSE_FILE" build
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
docker compose -f "$COMPOSE_FILE" ps

echo "[deploy] completed"
