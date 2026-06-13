#!/usr/bin/env bash
set -euo pipefail

BASE_PATH=""
REF=""
COMPOSE_FILE="infra/docker-compose.yml"

while [[ $# -gt 0 ]]; do
  case "$1" in
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

if [[ -z "$BASE_PATH" || -z "$REF" ]]; then
  echo "--base-path and --ref are required" >&2
  exit 2
fi

cd "$BASE_PATH"
echo "[rollback] target_ref=$REF base_path=$BASE_PATH"
git fetch origin --prune --tags
git checkout --force "$REF"
git reset --hard "$REF"
echo "$REF" > .deploy-ref
date -u +"%Y-%m-%dT%H:%M:%SZ" > .rollback-at
docker compose -f "$COMPOSE_FILE" build
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
docker compose -f "$COMPOSE_FILE" ps
echo "[rollback] completed"
