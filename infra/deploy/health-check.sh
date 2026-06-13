#!/usr/bin/env bash
set -euo pipefail

BASE_URL="http://localhost:18000"
COMPOSE_FILE="infra/docker-compose.yml"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      BASE_URL="${2%/}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

echo "[health] checking compose services"
docker compose -f "$COMPOSE_FILE" ps

echo "[health] checking API health via $BASE_URL/health"
for attempt in {1..30}; do
  if curl -fsS "$BASE_URL/health" >/tmp/amx-health.json; then
    cat /tmp/amx-health.json
    echo
    echo "[health] healthy"
    exit 0
  fi
  echo "[health] attempt $attempt failed; retrying"
  sleep 3
done

echo "[health] failed after retries" >&2
docker compose -f "$COMPOSE_FILE" logs --tail=120 api || true
exit 1
