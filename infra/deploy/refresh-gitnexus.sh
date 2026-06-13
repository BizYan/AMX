#!/usr/bin/env bash
set -euo pipefail

GITNEXUS_DIR="${GITNEXUS_DIR:-/home/ubuntu/amx/gitnexus}"
server_image_override="${GITNEXUS_SERVER_IMAGE:-}"
web_image_override="${GITNEXUS_WEB_IMAGE:-}"

if [[ ! -f "$GITNEXUS_DIR/.env" ]]; then
  echo "GitNexus .env not found: $GITNEXUS_DIR/.env" >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a
source "$GITNEXUS_DIR/.env"
set +a

if [[ -n "$server_image_override" ]]; then
  export GITNEXUS_SERVER_IMAGE="$server_image_override"
fi
if [[ -n "$web_image_override" ]]; then
  export GITNEXUS_WEB_IMAGE="$web_image_override"
fi

repo_path="${GITNEXUS_REPOSITORY_PATH:-/workspace/ConsultantAIP}"

cd "$GITNEXUS_DIR"

restore_services() {
  docker compose up -d --remove-orphans >/dev/null 2>&1 || true
}

trap restore_services EXIT

docker compose up -d --remove-orphans
docker compose exec -T gitnexus-server sh -lc '
  repo_path="$1"
  git config --global --get-all safe.directory | grep -Fxq "$repo_path" ||
    git config --global --add safe.directory "$repo_path"
' sh "$repo_path"
docker compose exec -T gitnexus-server \
  git -C "$repo_path" rev-parse --short HEAD

if ! docker compose exec -T gitnexus-server \
  gitnexus analyze "$repo_path" --index-only; then
  echo "[gitnexus] incremental analyze failed; retrying once with a forced full rebuild" >&2
  docker compose exec -T gitnexus-server \
    gitnexus analyze "$repo_path" --index-only --force
fi

docker compose up -d --remove-orphans
docker compose exec -T gitnexus-server gitnexus list
