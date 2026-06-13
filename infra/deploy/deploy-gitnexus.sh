#!/usr/bin/env bash
set -euo pipefail

SOURCE_REPO="${SOURCE_REPO:-/home/ubuntu/amx/production/ConsultantAIP}"
TARGET_DIR="${TARGET_DIR:-/home/ubuntu/amx/gitnexus}"
WORKSPACE_DIR="${WORKSPACE_DIR:-/home/ubuntu/amx/gitnexus/workspace}"
REPOSITORY_URL="${REPOSITORY_URL:-git@github.com:BizYan/AMX.git}"
GITNEXUS_SERVER_IMAGE="${GITNEXUS_SERVER_IMAGE:-ghcr.io/abhigyanpatwari/gitnexus:1.6.5}"
GITNEXUS_WEB_IMAGE="${GITNEXUS_WEB_IMAGE:-ghcr.io/abhigyanpatwari/gitnexus-web:1.6.5}"
export GITNEXUS_SERVER_IMAGE GITNEXUS_WEB_IMAGE

if [[ ! -d "$SOURCE_REPO/.git" ]]; then
  echo "SOURCE_REPO must point to a checked out ConsultantAIP repository: $SOURCE_REPO" >&2
  exit 1
fi

mkdir -p "$TARGET_DIR" "$WORKSPACE_DIR"
cp "$SOURCE_REPO/infra/gitnexus/docker-compose.yml" "$TARGET_DIR/docker-compose.yml"

if [[ ! -f "$TARGET_DIR/.env" ]]; then
  cp "$SOURCE_REPO/infra/gitnexus/env.example" "$TARGET_DIR/.env"
fi

if [[ ! -d "$WORKSPACE_DIR/ConsultantAIP/.git" ]]; then
  git clone "$REPOSITORY_URL" "$WORKSPACE_DIR/ConsultantAIP"
fi

git -C "$WORKSPACE_DIR/ConsultantAIP" fetch origin --prune --tags
git -C "$WORKSPACE_DIR/ConsultantAIP" checkout --force main
git -C "$WORKSPACE_DIR/ConsultantAIP" reset --hard origin/main

cd "$TARGET_DIR"
docker compose pull
bash "$SOURCE_REPO/infra/deploy/refresh-gitnexus.sh"
docker compose ps
bash "$SOURCE_REPO/infra/deploy/health-check-gitnexus.sh"
