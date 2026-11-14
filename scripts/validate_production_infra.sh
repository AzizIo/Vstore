#!/usr/bin/env bash
# Static guardrails for production infrastructure files. Does not read .env,
# contact production systems, print secrets, or start containers.
set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.production.yml"
NGINX_FILE="$ROOT_DIR/frontend/nginx.production.conf"
RUNBOOK="$ROOT_DIR/docs/PRODUCTION_OPERATIONS_RUNBOOK.md"

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
require_file() { [[ -f "$1" ]] || fail "Required file is missing: ${1#"$ROOT_DIR"/}"; }
require_file "$COMPOSE_FILE"
require_file "$NGINX_FILE"
require_file "$RUNBOOK"

# This stack intentionally has exactly one host-published port: the Mini App
# bound to loopback. The Compose JSON validation in the dedicated workflow
# performs the structural check as well.
port_blocks="$(grep -Ec '^[[:space:]]+ports:' "$COMPOSE_FILE" || true)"
[[ "$port_blocks" == "1" ]] || fail "Only the Mini App may publish a host port"
grep -Fq '"127.0.0.1:${PROD_HTTP_PORT:-8081}:80"' "$COMPOSE_FILE" \
  || fail "Mini App must be bound to host loopback"
if grep -Eq '^[[:space:]]*-[[:space:]]*["]?([0-9.]+:)?(5432|6379|8000):' "$COMPOSE_FILE"; then
  fail "Potential database, Redis or API host port exposure found"
fi

grep -Eq 'production_postgres_data:' "$COMPOSE_FILE" \
  || fail "Named production PostgreSQL volume declaration is missing"
grep -Eq 'external:[[:space:]]*true' "$COMPOSE_FILE" \
  || fail "Production PostgreSQL volume must be external"
grep -Fq 'PROD_POSTGRES_VOLUME_NAME:?Set PROD_POSTGRES_VOLUME_NAME' "$COMPOSE_FILE" \
  || fail "Exact production volume name must be required"
grep -Eq 'TON_CONNECT_NETWORK:.*PROD_TON_CONNECT_NETWORK' "$COMPOSE_FILE" \
  || fail "Production TON network must be explicit"
grep -Eq 'ENVIRONMENT: production' "$COMPOSE_FILE" \
  || fail "Production environment mode must be explicit"
if grep -Eq 'TELEGRAM_STARS_TEST_ENABLED|TELEGRAM_STARS_TEST_BOT_TOKEN|PREVIEW_MODE|TON_CONNECT_NETWORK:[[:space:]]*testnet' "$COMPOSE_FILE"; then
  fail "Test-only payment/Preview/testnet configuration found in production Compose"
fi
grep -Eq 'server_tokens off;' "$NGINX_FILE" || fail "Nginx server_tokens must be disabled"
grep -Eq 'X-Content-Type-Options' "$NGINX_FILE" || fail "Nginx nosniff header is missing"
grep -Eq 'Referrer-Policy' "$NGINX_FILE" || fail "Nginx Referrer-Policy header is missing"
grep -Eq 'Production operations and recovery runbook' "$RUNBOOK" || fail "Operations runbook is missing"

printf 'Static production infrastructure guardrails passed. No live systems were checked.\n'
