# Vstore — Agent Instructions

> Last checked: 2026-11-10. This guide describes the current non-custodial MVP and the repository structure. Always inspect the checked-out code, migrations, tests, current issues, and open PRs before relying on any status note.

## 1. Product boundary

Vstore is a Telegram Mini App for a **non-custodial peer-to-peer marketplace for standard TON NFTs implementing TEP-62**.

### Current MVP

The current MVP is deliberately limited to free listings and coordination of direct NFT transfers between users:

- Sellers authenticate through Telegram, connect and prove control of their own TON wallet, and synchronize eligible TON NFTs.
- Sellers create private listing drafts and publish only after a fresh server-side ownership check.
- Buyers browse public listings and create an order reservation.
- The seller is expected to initiate and sign an NFT transfer from their own wallet directly to the buyer's wallet.
- The backend must independently verify on-chain evidence before a future transfer lifecycle may mark an order completed.
- Order reservations can be cancelled or expire. Notifications are delivered through a durable Telegram outbox.

**All current MVP listings are free.** Listing and order records have no price or currency fields. The catalog has no price sorting or currency filter. Never add price inputs, price displays, price-based sorting, checkout buttons, or price snapshots to the current MVP.

### Explicitly unavailable in the current MVP

- Payment collection of any kind: Telegram Stars, TON payments, card payments, external checkout, or other payment rails.
- Escrow, custody of funds or NFTs, commissions, refunds, seller payouts, or dispute adjudication.
- A guarantee service, buyer protection, guaranteed refunds, or guaranteed asset recovery.
- General Telegram Gifts listing or transfer support.

A created order means **reservation only**. It does not mean payment was requested or received, and it does not prove that an NFT was transferred. The legacy database/API status name `pending_payment` currently represents a reservation state; do not infer payment functionality from that name.

### Future phase — guaranteed transactions

The product roadmap intends to explore a guaranteed/protected transaction flow in a later phase. It is **planned, not implemented, not approved, and not legally or platform-cleared**. Its precise architecture and operating model remain undecided. It requires a separate owner decision, platform/provider validation, legal review, threat modelling, and independent security review before implementation.

Payment/escrow documents and ADRs are proposals and research only. They are not implementation authorization.

### Asset distinction

Standard TON NFTs using TEP-62 and Telegram Gifts are different asset types with different ownership and transfer models. The current marketplace path is TON NFT focused. Do not claim that ordinary Telegram bots can inspect or transfer every Telegram Gift, or present Telegram Gifts as supported without a separately implemented and tested integration.

## 2. Architecture and stack

The application is a **modular monolith**. Keep domain boundaries clear; do not introduce microservices without an explicit architecture decision.

### Backend

- Python 3.13+
- FastAPI, Pydantic v2, pydantic-settings
- SQLAlchemy 2 async and PostgreSQL
- Alembic migrations
- Redis for short-lived wallet-proof challenges and supporting infrastructure
- aiogram 3 for Telegram bot runtime and notification delivery
- TON NFT provider/verifier integration for TEP-62 ownership checks

Backend source is under `backend/app/`. API routers are registered in `backend/app/main.py`.

### Frontend

- React 19 + TypeScript + Vite
- Tailwind CSS v4 and the existing project CSS
- Telegram Mini App integration and TON Connect UI
- Vitest and Testing Library

Frontend source is under `frontend/src/`.

### Infrastructure

- PostgreSQL and Redis are defined in root `docker-compose.yml`.
- Backend and frontend CI are in `.github/workflows/backend.yml` and `.github/workflows/frontend.yml`.
- The optional Telegram bot/outbox worker uses the Compose `bot` profile.
- Environment-variable names and safe placeholders are documented in root `.env.example`.

## 3. Repository map

```text
/
├── AGENTS.md
├── README.md
├── .env.example
├── docker-compose.yml
├── .github/workflows/
│   ├── backend.yml
│   └── frontend.yml
├── backend/
│   ├── app/
│   │   ├── api/                 # FastAPI route handlers
│   │   ├── assets/ton_nft/      # TON NFT provider, address and TEP-62 verifier
│   │   ├── auth/                # Telegram initData and API authentication
│   │   ├── core/                # Settings and application configuration
│   │   ├── db/                  # SQLAlchemy models and DB session
│   │   ├── listings/            # Draft, publish, edit, cancel and expiry services
│   │   ├── notifications/       # Durable Telegram outbox delivery
│   │   ├── orders/              # Reservation, cancellation and expiry services
│   │   └── wallets/             # TON Connect proof verification and challenges
│   ├── migrations/versions/     # Alembic schema history
│   ├── tests/                   # Unit, API and PostgreSQL integration tests
│   ├── alembic.ini
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── api/                 # Typed API clients
│   │   ├── auth/                # Telegram session integration
│   │   ├── listings/            # Seller listing and inventory picker UI
│   │   ├── orders/              # Buyer/seller reservation views
│   │   ├── wallet/              # TON Connect UI
│   │   ├── App.tsx
│   │   └── test/
│   ├── package.json
│   └── vite.config.ts
└── docs/
    ├── ASSET_INTEGRATION_AUDIT.md
    ├── LISTING_CREATION_FLOW.md
    ├── ORDER_LIFECYCLE.md
    ├── PAYMENTS_ESCROW_DESIGN.md
    ├── TELEGRAM_NOTIFICATIONS.md
    ├── TON_CONNECT_PROOF.md
    ├── TON_NFT_VERIFICATION.md
    ├── adr/
    └── discussions/
```

