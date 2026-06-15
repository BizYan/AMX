#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT="production"
ENV_FILE=".env"
COMPOSE_FILE="infra/docker-compose.yml"
VERIFY_RUNNING=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --environment)
      ENVIRONMENT="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --compose-file)
      COMPOSE_FILE="$2"
      shift 2
      ;;
    --verify-running)
      VERIFY_RUNNING=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ "$ENVIRONMENT" != "production" ]]; then
  echo "[runtime-security] non-production validation skipped"
  exit 0
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Production .env is required: $ENV_FILE" >&2
  exit 1
fi

mode="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || stat -f '%Lp' "$ENV_FILE")"
permissions="${mode: -3}"
if [[ "${permissions:1:1}" != "0" || "${permissions:2:1}" != "0" ]]; then
  echo "Production .env must not be readable or writable by group or other users" >&2
  exit 1
fi

read_env_value() {
  local key="$1"
  awk -v key="$key" '
    index($0, key "=") == 1 {
      sub(/^[^=]*=/, "")
      sub(/\r$/, "")
      gsub(/^["'"'"']|["'"'"']$/, "")
      print
      exit
    }
  ' "$ENV_FILE"
}

jwt_secret="$(read_env_value "JWT_SECRET_KEY")"
jwt_secret="$(printf '%s' "$jwt_secret" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
jwt_secret_normalized="$(printf '%s' "$jwt_secret" | tr '[:upper:]' '[:lower:]')"
case "$jwt_secret_normalized" in
  ""|change-me|change-me-in-production|changeme|development-secret|dev-secret|jwt-secret|secret|test|test-secret|your-super-secret-jwt-key-change-in-production)
    echo "Production JWT_SECRET_KEY must be a real non-placeholder secret" >&2
    exit 1
    ;;
esac
if [[ "${#jwt_secret}" -lt 32 ]]; then
  echo "Production JWT_SECRET_KEY must be a real non-placeholder secret" >&2
  exit 1
fi

bootstrap_admin_email="$(read_env_value "BOOTSTRAP_ADMIN_EMAIL")"
bootstrap_admin_email="$(printf '%s' "$bootstrap_admin_email" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
if [[ -n "$bootstrap_admin_email" ]]; then
  bootstrap_admin_password="$(read_env_value "BOOTSTRAP_ADMIN_PASSWORD")"
  bootstrap_admin_password="$(printf '%s' "$bootstrap_admin_password" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  bootstrap_admin_password_normalized="$(printf '%s' "$bootstrap_admin_password" | tr '[:upper:]' '[:lower:]')"
  case "$bootstrap_admin_password_normalized" in
    ""|admin|admin123|change-me|change-me-in-production|changeme|consultant|consultant123|password|password123|test|test-password|test_password)
      echo "Production BOOTSTRAP_ADMIN_PASSWORD must be a real non-placeholder password" >&2
      exit 1
      ;;
  esac
fi

postgres_password="$(read_env_value "POSTGRES_PASSWORD")"
postgres_password="$(printf '%s' "$postgres_password" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
postgres_password_normalized="$(printf '%s' "$postgres_password" | tr '[:upper:]' '[:lower:]')"
database_url="$(read_env_value "DATABASE_URL")"
database_url_normalized="$(printf '%s' "$database_url" | tr '[:upper:]' '[:lower:]')"
case "$postgres_password_normalized" in
  ""|consultant123|postgres|postgres123|password|password123|test|test-password|test_password)
    echo "Production database credentials must not use example passwords" >&2
    exit 1
    ;;
esac
case "$database_url_normalized" in
  *consultant123*|*postgres:postgres*|*password123*|*test-password*|*test_password*)
    echo "Production database credentials must not use example passwords" >&2
    exit 1
    ;;
esac

for variable in \
  POSTGRES_BIND_ADDRESS \
  REDIS_BIND_ADDRESS \
  API_BIND_ADDRESS \
  WEB_BIND_ADDRESS; do
  value="$(read_env_value "$variable")"
  value="${value:-127.0.0.1}"
  if [[ "$value" != "127.0.0.1" ]]; then
    echo "Production bind address must be loopback: $variable" >&2
    exit 1
  fi
done

if [[ "$VERIFY_RUNNING" == "1" ]]; then
  for mapping in postgres:5432 redis:6379 api:8000 web:3000; do
    service="${mapping%%:*}"
    container_port="${mapping##*:}"
    bindings="$(docker compose -f "$COMPOSE_FILE" port "$service" "$container_port")"
    if [[ -z "$bindings" ]]; then
      echo "Running service port is not published: $service:$container_port" >&2
      exit 1
    fi
    while IFS= read -r binding; do
      if [[ "$binding" != 127.0.0.1:* ]]; then
        echo "Running service port is not loopback-only: $service:$container_port" >&2
        exit 1
      fi
    done <<<"$bindings"
  done
fi

echo "[runtime-security] production bind addresses and .env permissions verified"
