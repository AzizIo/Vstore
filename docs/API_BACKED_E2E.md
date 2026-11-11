# API-backed Playwright E2E

The repository keeps two distinct browser-test layers:

- `npm run test:e2e` exercises UI behavior with mocked API responses.
- `npm run test:e2e:api` exercises the real React app, FastAPI routes, PostgreSQL and Redis in an isolated environment.

## What the API-backed journey covers

The Playwright browser signs Telegram `initData` with the same HMAC-SHA-256 algorithm used by the backend. FastAPI validates the signature and issues ordinary bearer sessions; there is no test-only authentication bypass.

A seeded seller has a database-backed verified wallet and NFT record. A loopback TON Center v3 fixture returns that exact NFT and owner, so the normal inventory, draft-creation, publish and buyer-reservation checks execute without contacting a public chain provider. A second browser context authenticates a buyer and creates a real order through the API.

After Playwright exits, a database assertion checks that PostgreSQL contains the published/reserved listing, the buyer's order with its exact price/currency snapshot, the order event and both pending notification-outbox rows.

## CI isolation

The `api-backed-e2e` job provisions disposable PostgreSQL 16 and Redis 7 services. It applies the repository's Alembic migrations to the database named `viltara_e2e`, starts FastAPI and the local TON provider on loopback, then starts Vite with its API proxy pointed at that FastAPI process.

The seed and assertion scripts refuse to run unless all of the following are true:

- `ENVIRONMENT=test`
- database hostname is `localhost` or `127.0.0.1`
- database name is exactly `viltara_e2e`

The CI `BOT_TOKEN` and `AUTH_SECRET_KEY` are non-production test values. The bot token is used only to calculate the Telegram initData signature; the job never calls Telegram. No real wallet, real TON provider, production DB, VPS, or deploy is involved.

## Local execution

Use a disposable local PostgreSQL database named `viltara_e2e` and a local Redis instance. Never point these scripts at a shared or production database.

From the repository root, set the same test-only environment variables used by the workflow:

```sh
export ENVIRONMENT=test
export DATABASE_URL=postgresql+asyncpg://viltara:viltara_e2e@127.0.0.1:5432/viltara_e2e
export REDIS_URL=redis://127.0.0.1:6379/0
export BOT_TOKEN=e2e-only-not-a-real-telegram-bot-token
export AUTH_SECRET_KEY=e2e-only-secret-never-use-outside-disposable-ci-database-123456789
export TON_CONNECT_NETWORK=mainnet
export TON_CONNECT_ALLOWED_DOMAINS='["viltara-e2e.example"]'
export TON_CENTER_MAINNET_BASE_URL=http://127.0.0.1:8999/api/v3
export VITE_API_PROXY_TARGET=http://127.0.0.1:8000
```

Then run the following in separate terminals:

```sh
cd backend
python -m pip install -e ".[dev]"
python -m alembic upgrade head
python -m scripts.e2e_ton_provider
```

```sh
cd backend
python -m scripts.seed_api_backed_e2e
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```sh
cd frontend
npm install
npx playwright install chromium
npm run test:e2e:api
```

After a successful journey, verify the persisted database result:

```sh
cd backend
python -m scripts.assert_api_backed_e2e
```

The Playwright test deliberately stops at reservation. NFT transfer preparation, chain observation and the `completed` transition are not implemented by this suite; those remain separate Issue #46 work.