Use the source tree as authoritative if a path changes.

## 4. Implemented foundations and unfinished flows

The repository contains the following foundations. Their presence does not imply that every Telegram end-to-end path is production-ready.

### Implemented foundations

- Telegram Mini App `initData` HMAC validation and bearer-token API sessions.
- Authenticated current-user and wallet APIs.
- Backend TON Connect proof challenge/verification primitives; the backend is authoritative for wallet verification.
- TON NFT provider and TEP-62 item/owner verification primitives.
- Authenticated NFT inventory endpoint with pagination.
- Listing draft creation from eligible verified NFTs.
- Live ownership re-check before publishing; seller listing edit/unpublish and listing expiry lifecycle.
- Public catalog, listing details, filtering, pagination, and stable newest-first ordering.
- Order reservation, idempotency, buyer cancellation, expiry worker, and append-only order events.
- Durable Telegram notification outbox with retry and at-least-once delivery semantics.
- PostgreSQL migrations, Docker Compose, backend/frontend CI, and unit/integration test foundations.

### Work still tracked by MVP issues

Check the current GitHub issue/PR state before taking work. The principal remaining issue sequence is:

- **#43 — TON Connect proof UI/lifecycle:** review frontend proof flow, wallet restore/account/network changes, and perform actual wallet-signing verification inside Telegram.
- **#44 — NFT inventory:** complete sync/ownership refresh semantics, stale-asset handling, metadata input safety, and a dedicated user-facing inventory experience.
- **#45 — listing/catalog acceptance:** code scope is substantially implemented; final acceptance depends on wallet and inventory flows plus the full user journey.
- **#46 — direct NFT transfer confirmation:** implement the seller-to-buyer transfer request and independent on-chain confirmation; no order may become completed based on client claims or a submitted hash alone.
- **#47 — Mini App/bot E2E:** complete the mobile Telegram user journey and negative-path E2E coverage.

Issue #41 is the parent non-custodial MVP plan. Do not start a dependent task before checking its issue dependencies and current PR state.

## 5. Current API and lifecycle notes

Inspect route schemas and tests for the exact live contract. The list below is navigation, not a substitute for reading the route.

| Area | Endpoint / location | Notes |
|---|---|---|
| Telegram auth | `POST /api/auth/telegram` | Verify raw `Telegram.WebApp.initData`; never trust `initDataUnsafe`. |
| Current user | `GET /api/users/me` | Authenticated profile. |
| Wallets | `GET /api/wallets/me` | Only backend-verified wallet state is authoritative. |
| Wallet proof | `POST /api/wallets/proof/challenge`, `POST /api/wallets/proof/verify` | Short-lived, user-bound one-time proof challenge. |
| NFT inventory | `GET /api/assets/me` | Uses the current user's verified wallet; provider failures must not look like empty inventory. |
| Catalog | `GET /api/listings` | Public, paginated, newest-first. Optional filters: `asset_type`, `search`. **No price or currency fields/filters/sorting.** |
| Listing detail | `GET /api/listings/{listing_id}` | Only currently visible listings are returned. |
| Seller listings | `GET /api/listings/me` | Authenticated seller's records. |
| Listing draft | `POST /api/listings` | Uses verified asset identity and optional title/description/expiry. No price fields. |
| Order reservation | `POST /api/orders` | Requires `Idempotency-Key`; reservation only, no payment. |

### Database and migration rules

- Database schema is defined in SQLAlchemy models and Alembic migrations.
- Add a new Alembic migration for every schema change. Never edit an already-applied migration to change production history.
- Current free-MVP listing/order tables do not store price/currency. Legacy price columns are removed by migration `0005_free_listings`.
- The database partial unique index `uq_listings_open_asset` prevents more than one ACTIVE/RESERVED listing for the same NFT.
- PostgreSQL is the source of truth for concurrency-sensitive behavior. Prefer PostgreSQL integration tests for row locks, unique constraints, migrations, and concurrent reservations.
- Use a dedicated disposable `TEST_DATABASE_URL` for integration tests. Never run tests/migrations against a production or shared database.

