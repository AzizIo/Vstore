# Controlled MVP preview demo runbook

This runbook is for a **separate, disposable Preview environment**. It does not describe a production deployment. The Preview stack has its own PostgreSQL volume and Redis service and must not reuse the development or production database.

## 1. Prepare the Preview environment

Run commands from the repository root. Create .env only when it does not already exist:

\`\`\`bash
test -f .env || cp .env.example .env
\`\`\`

If .env already exists, keep it intact and add the Preview variables below. Never overwrite it with cp .env.example .env.

Generate two different URL-safe secrets locally:

\`\`\`bash
openssl rand -hex 32
openssl rand -hex 32
\`\`\`

Put the values into PREVIEW_AUTH_SECRET_KEY and PREVIEW_DB_PASSWORD. Do not paste them into chat, commit them, or print the contents of .env.

Configure these Preview-only values in .env:

\`\`\`dotenv
PREVIEW_AUTH_SECRET_KEY=<fresh-64-character-hex-secret>
PREVIEW_DB_PASSWORD=<different-fresh-64-character-hex-password>
PREVIEW_HTTP_PORT=8080

PREVIEW_BOT_TOKEN=<dedicated-preview-bot-token>
PREVIEW_TELEGRAM_MINI_APP_URL=https://<stable-public-mini-app-host>
PREVIEW_TELEGRAM_MINI_APP_DIRECT_LINK=https://t.me/<preview_bot_username>/<app_short_name>

PREVIEW_VITE_TONCONNECT_APP_URL=https://<stable-public-mini-app-host>
PREVIEW_VITE_TONCONNECT_MANIFEST_URL=https://<stable-public-mini-app-host>/tonconnect-manifest.json
PREVIEW_TON_CONNECT_ALLOWED_DOMAINS=["<stable-public-mini-app-host>"]
PREVIEW_TON_CONNECT_NETWORK=testnet
\`\`\`

The host in all three URL settings must be the same stable public HTTPS Mini App host:

- PREVIEW_VITE_TONCONNECT_APP_URL is baked into the frontend TON Connect manifest.
- PREVIEW_TELEGRAM_MINI_APP_URL is used by the bot's inline Web App launch button.
- PREVIEW_TELEGRAM_MINI_APP_DIRECT_LINK is an optional Telegram t.me/<bot>/<app> link used for order-specific notification links. It is not a website URL.

The TON proof allowlist is a JSON array containing the hostname only: no scheme, port, path, or trailing slash. Keep PREVIEW_TON_CONNECT_NETWORK=testnet and use a disposable testnet wallet and TEP-62 test NFT. Do not switch to mainnet for a Preview walkthrough.

Use a dedicated BotFather bot. PREVIEW_BOT_TOKEN is required by the API to verify Telegram initData, even when the separate bot container is not running. Start the optional polling bot only once for that token; two polling processes using the same Telegram bot token conflict. Users must open the bot at least once before Telegram will allow it to send them messages.

The PREVIEW_* values are deliberately separate from the development stack's normal BOT_TOKEN, AUTH_SECRET_KEY, DATABASE_URL, REDIS_URL, and TON settings. Do not copy production secrets into Preview.

## 2. Start the isolated stack and migrate its database

Start only the Preview database and cache:

\`\`\`bash
docker compose -f docker-compose.preview.yml up -d db redis
\`\`\`

Apply migrations through a one-off container that uses the Preview service configuration:

\`\`\`bash
docker compose -f docker-compose.preview.yml run --rm --build api alembic upgrade head
\`\`\`

Start the API and static Mini App:

\`\`\`bash
docker compose -f docker-compose.preview.yml up -d --build api miniapp
\`\`\`

Start the optional bot/outbox worker only after checking the token and Mini App settings:

\`\`\`bash
docker compose -f docker-compose.preview.yml --profile bot up -d --build bot
\`\`\`

The Mini App is published only on 127.0.0.1:8080 by default. Configure the existing HTTPS reverse proxy or tunnel to forward to that loopback listener. Do not publish the API, PostgreSQL, or Redis ports and do not expose port 8080 directly to the internet.

## 3. Verify service health and public endpoints

On the host, inspect the Preview services and application logs:

\`\`\`bash
docker compose -f docker-compose.preview.yml ps
docker compose -f docker-compose.preview.yml logs --tail=100 api miniapp
curl -fsS http://127.0.0.1:8080/api/health/ready
\`\`\`

When the optional bot is enabled:

\`\`\`bash
docker compose -f docker-compose.preview.yml logs --tail=100 bot
\`\`\`

From a separate laptop or workstation with access to the public HTTPS hostname, run the read-only preflight:

\`\`\`bash
python backend/scripts/demo_preflight.py \
  --api-url https://<stable-public-mini-app-host> \
  --mini-app-url https://<stable-public-mini-app-host>
\`\`\`

The API and Mini App URLs are the same origin for this Preview stack because Nginx proxies /api/* to FastAPI. Require **5/5 checks to pass** before demonstrating wallet linking:

1. API readiness: PostgreSQL, Redis and Telegram authentication configuration.
2. TON Connect proof configuration: supported network and a valid backend allowlist containing the exact public Mini App hostname.
3. Mini App entry page: HTTP 200 HTML from the expected origin.
4. TON Connect manifest: HTTP 200 JSON, correct app/icon URLs and cross-origin GET access.
5. TON Connect icon: HTTP 200 PNG with a valid PNG signature.

A successful preflight verifies public reachability and configuration only. It does not prove that Telegram opened the Mini App, a real Tonkeeper proof succeeded, listing/order actions worked, bot notifications were delivered, or an NFT was transferred. Complete the live wallet acceptance steps in TON_CONNECT_SETUP.md.

## 4. Rehearse the supported marketplace journey

Use two dedicated Telegram test accounts, a disposable testnet wallet for the seller, and a real TEP-62 testnet NFT that the configured TON Center provider can verify.

1. Start the dedicated Preview bot and send it /start from both Telegram test accounts. Confirm the **Открыть VILTARA SHOP** button opens the Preview hostname.
2. Open the Mini App as the seller. Complete Telegram authentication.
3. Connect the seller's testnet wallet and complete **Connect & verify**. Confirm the backend marks the wallet verified; a visible wallet address by itself is not proof.
4. Sync the seller's NFT inventory. Confirm the chosen test NFT appears as backend-verified and is eligible for listing.
5. Create a priced listing and publish it. Publishing performs a fresh ownership check; a manually inserted listing or client-supplied NFT record is not a safe substitute.
6. Open the Mini App as the second Telegram account. Find the public listing and reserve it.
7. Open the buyer's orders and confirm the UI says **Reservation pending**. The seller should also see the reservation in their orders.
8. When the optional bot worker is running and both users have started the bot, check that the order notification outbox is processed and Telegram notifications are received.

### Demo data and safety

There is intentionally **no Preview seed that creates verified users, wallets, or NFT ownership records**. The backend's inventory and publish flows depend on actual on-chain ownership checks. Fabricating a verified wallet or inventory row would bypass the security boundary and make the demo misleading.

The API-backed Playwright seed is for an isolated disposable CI database and a local deterministic TON provider fixture only. Do not run CI seed scripts against Preview, development, or production databases. For a live Preview walkthrough, create test accounts through Telegram and use a genuine testnet wallet/NFT.

If a suitable testnet NFT is not available or the TON provider cannot verify it, limit the walkthrough to the public catalogue and already-supported screens. Do not claim the seller-publish journey is live-tested.

## 5. Current MVP boundaries

- Creating an order reserves a listing; it does not collect payment.
- There is no checkout, Telegram Stars payment, escrow, custody, refund, commission, or seller payout flow.
- The seller-to-buyer NFT transfer is not automated by VILTARA.
- Independent on-chain delivery observation and the order completed transition are not implemented.
- A public preflight pass is not a substitute for live Telegram/Tonkeeper acceptance.

Never request or store a seed phrase or private key. Wallet proof is a signature challenge; it is not a payment or an NFT transfer.

## 6. Stop the Preview safely

Stop the Preview containers without deleting the named PostgreSQL volume:

\`\`\`bash
docker compose -f docker-compose.preview.yml --profile bot stop
\`\`\`

The database volume is retained. Do not run docker compose down -v; it deletes named volumes. The normal development Compose project remains separate.
