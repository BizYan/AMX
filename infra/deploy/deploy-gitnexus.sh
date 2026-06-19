#!/usr/bin/env bash
set -euo pipefail

SOURCE_REPO="${SOURCE_REPO:-/home/ubuntu/amx/production/AMX}"
REF="${REF:-main}"
TARGET_DIR="${TARGET_DIR:-/home/ubuntu/amx/gitnexus}"
WORKSPACE_DIR="${WORKSPACE_DIR:-/home/ubuntu/amx/gitnexus/workspace}"
REPOSITORY_URL="${REPOSITORY_URL:-git@github.com:BizYan/AMX.git}"
WORKSPACE_REPO_NAME="${WORKSPACE_REPO_NAME:-AMX}"
WORKSPACE_REPO_DIR="$WORKSPACE_DIR/$WORKSPACE_REPO_NAME"
LEGACY_WORKSPACE_REPO_DIR="$WORKSPACE_DIR/ConsultantAIP"
CONTAINER_REPO_PATH="/workspace/$WORKSPACE_REPO_NAME"
GITNEXUS_SERVER_IMAGE="${GITNEXUS_SERVER_IMAGE:-ghcr.io/abhigyanpatwari/gitnexus:1.6.5}"
GITNEXUS_WEB_IMAGE="${GITNEXUS_WEB_IMAGE:-ghcr.io/abhigyanpatwari/gitnexus-web:1.6.5}"
export GITNEXUS_SERVER_IMAGE GITNEXUS_WEB_IMAGE

if [[ ! -d "$SOURCE_REPO/.git" ]]; then
  echo "SOURCE_REPO must point to a checked out AMX repository: $SOURCE_REPO" >&2
  exit 1
fi

mkdir -p "$TARGET_DIR" "$WORKSPACE_DIR"
cp "$SOURCE_REPO/infra/gitnexus/docker-compose.yml" "$TARGET_DIR/docker-compose.yml"

if [[ ! -f "$TARGET_DIR/.env" ]]; then
  cp "$SOURCE_REPO/infra/gitnexus/env.example" "$TARGET_DIR/.env"
fi

if [[ ! -d "$WORKSPACE_REPO_DIR/.git" && -d "$LEGACY_WORKSPACE_REPO_DIR/.git" ]]; then
  mv "$LEGACY_WORKSPACE_REPO_DIR" "$WORKSPACE_REPO_DIR"
fi

if [[ ! -d "$WORKSPACE_REPO_DIR/.git" ]]; then
  git clone "$REPOSITORY_URL" "$WORKSPACE_REPO_DIR"
fi

git -C "$WORKSPACE_REPO_DIR" remote set-url origin "$REPOSITORY_URL"
git -C "$WORKSPACE_REPO_DIR" fetch origin --prune --tags
git -C "$WORKSPACE_REPO_DIR" checkout --force "$REF"
git -C "$WORKSPACE_REPO_DIR" reset --hard "$REF"

if grep -q '^GITNEXUS_REPOSITORY_PATH=' "$TARGET_DIR/.env"; then
  sed -i "s|^GITNEXUS_REPOSITORY_PATH=.*|GITNEXUS_REPOSITORY_PATH=$CONTAINER_REPO_PATH|" "$TARGET_DIR/.env"
else
  printf '\nGITNEXUS_REPOSITORY_PATH=%s\n' "$CONTAINER_REPO_PATH" >> "$TARGET_DIR/.env"
fi

cd "$TARGET_DIR"
docker compose pull
GITNEXUS_REPOSITORY_PATH="$CONTAINER_REPO_PATH" \
GITNEXUS_LEGACY_REPOSITORY_PATH="/workspace/ConsultantAIP" \
  bash "$SOURCE_REPO/infra/deploy/refresh-gitnexus.sh"
docker compose ps
bash "$SOURCE_REPO/infra/deploy/health-check-gitnexus.sh"
