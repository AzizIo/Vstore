# VILTARA SHOP — Agent Onboarding

> Read this file before changing code. It is a navigation guide and collaboration contract, not a replacement for inspecting the exact files involved in your task.
> Last checked: 2026-11-10. The repository changes continuously; verify the current branch, open PRs, and file contents before relying on status notes below.
> **Product model and stage boundaries:** read `docs/PRODUCT_MODEL.md` first — prices are a mandatory part of listings; reservation is not payment; payment/escrow must not be imitated.

## 1. What this project is

**VILTARA SHOP** is a Telegram bot + Telegram Mini App marketplace for buying and selling verifiable Telegram digital gifts and TON NFTs.

The intended product includes:
- a public NFT/gift catalog and listing details;
- seller profiles and listing management;
- asset verification and ownership checks;
- purchase orders and deal lifecycle;
- buyer/seller communication and notifications;
- admin tools, disputes, fees and audit history;
- payment and escrow flows, but only after the technical and policy constraints are solved.

The product is **not yet a complete marketplace**. The repository currently contains an early modular-monolith backend, a minimal frontend shell, database migrations/models, authentication and listing endpoints, and automated tests. Do not describe planned features as implemented.

## 2. Repository map — where to look first

```text
/
├── README.md                    # Product brief, stack, architecture decisions, runbook
├── AGENTS.md                    # This onboarding guide
├── .env.example                 # Local environment variable template (no real secrets)
├── docker-compose.yml           # PostgreSQL, Redis, API, Mini App, optional bot
├── .github/workflows/
│   ├── backend.yml              # Backend lint + tests; PostgreSQL service in CI
│   └── frontend.yml             # Frontend tests/build
├── docs/
│   └── ASSET_INTEGRATION_AUDIT.md # Telegram Gifts / TON NFT / transfer constraints audit
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, middleware and router registration
│   │   ├── bot.py               # aiogram bot entrypoint (currently minimal)
│   │   ├── api/
│   │   │   ├── auth.py          # POST /api/auth/telegram
│   │   │   ├── health.py        # Health/readiness endpoints
│   │   │   ├── users.py         # Current-user endpoint
│   │   │   └── listings.py      # Public catalog, details, seller listings, draft creation
│   │   ├── auth/
│   │   │   ├── telegram.py      # Telegram Mini App initData HMAC verification
│   │   │   ├── tokens.py        # API JWT creation/verification helpers
│   │   │   ├── dependencies.py  # Bearer auth/current-user dependencies
│   │   │   └── schemas.py       # Auth request/response schemas
│   │   ├── core/
│   │   │   └── config.py        # pydantic-settings configuration
│   │   └── db/
│   │       ├── models.py        # SQLAlchemy models, enums and constraints
│   │       └── session.py       # Async engine, session factory and dependency
│   ├── migrations/
│   │   ├── env.py               # Alembic async migration environment
│   │   └── versions/             # Versioned DB schema changes (0001–0004)
│   ├── tests/                    # Backend unit/API/PostgreSQL integration tests
│   ├── alembic.ini
│   ├── pyproject.toml             # Python dependencies, Ruff, pytest and mypy config
│   └── Dockerfile
└── frontend/
    ├── src/
    │   ├── App.tsx              # Marketplace app: catalog, listing detail, navigation
    │   ├── main.tsx             # React entrypoint
    │   ├── index.css            # Global styles
    │   ├── api/                 # Typed API clients (listings, orders, assets, config)
    │   ├── auth/                # SessionProvider, Telegram initData helpers, auth API
    │   ├── listings/            # CreateListing, MyListings (create/edit/unpublish)
    │   ├── orders/              # Orders (buyer/seller order list and cancel)
    │   ├── wallet/              # TON Connect wallet connection UI
    │   └── test/                # Vitest setup and frontend tests
    ├── package.json             # Frontend scripts and dependencies
    ├── vite.config.ts
    └── Dockerfile
```

**Navigation rule:** start in the relevant router/component, then follow imports into schemas, models, dependencies and tests. Do not scan the whole repository when the task points to one feature.

## 3. Current architecture and data flow

### Backend

