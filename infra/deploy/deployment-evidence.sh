#!/usr/bin/env bash
set -euo pipefail

EXPECTED_REF=""
COMPOSE_FILE="infra/docker-compose.yml"
GITNEXUS_URL="http://127.0.0.1:4747/api/health"
GITNEXUS_DIR="${GITNEXUS_DIR:-/home/ubuntu/amx/gitnexus}"
GITNEXUS_REPOSITORY_PATH="${GITNEXUS_REPOSITORY_PATH:-/workspace/AMX}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --expected-ref)
      EXPECTED_REF="$2"
      shift 2
      ;;
    --gitnexus-url)
      GITNEXUS_URL="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$EXPECTED_REF" ]]; then
  echo "--expected-ref is required" >&2
  exit 2
fi

if [[ ! -f "$COMPOSE_FILE" || ! -f ".deploy-ref" || ! -f ".deploy-at" ]]; then
  echo "[deployment-evidence] deployment metadata or compose file is missing" >&2
  exit 1
fi

case "$EXPECTED_REF" in
  origin/*)
    RESOLVED_REF="$EXPECTED_REF"
    ;;
  main|release/*|feature/*|fix/*|infra/*)
    RESOLVED_REF="origin/$EXPECTED_REF"
    ;;
  *)
    RESOLVED_REF="$EXPECTED_REF"
    ;;
esac

DEPLOYED_SHA="$(git rev-parse HEAD)"
EXPECTED_SHA="$(git rev-parse "$RESOLVED_REF")"
RECORDED_REF="$(tr -d '\r\n' < .deploy-ref)"
DEPLOYED_AT="$(tr -d '\r\n' < .deploy-at)"

if [[ "$DEPLOYED_SHA" != "$EXPECTED_SHA" ]]; then
  echo "[deployment-evidence] deployed SHA $DEPLOYED_SHA does not match expected SHA $EXPECTED_SHA" >&2
  exit 1
fi

if [[ "$RECORDED_REF" != "$EXPECTED_REF" ]]; then
  echo "[deployment-evidence] recorded ref $RECORDED_REF does not match expected ref $EXPECTED_REF" >&2
  exit 1
fi

tracked_changes="$(git status --porcelain --untracked-files=no)"
if [[ -n "$tracked_changes" ]]; then
  echo "[deployment-evidence] tracked production worktree changes detected:" >&2
  echo "$tracked_changes" >&2
  exit 1
fi

required_services=(postgres redis api worker web)
running_services="$(docker compose -f "$COMPOSE_FILE" ps --status running --services)"
for service in "${required_services[@]}"; do
  if ! grep -Fxq "$service" <<<"$running_services"; then
    echo "[deployment-evidence] required service is not running: $service" >&2
    exit 1
  fi
done

gitnexus_health="$(curl -fsS "$GITNEXUS_URL")"
python3 -c 'import json,sys; json.load(sys.stdin)' <<<"$gitnexus_health"

gitnexus_repo_sha="$(
  docker compose -f "$GITNEXUS_DIR/docker-compose.yml" --env-file "$GITNEXUS_DIR/.env" \
    exec -T gitnexus-server git -C "$GITNEXUS_REPOSITORY_PATH" rev-parse HEAD
)"
if [[ "$gitnexus_repo_sha" != "$DEPLOYED_SHA" ]]; then
  echo "[deployment-evidence] GitNexus repository SHA $gitnexus_repo_sha does not match deployed SHA $DEPLOYED_SHA" >&2
  exit 1
fi

gitnexus_list="$(
  docker compose -f "$GITNEXUS_DIR/docker-compose.yml" --env-file "$GITNEXUS_DIR/.env" \
    exec -T gitnexus-server gitnexus list
)"
if ! grep -Eq "Commit:[[:space:]]+${DEPLOYED_SHA:0:7}([[:space:]]|$)" <<<"$gitnexus_list"; then
  echo "[deployment-evidence] GitNexus index does not contain deployed SHA ${DEPLOYED_SHA:0:7}" >&2
  exit 1
fi

export DEPLOYED_SHA EXPECTED_REF EXPECTED_SHA RECORDED_REF DEPLOYED_AT
export RUNNING_SERVICES="$(tr '\n' ',' <<<"$running_services" | sed 's/,$//')"
export GITNEXUS_REPO_SHA="$gitnexus_repo_sha"
python3 <<'PY'
import json
import os

print(json.dumps({
    "status": "verified",
    "expected_ref": os.environ["EXPECTED_REF"],
    "recorded_ref": os.environ["RECORDED_REF"],
    "expected_sha": os.environ["EXPECTED_SHA"],
    "deployed_sha": os.environ["DEPLOYED_SHA"],
    "deployed_at": os.environ["DEPLOYED_AT"],
    "tracked_worktree_clean": True,
    "running_services": os.environ["RUNNING_SERVICES"].split(","),
    "gitnexus_healthy": True,
    "gitnexus_indexed_sha": os.environ["GITNEXUS_REPO_SHA"],
}, ensure_ascii=False, indent=2))
PY
