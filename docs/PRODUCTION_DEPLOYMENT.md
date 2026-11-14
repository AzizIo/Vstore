# Production deployment baseline

This is an opt-in production Compose stack. It is separate from the development
stack in `docker-compose.yml` and the isolated testnet Preview stack in
`docker-compose.preview.yml`.

It deliberately:
- serves the compiled React app from Nginx, not the Vite development server;
- keeps FastAPI, PostgreSQL and Redis private to the Compose network;
- publishes only the Mini App listener on host loopback (default 127.0.0.1:8081);
- requires the exact PostgreSQL Docker volume to be selected explicitly;
- requires explicit TON network, Mini App origin, proof-domain and CORS settings;
- does not run migrations automatically on application startup;
- starts the Telegram bot/outbox worker only through the optional `bot` profile.

This is a deployment baseline, not proof that the current VPS is ready. It does
not configure TLS, a reverse proxy, backups, monitoring, firewall rules or
provider quotas. Do not point it at an existing database volume until that
volume and its backup have been identified.

## 1. Inspect the existing server before changing anything

On the VPS, from the existing repository directory:

```bash
docker compose ps
docker volume ls
docker inspect <current-postgres-container> --format '{{json .Mounts}}'
```

Identify the exact named volume mounted at `/var/lib/postgresql/data`. Check the
PostgreSQL major version and take a verified backup before any upgrade or
container replacement. Do not attach one PostgreSQL data directory to two
running PostgreSQL containers.

For the safest first production cutover, create a **new dedicated production
volume** and restore a database dump into it rather than reusing the development
volume. This keeps development and production data stores isolated:

```bash
docker volume create viltara_production_postgres_data
```

Set `PROD_POSTGRES_VOLUME_NAME=viltara_production_postgres_data`.
The Compose file requires the volume to exist and will not silently create one.
Keep the old stack and its volume untouched until the new database has been
restored, validated and the reverse-proxy cutover is approved.

## 2. Configure production-only variables

Keep the existing `.env` file. Do not overwrite it with `.env.example`.
Generate two different URL-safe secrets locally:

```bash
openssl rand -hex 32
openssl rand -hex 32
```

Append production-specific variables to `.env`. Never paste secret values into
chat, shell history, Git commits or screenshots.

```dotenv
PROD_DB_NAME=viltara_production
PROD_DB_USER=viltara_production
PROD_DB_PASSWORD=<first-64-hex-secret>
PROD_AUTH_SECRET_KEY=<different-64-hex-secret>
PROD_BOT_TOKEN=<production-BotFather-token>

PROD_TELEGRAM_MINI_APP_URL=https://<public-mini-app-host>
PROD_TELEGRAM_MINI_APP_DIRECT_LINK=https://t.me/<bot_username>/<app_short_name>

PROD_VITE_TONCONNECT_APP_URL=https://<public-mini-app-host>
PROD_VITE_TONCONNECT_MANIFEST_URL=https://<public-mini-app-host>/tonconnect-manifest.json
PROD_TON_CONNECT_ALLOWED_DOMAINS=["<public-mini-app-host>"]
PROD_CORS_ALLOWED_ORIGINS=["https://<public-mini-app-host>"]
PROD_TON_CONNECT_NETWORK=mainnet
PROD_ADMIN_TELEGRAM_IDS=["<numeric-telegram-user-id>"]

PROD_POSTGRES_VOLUME_NAME=<exact-existing-or-new-volume-name>
PROD_HTTP_PORT=8081
PROD_TON_CENTER_API_KEY=<optional-provider-api-key>
```

The DB password must be URL-safe; a 64-character hexadecimal value is suitable.
The Telegram ID list must be a JSON array of numeric IDs. An empty list disables
admin access. The TON proof allowlist contains the hostname only (no scheme,
port, path or trailing slash). CORS contains the exact HTTPS origin. The
Mini App URL and Vite app URL must be the same public HTTPS origin; the manifest
URL must be that origin plus `/tonconnect-manifest.json`.

Set `PROD_TON_CONNECT_NETWORK` deliberately. Use `mainnet` only for the real
marketplace and real TON NFTs. Use `testnet` only with a separate test bot,
test domain, test credentials and disposable test data. Do not expose a
testnet Preview as the production marketplace.

The API readiness endpoint requires a configured Telegram bot token and an
authentication secret of at least 32 characters, even when the polling bot
worker is not started. The `bot` service uses the same production token and
database; start only one polling process for that token.

