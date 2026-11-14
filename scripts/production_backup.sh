#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${PROD_COMPOSE_FILE:-docker-compose.production.yml}"
BACKUP_DIR="${PROD_BACKUP_DIR:-$ROOT_DIR/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FINAL="$BACKUP_DIR/viltara-production-$STAMP.dump"
TMP="$FINAL.partial"

mkdir -p "$BACKUP_DIR"
trap 'rm -f "$TMP"' EXIT

docker compose -f "$COMPOSE_FILE" exec -T db sh -ec \
  'pg_dump --format=custom --no-owner --no-acl --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  > "$TMP"

test -s "$TMP"
# Validate that PostgreSQL can read the custom archive before publishing it.
docker compose -f "$COMPOSE_FILE" exec -T db pg_restore --list < "$TMP" >/dev/null

mv "$TMP" "$FINAL"
sha256sum "$FINAL" > "$FINAL.sha256"
chmod 600 "$FINAL" "$FINAL.sha256"
printf 'Backup created and archive-validated: %s\n' "$FINAL"
printf 'SHA-256: '
cut -d ' ' -f 1 "$FINAL.sha256"
