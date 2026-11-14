#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKUP_FILE="${1:?Usage: scripts/production_restore_drill.sh <custom-format-backup.dump>}"
COMPOSE_FILE="${PROD_COMPOSE_FILE:-docker-compose.production.yml}"
if [[ ! -f "$BACKUP_FILE" || ! -s "$BACKUP_FILE" ]]; then
  echo "Backup file is missing or empty." >&2
  exit 2
fi

# A restore drill always targets a fresh throwaway database, never PROD_DB_NAME.
DRILL_DB="viltara_restore_drill_$(date -u +%s)_$$"
cleanup() {
  docker compose -f "$COMPOSE_FILE" exec -T db sh -ec \
    'psql --username="$POSTGRES_USER" --dbname=postgres --set=ON_ERROR_STOP=1 --command="DROP DATABASE IF EXISTS \"'"${DRILL_DB}"'\" WITH (FORCE)"' \
    >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose -f "$COMPOSE_FILE" exec -T db sh -ec \
  'psql --username="$POSTGRES_USER" --dbname=postgres --set=ON_ERROR_STOP=1 --command="CREATE DATABASE \"'"${DRILL_DB}"'\""' \
  >/dev/null

docker compose -f "$COMPOSE_FILE" exec -T db sh -ec \
  'pg_restore --no-owner --no-acl --exit-on-error --username="$POSTGRES_USER" --dbname="'"$DRILL_DB"'" -' \
  < "$BACKUP_FILE"

docker compose -f "$COMPOSE_FILE" exec -T db sh -ec \
  'psql --username="$POSTGRES_USER" --dbname="'"$DRILL_DB"'" --set=ON_ERROR_STOP=1 --tuples-only --no-align --command="SELECT CASE WHEN to_regclass('\''public.alembic_version'\'') IS NOT NULL AND to_regclass('\''public.users'\'') IS NOT NULL AND to_regclass('\''public.listings'\'') IS NOT NULL AND to_regclass('\''public.orders'\'') IS NOT NULL THEN '\''ok'\'' ELSE '\''missing_core_schema'\'' END"' \
  | grep -qx ok

echo "Restore drill passed for $BACKUP_FILE (temporary database $DRILL_DB)."