- Python 3.13+, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic and PostgreSQL.
- aiogram 3 is included for the Telegram bot. Redis is provisioned in Compose.
- Architecture is a **modular monolith**. Keep domain boundaries clear; do not introduce microservices without an explicit architectural decision.
- API routers are mounted under `/api` in `backend/app/main.py`.
- Configuration is loaded by `backend/app/core/config.py` from environment variables / root `.env`.
- Database sessions are created by `backend/app/db/session.py`. Use the existing async session dependency in route handlers unless a strong reason requires otherwise.
- SQLAlchemy models and enums are in `backend/app/db/models.py`. Schema changes must be represented by Alembic migrations in `backend/migrations/versions/`; do not edit the database schema by hand.

### Frontend

- React 19 + TypeScript + Vite + Tailwind CSS v4.
- TanStack Query, Zustand and TON Connect UI are dependencies in `frontend/package.json`.
- The Mini App implements the full current product surface: public catalog with filters/sorting/pagination, listing detail, Telegram initData authentication with Bearer sessions, listing creation/edit/unpublish from verified inventory, my-listings management, and buyer/seller order lists. API clients are typed wrappers in `frontend/src/api/`.
- Still absent: payment/checkout UI, NFT delivery confirmation flow, deal chat, admin panel. Do not assume a planned screen exists; inspect `frontend/src/` first.

### Local infrastructure

- `docker-compose.yml` starts PostgreSQL 17, Redis 7, FastAPI API and the Mini App.
- The Telegram bot is behind the Compose profile `bot`; it is not started by the default `docker compose up`.
- Local service ports: API `8000`, Mini App `5173`; Swagger at `/docs`.
- Use root `.env.example` to create `.env`. Never commit `.env`, tokens, signing secrets, private keys or real user data.

## 4. Existing API contract — inspect before extending

Current API routes are registered in `backend/app/main.py`.

| Method | Endpoint | Auth | Current behavior |
|---|---|---|---|
| GET | `/api/health/live` and `/api/health/ready` | No | Health/readiness checks (PostgreSQL, Redis); see `api/health.py` |
| POST | `/api/auth/telegram` | Telegram initData | Verifies signed, short-lived Mini App initData; upserts user; returns API JWT |
| GET | `/api/users/me` | Bearer JWT | Returns current user profile |
| POST | `/api/wallets/proof/challenge` | Bearer JWT | Issues a short-lived TON Connect proof challenge |
| POST | `/api/wallets/proof/verify` | Bearer JWT | Verifies the signed proof and links the wallet |
| GET | `/api/wallets/me` | Bearer JWT | Current user's linked wallets |
| GET | `/api/assets/me` | Bearer JWT | Verified NFT inventory from the user's verified wallets (TON Center v3 + TEP-62 re-check) |
| GET | `/api/listings` | No | Public catalog; filters `asset_type`, `currency`, `search`; sort `newest`, `price_asc`, `price_desc`; pagination `limit`/`offset`; hides stale/unverified/reserved/owner-mismatch listings |
| GET | `/api/listings/me` | Bearer JWT | Current seller's listings |
| GET | `/api/listings/{listing_id}` | No | Public listing detail under the same visibility guard; otherwise 404 |
| POST | `/api/listings` | Bearer JWT | Creates a **draft only**, requiring a verified asset currently owned by the user |
| POST | `/api/listings/{listing_id}/publish` | Bearer JWT | Publishes a draft after a fresh on-chain ownership re-check (503 on provider outage) |
| PATCH | `/api/listings/{listing_id}` | Bearer JWT | Edits price/title/description of the seller's draft or active listing |
| POST | `/api/listings/{listing_id}/cancel` | Bearer JWT | Unpublishes an active listing or cancels a draft |
| POST | `/api/orders` | Bearer JWT | Reserves an active listing; requires `Idempotency-Key` header; snapshots price/currency; fresh ownership re-check before reservation |
| GET | `/api/orders` | Bearer JWT | Buyer's or seller's orders (`role` query parameter) |
| GET | `/api/orders/{order_id}` | Bearer JWT | Order detail for the buyer or seller only |
| POST | `/api/orders/{order_id}/cancel` | Bearer JWT | Buyer cancels a pending order; releases the listing |

For exact request/response fields and validation, read `backend/app/api/listings.py`, `backend/app/api/orders.py`, `backend/app/api/wallets.py`, `backend/app/api/assets.py`, `backend/app/api/auth.py`, `backend/app/auth/schemas.py` and the related tests. Do not invent endpoints, query parameters or response fields.

## 5. Database model quick map

Defined in `backend/app/db/models.py`; migrated in `backend/migrations/versions/` (0001 initial, 0002 network scoping, 0003 orders, 0004 notification outbox):

