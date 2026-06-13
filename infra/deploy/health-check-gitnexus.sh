#!/usr/bin/env bash
set -euo pipefail

GITNEXUS_DIR="${GITNEXUS_DIR:-/home/ubuntu/amx/gitnexus}"

if [[ -f "$GITNEXUS_DIR/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$GITNEXUS_DIR/.env"
  set +a
fi

server_url="${GITNEXUS_BASE_URL:-http://127.0.0.1:4747}"
web_url="${GITNEXUS_WEB_URL:-http://127.0.0.1:4173}"

curl -fsS "$server_url/api/health"
curl -fsS "$web_url/" >/dev/null
echo
echo "[gitnexus] healthy server=$server_url web=$web_url"
