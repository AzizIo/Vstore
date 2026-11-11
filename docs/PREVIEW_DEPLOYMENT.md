# Isolated preview deployment

This is an **opt-in preview stack**, separate from the local-development stack in `docker-compose.yml`.

It is designed for a demo on a VPS behind an existing HTTPS reverse proxy or tunnel:

- The frontend is built once with Vite and served as static files by Nginx. The Vite development server is not exposed.
- Nginx proxies `/api/*` to FastAPI on the private Compose network. The API port is not published on the host.
- PostgreSQL and Redis are private to the Compose network and have no published host ports.
- Only Nginx is published, and only on `127.0.0.1` (default port `8080`).
- The preview uses a separate PostgreSQL volume named `viltara_preview_postgres_data`; it does not reuse or migrate the volume from the development Compose project.
- The optional bot runs in the same isolated preview project and shares the preview database with the API.

This is a safer preview baseline, not a substitute for a production security review, backups, monitoring, rate limiting, and a managed TLS/reverse-proxy configuration.

## 1. Configure environment

From the repository root, first check whether `.env` already exists:

```bash
test -f .env || cp .env.example .env
```

**Do not run `cp .env.example .env` over an existing file.** On an existing VPS, keep the current `.env` intact and add only the preview-specific variables listed below. The preview Compose file uses separate `PREVIEW_*` credentials and URLs and maps them to the normal environment variables only inside preview containers; the existing development stack's `.env` values remain untouched.

Generate values locally; do not paste secrets into chat or commit `.env`:

```bash
openssl rand -hex 32
```

Use one generated value for `PREVIEW_AUTH_SECRET_KEY` and a different generated value for `PREVIEW_DB_PASSWORD`. The preview database password must be URL-safe; a 64-character hexadecimal value from the command above is suitable.

Set these values in the root `.env`:

```dotenv
PREVIEW_AUTH_SECRET_KEY=<fresh-64-hex-character-secret>
PREVIEW_BOT_TOKEN=<BotFather-token-for-preview-bot>
PREVIEW_DB_PASSWORD=<different-64-hex-character-secret>
PREVIEW_HTTP_PORT=8080

PREVIEW_TELEGRAM_MINI_APP_URL=https://t.me/<preview_bot_username>/<app_short_name>

PREVIEW_VITE_TONCONNECT_APP_URL=https://<stable-public-mini-app-host>
PREVIEW_VITE_TONCONNECT_MANIFEST_URL=https://<stable-public-mini-app-host>/tonconnect-manifest.json
PREVIEW_TON_CONNECT_ALLOWED_DOMAINS=["<stable-public-mini-app-host>"]
PREVIEW_TON_CONNECT_NETWORK=testnet
PREVIEW_TON_CENTER_API_KEY=<optional-preview-provider-api-key>
```

Use a stable hostname that will remain the same across rebuilds. Configure that exact hostname for the preview bot's Mini App in @BotFather. The hostname in `PREVIEW_TON_CONNECT_ALLOWED_DOMAINS` must be exact: no scheme, port, path, or trailing slash. The preview stack maps these preview-specific values to the API's `TON_CONNECT_ALLOWED_DOMAINS`, `TON_CONNECT_NETWORK`, `TON_CENTER_API_KEY`, and TON Center provider URLs; it does not inherit the existing dev stack's TON domain/network or provider API key. If no preview API key is supplied, the preview uses the provider's unauthenticated rate limits. `PREVIEW_TON_CONNECT_NETWORK` defaults to `testnet`; use a disposable test wallet and testnet provider for the preview. Only switch the preview to mainnet deliberately and with a separately reviewed plan. The two `VITE_TONCONNECT_*` values are build-time inputs for the static frontend, so changing them requires rebuilding the `miniapp` image.

The Mini App URL above is the HTTPS website origin used by TON Connect. `PREVIEW_TELEGRAM_MINI_APP_URL` is a different value: the Telegram direct link for the preview bot configured in @BotFather.

The preview Compose file maps these `PREVIEW_*` values into the API's normal `AUTH_SECRET_KEY`, `BOT_TOKEN`, `TELEGRAM_MINI_APP_URL` and `VITE_TONCONNECT_*` settings **inside preview containers only**. The existing development stack's `.env` values are not changed. Use a fresh `PREVIEW_AUTH_SECRET_KEY` (at least 32 characters) so tokens from the existing stack are not accepted in preview. The preview API requires `PREVIEW_BOT_TOKEN` to verify Telegram `initData`, even when the separate preview bot container is not started. It also requires a fresh `PREVIEW_AUTH_SECRET_KEY` so preview JWTs are isolated from the existing development stack.