## 3. Validate Compose without starting services

After the variables are configured:

```bash
docker compose -f docker-compose.production.yml config -q
```

This checks Compose interpolation and syntax without starting containers or
touching the database. If it fails, fix the missing or malformed variables;
do not substitute development credentials.

## 4. Back up, migrate, and start

Take a database backup before changing images or schema. For an existing
installation, create a dump from the old database and copy it off the VPS:

```bash
docker compose exec -T db pg_dump -U <old-db-user> -d <old-db-name> -Fc \
  > /root/backups/viltara-before-production.dump
test -s /root/backups/viltara-before-production.dump
```

Start the new production database on the dedicated empty volume, then restore
the dump into it. Do not mount the old database volume into this stack while
the old PostgreSQL container is running. Confirm that the source dump is
compatible with PostgreSQL 17 before restoring.

Start only dependencies:

```bash
docker compose -f docker-compose.production.yml up -d db redis
```

For a migration from an existing database, restore the previously created
custom-format dump into the new production database before applying migrations:

```bash
docker compose -f docker-compose.production.yml exec -T db sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' \
  < /root/backups/viltara-before-production.dump
```

Run this restore only against the new, dedicated production database. Verify
users, listings, orders and the current Alembic revision before proceeding.
Do not use `--clean` against the old/live database.

Apply migrations explicitly as a one-off API container:

```bash
docker compose -f docker-compose.production.yml run --rm api alembic upgrade head
```

Then build and start the API and static Mini App:

```bash
docker compose -f docker-compose.production.yml up -d --build api miniapp
```

Start the Telegram notification worker only after checking the bot token and
Mini App links:

```bash
docker compose -f docker-compose.production.yml --profile bot up -d --build bot
```

Do not start the development Compose stack against this database. Do not run
migrations against production from a test container or a Preview stack.

## 5. HTTPS reverse proxy and public checks

The Mini App listener is bound to `127.0.0.1:8081` by default. Configure the
existing HTTPS reverse proxy to forward the public host to that loopback port.
Preserve the original `Host` and `X-Forwarded-Proto: https` headers. Keep
PostgreSQL, Redis and FastAPI ports unpublished; do not expose port 8081
directly to the internet.

Check the containers and readiness:

```bash
docker compose -f docker-compose.production.yml ps
docker compose -f docker-compose.production.yml logs --tail=100 api miniapp
curl -fsS http://127.0.0.1:8081/api/health/ready
```

From a machine outside the VPS, run the public read-only preflight:

```bash
python backend/scripts/demo_preflight.py \
  --api-url https://<public-mini-app-host> \
  --mini-app-url https://<public-mini-app-host>
```

Require all five checks to pass before demonstrating TON wallet linking:
API readiness, TON Connect proof configuration, Mini App HTML, manifest JSON
and icon PNG. This check does not prove Telegram launch, a live wallet proof,
bot notification delivery or NFT transfer.

Complete the actual Telegram/Tonkeeper acceptance checklist in
[TON Connect setup](TON_CONNECT_SETUP.md). For an initial public Beta, do not
advertise payments, escrow, refunds or buyer guarantees: they are not part of
the current marketplace implementation. Live testnet acceptance for direct NFT
delivery remains a separate gate before describing that flow as tested.

## 6. Backups and rollback

The Compose stack does not create backups. Schedule encrypted off-host backups
and test restoration to a separate database before launch. A sample manual
PostgreSQL dump (run from the repository directory) is:

```bash
mkdir -p /root/backups
backup_file="/root/backups/viltara-production-$(date +%F-%H%M%S).dump"
docker compose -f docker-compose.production.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_file"
test -s "$backup_file"
```

The non-empty check confirms the exact dump file was written; inspect its size
and copy it off-host. Do not treat a backup as verified until a restore has
succeeded against a separate database.

Keep the previous application image available for rollback. A schema migration
may not be safely reversible by rolling back only the container image. Review
the Alembic revision and its downgrade behavior before applying any new
migration, and restore from the verified backup only under an explicit
recovery plan.

## 7. Operational limits

Before calling this a stable production release, separately arrange:
- monitored off-host database backups and restore drills;
- HTTPS certificate renewal and reverse-proxy hardening;
- resource/disk monitoring and log retention;
- an incident/support contact and rollback procedure;
- rate limiting/WAF at the public edge;
- live Telegram, wallet proof and NFT transfer acceptance.

No VPS, production database, live bot token or user data is modified by adding
this Compose file and runbook to the repository.
