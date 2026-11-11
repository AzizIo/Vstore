# Isolated preview deployment

This is an **opt-in preview stack**, separate from the local-development stack in `docker-compose.yml`.

It is designed for a demo on a VPS behind an existing HTTPS reverse proxy or tunnel:

- The frontend is built once with Vite and served as static files by Nginx. The Vite development server is not exposed.
- Nginx proxies `/api/*` to FastAPI on the private Compose network. The API port is not published on the host.
- PostgreSQL and Redis are private to the Compose network and have no published host ports.
- Only Nginx is published, and only on `127.0.0.1` (default port `8080`).
- The preview uses a separate PostgreSQL volume named `viltara_preview_postgres_data`; it does not reuse or migrate the volume from the development Compose project.
- The optional bot runs in the same isolated preview project and uses its own preview database.

This is a safer preview baseline, not a substitute for a production security review, backups, monitoring, rate limiting, and a managed TLS/reverse-proxy configuration.

## 1. Configure environment

From the repository root:

```bash
cp .env.example .env
```

Generate values locally; do not paste secrets into chat or commit `.env`:

```bash
openssl rand -hex 32
```

Use one generated value for `AUTH_SECRET_KEY` and another for `PREVIEW_DB_PASSWORD`. The preview database password must be URL-safe; a 64-character hexadecimal value from the command above is suitable.

Set these values in the root `.env`:

```dotenv
ENVIRONMENT=production
AUTH_SECRET_KEY=<64-hex-character-secret>
PREVIEW_DB_PASSWORD=<different-64-hex-character-secret>
PREVIEW_HTTP_PORT=8080

BOT_TOKEN=<BotFather-token>
TELEGRAM_MINI_APP_URL=https://t.me/<bot_username>/<app_short_name>

VITE_TONCONNECT_APP_URL=https://<stable-public-mini-app-host>
VITE_TONCONNECT_MANIFEST_URL=https://<stable-public-mini-app-host>/tonconnect-manifest.json
TON_CONNECT_ALLOWED_DOMAINS=["<stable-public-mini-app-host>"]
TON_CONNECT_NETWORK=testnet
```

Use a stable hostname that will remain the same across rebuilds. The hostname in `TON_CONNECT_ALLOWED_DOMAINS` must be exact: no scheme, port, path, or trailing slash. Use `mainnet` only when deliberately testing with a mainnet wallet/provider; for a preview, prefer a disposable test wallet on testnet. TON Connect variables are build-time inputs for the static frontend, so changing them requires rebuilding the `miniapp` image.

The Mini App URL above is the HTTPS website origin used by TON Connect. `TELEGRAM_MINI_APP_URL` is a different value: the Telegram direct link configured in @BotFather.

The API requires `BOT_TOKEN` to verify Telegram `initData`, even when the separate bot container is not started. `TELEGRAM_MINI_APP_URL` is only needed when the bot menu and notification messages should include the configured Mini App direct link. Leave the bot profile off unless you specifically want polling and notification delivery in this preview.

## 2. Start the isolated stack

Start only its database and cache first:

```bash
docker compose -f docker-compose.preview.yml up -d db redis
```

Apply migrations to the **preview database only** by using the API image as a one-off migration container:

```bash
docker compose -f docker-compose.preview.yml run --rm api alembic upgrade head
```

Then start the API and static Mini App:

```bash
docker compose -f docker-compose.preview.yml up -d api miniapp
```

Start the optional bot/outbox worker only after configuring the BotFather values:

```bash
docker compose -f docker-compose.preview.yml --profile bot up -d bot
```

Inspect status:

```bash
docker compose -f docker-compose.preview.yml ps
docker compose -f docker-compose.preview.yml logs --tail=100 api miniapp
```

The only host listener created by this stack is `127.0.0.1:8080` (or the configured `PREVIEW_HTTP_PORT`). Configure the existing HTTPS reverse proxy/tunnel to forward to that loopback address. Do not publish the API, PostgreSQL, or Redis ports. Do not expose port 8080 directly to the public internet; terminate HTTPS at the trusted proxy.

## 3. Run public preflight

From a laptop or another machine outside the VPS, run the [read-only Demo Preflight](DEMO_PREFLIGHT.md) against the public HTTPS host. Because Nginx serves both the Mini App and the `/api` proxy on one origin, pass the same origin twice:

```bash
python backend/scripts/demo_preflight.py \
  --api-url https://<stable-public-mini-app-host> \
  --mini-app-url https://<stable-public-mini-app-host>
```

All four checks must pass before demonstrating the wallet UI. Then complete the actual Telegram/Tonkeeper steps in [TON Connect setup](TON_CONNECT_SETUP.md). Public reachability and a valid manifest do not prove a wallet proof succeeded.

## 4. Safety boundaries

- This Compose project is isolated by its explicit project name and its own named database volume. It does not alter the existing `docker-compose.yml` project or its `postgres_data` volume.
- The preview starts with a fresh database. It does not import existing user/listing data.
- Never point `DATABASE_URL` at a production/shared database. The preview Compose file overrides it to the private `viltara_preview` service.
- The bot is optional and isolated under the `bot` profile.
- Do not run `docker compose down -v`; that command can delete persistent database volumes.
- Do not put private keys or seed phrases into environment variables. The app must never request or store them.
- Reservations are not payments. This preview does not implement checkout, escrow, or post-reservation NFT delivery confirmation.

The current development Compose file remains available for local work. Use this separate file only when you intentionally need the isolated static preview stack.