Use a dedicated BotFather preview bot and configure its Mini App domain/menu URL to the stable preview host. If you deliberately reuse the existing bot token, never run a second polling process for it: two polling bot containers with the same token conflict. The preview outbox is stored in preview PostgreSQL, so preview notifications are delivered only when a worker connected to that same preview database is running.

## 2. Where preview data goes

| Data | Destination | Persistence / behavior |
|---|---|---|
| Telegram users, wallets, NFT inventory, listings, orders, order events and notification outbox | PostgreSQL service `db`, database `viltara_preview` | Durable in named volume `viltara_preview_postgres_data`. API and optional preview bot use the same database URL. |
| TON Connect proof challenges and inventory-sync locks | Preview Redis service | Temporary keys only. Redis has no persistent volume; challenges expire and locks are recoverable. It is not the source of truth for users, listings or orders. |
| Mini App HTML, JS, CSS, manifest and icon | Static files baked into the `miniapp` image and served by Nginx | Replaced when the image is rebuilt; not stored in PostgreSQL. |
| API requests from the browser | Same-origin `/api/*` path → Nginx → FastAPI service `api:8000` | No separate public API hostname or frontend API URL is needed. |
| Telegram notifications | Outbox rows in preview PostgreSQL → optional bot worker → Telegram Bot API | Rows remain in the preview DB until the worker delivers/retries them. The worker must use this preview DB. |

**The preview starts with a new, empty database.** It will not display records from the existing development database or any live database. This is intentional isolation: the existing Compose database volume is not mounted, imported, migrated or written by the preview stack. Do not point the preview `DATABASE_URL` at the existing database to make old listings appear. If existing demo records are needed, create fresh test listings in the preview or plan a separate reviewed export/import from a backup.

## 3. Start the isolated stack

Start only its database and cache first:

```bash
docker compose -f docker-compose.preview.yml up -d db redis
```

Apply migrations to the **preview database only** by using the API image as a one-off migration container:

```bash
docker compose -f docker-compose.preview.yml run --rm --build api alembic upgrade head
```

Then start the API and static Mini App:

```bash
docker compose -f docker-compose.preview.yml up -d --build api miniapp
```

Start the optional bot/outbox worker only after configuring the BotFather values:

```bash
docker compose -f docker-compose.preview.yml --profile bot up -d --build bot
```

Inspect status:

```bash
docker compose -f docker-compose.preview.yml ps
docker compose -f docker-compose.preview.yml logs --tail=100 api miniapp
```

The only host listener created by this stack is `127.0.0.1:8080` (or the configured `PREVIEW_HTTP_PORT`). Configure the existing HTTPS reverse proxy/tunnel to forward to that loopback address. Do not publish the API, PostgreSQL, or Redis ports. Do not expose port 8080 directly to the public internet; terminate HTTPS at the trusted proxy.

## 4. Run public preflight

From a laptop or another machine outside the VPS, run the [read-only Demo Preflight](DEMO_PREFLIGHT.md) against the public HTTPS host. Because Nginx serves both the Mini App and the `/api` proxy on one origin, pass the same origin twice:

```bash
python backend/scripts/demo_preflight.py \
  --api-url https://<stable-public-mini-app-host> \
  --mini-app-url https://<stable-public-mini-app-host>
```

All five checks must pass before demonstrating the wallet UI. The additional TON Connect proof-configuration check verifies that the preview API has a valid domain allowlist and network; a valid public manifest alone is not sufficient. Then complete the actual Telegram/Tonkeeper steps in [TON Connect setup](TON_CONNECT_SETUP.md). Public reachability and a valid manifest do not prove a wallet proof succeeded.

## 5. Safety boundaries

- This Compose project is isolated by its explicit project name and its own named database volume. It does not alter the existing `docker-compose.yml` project or its `postgres_data` volume.
- The preview starts with a fresh database. It does not import existing user/listing data.
- Never point `DATABASE_URL` at a production/shared database. The preview Compose file overrides it to the private `viltara_preview` service.
- The bot is optional and isolated under the `bot` profile.
- Do not run `docker compose down -v`; that command can delete persistent database volumes.
- Do not put private keys or seed phrases into environment variables. The app must never request or store them.
- Reservations are not payments. This preview does not implement checkout, escrow, or post-reservation NFT delivery confirmation.

The current development Compose file remains available for local work. Use this separate file only when you intentionally need the isolated static preview stack.