### Reservation semantics

- `pending_payment` is a legacy enum value meaning “reserved”; it is not an active payment state.
- Do not add `paid`, `completed`, `refunded`, or transfer-success paths to the current reservation service.
- Order reservation must re-check current ownership through the configured TEP-62 verifier.
- Provider outage or inconclusive ownership data must fail closed without falsely marking an NFT as transferred or stale.
- A future order can be marked completed only after a separately implemented server-side verification of exact NFT item, sender, recipient, and network.

## 6. Security and product invariants

These are mandatory:

1. Never trust client-supplied Telegram user identity, owner ID, seller ID, wallet verification flags, NFT verification state, network, or listing state.
2. Verify raw Telegram `initData` on the backend and enforce its freshness.
3. A connected wallet address alone is not proof of wallet control. Use a short-lived, user-bound, one-time TON Connect proof challenge.
4. Never request, store, log, or transmit wallet seed phrases or private keys. TON Connect signing happens in the user's own wallet.
5. Verify the NFT item, collection/network, and current owner with the trusted TEP-62 verifier. Metadata and image URLs are untrusted display inputs.
6. Do not hold database transactions or row locks while calling an external TON provider.
7. Preserve a consistent lock order for listing, wallet, and asset rows. Review the existing service before changing lock paths.
8. User-submitted transaction hashes, screenshots, client callbacks, or UI state are hints only; they are never proof of NFT transfer.
9. An unavailable or inconclusive provider is not evidence that ownership changed. Keep the operation pending/conflicted and fail closed.
10. Do not introduce pricing, payment collection, Stars, checkout, escrow, custody, refunds, payouts, commissions, or buyer-protection claims into the current MVP.
11. Distinguish TEP-62 TON NFTs from Telegram Gifts. Do not claim unsupported Telegram Gift capabilities.
12. Never commit secrets, real user data, `.env`, API keys, bot tokens, JWT secrets, or wallet material.

## 7. Local development and checks

From repository root:

```bash
cp .env.example .env
# Set local-only values. Generate AUTH_SECRET_KEY with:
openssl rand -hex 32

docker compose up --build
docker compose exec api alembic upgrade head
```

Start the optional Telegram bot/outbox worker:

```bash
docker compose --profile bot up --build
```

Services:

- Mini App: `http://localhost:5173`
- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- Readiness: `http://localhost:8000/api/health/ready`

### Backend checks

```bash
cd backend
python -m pip install -e ".[dev]"
ruff check app tests migrations
pytest --cov=app --cov-report=term-missing -q
```

### Frontend checks

```bash
cd frontend
npm install
npm run test:coverage
npm run build
```

Backend CI provisions a PostgreSQL service and runs lint/tests. Frontend CI runs unit/coverage tests and a production build. Check workflow path filters when changing shared root files or workflows.

## 8. Parallel-agent and Git workflow

Multiple agents may work in this repository simultaneously. Follow these rules:

1. Never commit directly to `main`. Start a task-specific branch from the latest `origin/main`.
2. Before editing, inspect open issues, open PRs, branch names, and current main SHA. Another agent may have changed a shared contract.
3. One focused task/issue per branch and PR. State the owned files in the task and avoid editing files owned by another active agent.
4. Do not rebase, force-push, reset, revert, or rewrite another agent's branch without explicit coordination.
5. Do not merge someone else's PR without maintainer authorization. A green CI is necessary but not sufficient; review diff and product scope too.
6. Keep API/schema changes coordinated between backend and frontend. Update typed API clients, tests, and docs in the same PR or explicitly split them into dependent PRs.
7. Add regression tests for changed behavior. Before opening/updating a PR, run Ruff, backend tests, frontend tests, and production build as appropriate.
8. Inspect the complete diff for accidental unrelated edits, secrets, generated files, and migrations.
9. Report exact branch, commit SHA, PR link, changed paths, tests actually executed, CI result, manual checks still required, and known limitations.
10. Do not claim that a test or Telegram wallet-signing flow passed unless its evidence is available.

Suggested branch prefixes:

- `feat/<area>-<short-description>`
- `fix/<area>-<short-description>`
- `test/<area>-<short-description>`
- `docs/<short-description>`

Suggested commit prefixes: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`.

If this guide conflicts with source code, migrations, tests, or the latest merged PRs, the code/migrations/tests are authoritative. Update this guide whenever a material architecture or product boundary changes.