- `User`: Telegram identity and account state.
- `Wallet`: user wallet address/network and verification flags.
- `NFTCollection`: collection address/network and metadata.
- `NFTAsset`: asset type, external ID, optional item address, collection/owner, metadata and verification state.
- `Listing`: seller, asset, lifecycle status, amount/currency, title/description and expiry.
- `Order` / `OrderEvent`: reservation with a price/currency snapshot, buyer idempotency, append-only status history.
- `TelegramNotificationOutbox`: durable notification queue with attempts and leases.

Important constraints already encoded include unique Telegram IDs, unique wallet address per network, unique external asset ID per asset type and network, positive listing and order prices, foreign keys, a PostgreSQL partial unique index preventing multiple open (`active`/`reserved`) listings for the same asset, and one pending order per listing. Read the model and migrations before changing related behavior.

## 6. How to run locally

### Full stack (recommended)

From repository root:

```bash
cp .env.example .env
# Put a Telegram bot token in BOT_TOKEN when testing Telegram auth.
# Generate AUTH_SECRET_KEY with: openssl rand -hex 32
docker compose up --build
docker compose exec api alembic upgrade head
```

Services:
- Mini App: http://localhost:5173
- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- Readiness: http://localhost:8000/api/health/ready

To start the Telegram bot as well:

```bash
docker compose --profile bot up --build
```

### Backend checks

From repository root:

```bash
cd backend
python -m pip install -e ".[dev]"
ruff check app tests migrations
pytest --cov=app --cov-report=term-missing -q
```

Some PostgreSQL integration tests require a **dedicated disposable** `TEST_DATABASE_URL` and are skipped when it is absent. Never point integration tests or migration fixtures at a production/shared database. In CI, the backend workflow provisions an isolated PostgreSQL service.

### Frontend checks

```bash
cd frontend
npm install
npm run test:coverage
npm run build
```

## 7. Tests — where to add coverage

Backend tests live in `backend/tests/`:
- `test_telegram_init_data.py`: Telegram initData signature/expiry validation.
- `test_auth_tokens.py`, `test_auth_dependencies.py`, `test_auth_route.py`: JWT and auth behavior.
- `test_api_routes.py`: general API routes.
- `test_db_models.py`: model-level behavior.
- `test_listing_schemas.py`, `test_listing_routes.py`: listing validation and route behavior.
- PostgreSQL-specific integration tests may exist on an open feature/PR branch before they are merged into `main`; check PRs and current branch before assuming they are present locally.

Frontend tests are under `frontend/src/test/`; use Vitest and Testing Library.

Every behavior change should include tests at the correct layer. For DB constraints and migrations, prefer integration coverage against PostgreSQL rather than SQLite-only assumptions.

## 8. Parallel-agent collaboration rules (mandatory)

Multiple agents/developers work in this repository at the same time.

1. **Never commit directly to `main`.** Create a focused branch from the latest `main` and open a PR.
2. Before editing, inspect open PRs/issues and branch names. Fetch latest `main`; another agent may have merged or changed a shared contract.
3. Avoid editing files owned by another active task. Coordinate through the GitHub issue/PR and state exact file ownership in the task.
4. Keep PRs narrow. Do not mix frontend redesign, backend domain changes, migrations and CI refactors in one PR without a clear reason.
5. Do not force-push, reset, revert or rewrite another agent's branch. Never merge someone else's PR without explicit authorization.
6. If an API/schema contract must change, coordinate frontend and backend changes; document the contract and tests in the PR.
7. Before finishing: run relevant lint/tests/build, inspect `git diff`, ensure no secrets, and report exact branch, commit, PR and CI result.
8. If a conflict appears, fetch latest refs and reconcile intentionally. Do not overwrite another person's changes to make a test pass.

Suggested branch names:
- `feat/<area>-<short-description>`
- `fix/<area>-<short-description>`
- `test/<area>-<short-description>`
- `docs/<short-description>`

Suggested commit prefixes: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`.

## 9. Product/security guardrails

These rules are non-negotiable:

- Never trust `initDataUnsafe` or client-supplied Telegram user fields. Verify raw `Telegram.WebApp.initData` on the backend with the bot token and enforce freshness.
- Never store Telegram bot tokens, JWT signing secrets, wallet private keys or seed phrases in source control. TON Connect is non-custodial; the server must not request wallet secrets.
- Do not treat an NFT as verified because a user submitted a URL, image or metadata. Verify the item/collection and current ownership through a trusted provider/on-chain source.
- TON NFT and Telegram Gifts are different asset types with different verification/transfer capabilities. Keep them behind separate adapters.
- Do not claim escrow, automatic NFT transfer, buyer protection or seller payout is implemented until the full lifecycle is implemented and tested.
- Telegram's in-app digital goods payment rules and Telegram Gifts API permissions constrain implementation. Read `README.md` and `docs/ASSET_INTEGRATION_AUDIT.md` before implementing checkout or transfer.
- Publishing listings is intentionally disabled at present: current create endpoint only creates drafts from verified assets owned by the seller. Do not bypass this guard to make the UI look complete.
- Do not add fake marketplace listings or fake payment/transfer success states to production UI.

## 10. Project status snapshot (2026-11-10)

This is a snapshot, not a promise that every item remains current. Verify the live repository and PR list before starting work. Product model and roadmap: `docs/PRODUCT_MODEL.md`.

**Stage A — marketplace foundation (current).** Prices are a mandatory part of listings; reservation is not payment; payment/escrow are deliberately not implemented or imitated.

### Implemented on `main`

- [x] FastAPI app, configuration, CORS and health/readiness endpoints (PostgreSQL + Redis probes).
- [x] PostgreSQL async engine/session and Alembic migrations (0001–0004).
- [x] Core SQLAlchemy entities: users, wallets, NFT collections/assets, listings, orders, order events, notification outbox.
- [x] Telegram Mini App initData HMAC validation and API JWT authentication; current-user endpoint.
- [x] TON Connect wallet proof (server-side verification, wallet binding); `GET/POST /api/wallets/*`.
- [x] TEP-62 NFT verification adapter (TON Center v3) and verified inventory `GET /api/assets/me`.
- [x] Secure draft creation from verified owned assets; publication after a live ownership re-check (provider call outside DB locks, revalidation under locks).
- [x] Listing management: publish, edit price/title/description, unpublish, seller-set expiry.
- [x] Public catalog with filters, sorting (stable `price_asc`/`price_desc`/`newest`) and pagination; unpurchasable listings (stale/unverified/reserved/owner-mismatch) hidden from catalog and detail.
- [x] Orders: creation with a **price/currency snapshot at reservation time**, buyer-scoped idempotency, one open order per listing, fresh ownership re-check before reservation (fail-closed 503 on provider outage), cancellation and expiry via a `SKIP LOCKED` worker.
- [x] Telegram order notifications through a durable outbox (bot profile `bot`).
- [x] React Mini App: catalog, listing detail (collection + item address), create/edit/unpublish listings, my listings, orders.
- [x] Backend and frontend CI workflows with a PostgreSQL 16 service.

### Do not assume available

- [ ] Payment capture/refunds/payouts — `PaymentAdapter` is a protocol only; no provider.
- [ ] Escrow/guarantee, disputes, fees, seller settlement (Stage C; ADR-0001/0002).
- [ ] Server-side confirmation of NFT delivery after reservation (Stage B).
- [ ] Telegram Gifts adapter (separate asset domain, deliberately out of scope).
- [ ] Deal chat, admin panel, E2E tests, production hardening.

### Open decisions for the maintainer (as of this snapshot)

- Renaming the `pending_payment` order status (mentions a payment that does not exist) — requires a migration; raised as an open question, not done unilaterally.

**Resolved:** PR #49 `docs/issue-48-mvp-scope` (price removal, destructive migration `0005_free_listings`) was closed by the owner on 2026-11-10 without merging. Main never contained the removal and no data was lost. Prices remain a mandatory part of the product model.

### Recommended next implementation sequence

1. Stage B: server-side NFT delivery confirmation and the full order lifecycle after reservation.
2. Payment integration strictly per ADR-0001/0002 gates (platform classification, funded remedy, settlement rail — see the ADR blocker lists).
3. Escrow/гарант only after separate design, testnet validation and audit.
4. Admin, chat, E2E tests, production operations.

## 11. First 10 minutes for a new agent

1. Read this file and the relevant sections of `README.md`.
2. Check current open issues and PRs: https://github.com/AzizIo/Vstore/issues and https://github.com/AzizIo/Vstore/pulls
3. Check out the latest `main`, then create a task-specific branch.
4. Open only the files listed in the relevant section above; follow imports/tests when necessary.
5. Confirm the exact API/database contract before coding.
6. Add tests with the feature, run checks, and open a focused PR.

If this guide conflicts with the current code, **the code, migrations, tests and latest merged PRs are authoritative**. Update this guide when architecture or project status materially changes.
