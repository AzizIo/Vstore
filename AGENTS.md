# VILTARA SHOP — Agent Onboarding

> Read this file before changing code. It is a navigation guide and collaboration contract, not a replacement for inspecting the exact files involved in your task.
> Last checked: 2026-11-09. The repository changes continuously; verify the current branch, open PRs, and file contents before relying on status notes below.

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
│   │   └── versions/             # Versioned DB schema changes
│   ├── tests/                    # Backend unit/API/model tests
│   ├── alembic.ini
│   ├── pyproject.toml             # Python dependencies, Ruff, pytest and mypy config
│   └── Dockerfile
└── frontend/
    ├── src/
    │   ├── App.tsx              # Current Mini App shell / entry screen
    │   ├── main.tsx             # React entrypoint
    │   ├── index.css            # Global styles
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
- **Important reality check:** on the current `main` snapshot the UI is still a small static shell in `frontend/src/App.tsx`. A complete feature/component architecture, API client, session integration and catalog flow are not present yet. Do not assume a planned library is already wired into the app; inspect actual imports and code first.

### Local infrastructure

- `docker-compose.yml` starts PostgreSQL 17, Redis 7, FastAPI API and the Mini App.
- The Telegram bot is behind the Compose profile `bot`; it is not started by the default `docker compose up`.
- Local service ports: API `8000`, Mini App `5173`; Swagger at `/docs`.
- Use root `.env.example` to create `.env`. Never commit `.env`, tokens, signing secrets, private keys or real user data.

## 4. Existing API contract — inspect before extending

Current API routes are registered in `backend/app/main.py`.

| Method | Endpoint | Auth | Current behavior |
|---|---|---|---|
| GET | `/api/health/live` and readiness route | No | Health/readiness checks; see `api/health.py` |
| POST | `/api/auth/telegram` | Telegram initData | Verifies signed, short-lived Mini App initData; upserts user; returns API JWT |
| GET | `/api/users/me` | Bearer JWT | Returns current user profile |
| GET | `/api/listings` | No | Active catalog; filters `asset_type`, `currency`, `search`; sort `newest`, `price_asc`, `price_desc`; pagination `limit`/`offset` |
| GET | `/api/listings/me` | Bearer JWT | Current seller's listings |
| GET | `/api/listings/{listing_id}` | No | Active listing detail only; otherwise 404 |
| POST | `/api/listings` | Bearer JWT | Creates a **draft only**, requiring a verified asset owned by the current user |

For exact request/response fields and validation, read `backend/app/api/listings.py`, `backend/app/api/auth.py`, `backend/app/auth/schemas.py` and the related tests. Do not invent endpoints, query parameters or response fields.

## 5. Database model quick map

Defined in `backend/app/db/models.py` and initially migrated in `backend/migrations/versions/0001_initial_marketplace.py`:

- `User`: Telegram identity and account state.
- `Wallet`: user wallet address/network and verification flags.
- `NFTCollection`: collection address/network and metadata.
- `NFTAsset`: asset type, external ID, optional item address, collection/owner, metadata and verification state.
- `Listing`: seller, asset, lifecycle status, amount/currency, title/description and expiry.

Important constraints already encoded include unique Telegram IDs, unique wallet address per network, unique external asset ID per asset type, positive listing price, foreign keys, and a PostgreSQL partial unique index preventing multiple open (`active`/`reserved`) listings for the same asset. Read the model and migration before changing related behavior.

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

## 10. Project status snapshot (2026-11-09)

This is a snapshot, not a promise that every item remains current. Verify the live repository and PR list before starting work.

### Implemented on `main`

- [x] FastAPI app, configuration, CORS and health/readiness endpoints.
- [x] PostgreSQL async engine/session and Alembic migration setup.
- [x] Core SQLAlchemy entities: users, wallets, NFT collections/assets and listings.
- [x] Telegram Mini App initData HMAC validation and API JWT authentication.
- [x] Current-user endpoint and auth dependencies.
- [x] Public active-listing catalog with filters, sorting and pagination.
- [x] Active listing detail, seller's listings and secure draft creation.
- [x] Docker Compose local infrastructure for PostgreSQL, Redis, API and Mini App.
- [x] Basic React/TypeScript/Vite/Tailwind Mini App shell.
- [x] Backend and frontend CI workflows; backend unit/API tests and frontend shell tests/build.

### In progress / open work at the time this guide was written

- [ ] **Issue #2 — frontend marketplace catalog and listing details.** Scope is frontend only, branch `feat/frontend-marketplace-catalog`; do not edit the same frontend files while this task is active. Track: https://github.com/AzizIo/Vstore/issues/2
- [ ] **PR #3 — PostgreSQL integration test suite.** Branch `test/postgres-integration`; adds 11 PostgreSQL integration tests, a PostgreSQL 16 CI service and pytest integration marker. Latest observed Backend CI run passed. The PR is still open/draft and its changes are not yet part of `main`. Track: https://github.com/AzizIo/Vstore/pull/3

### Not implemented / do not assume available

- [ ] Frontend Telegram session integration and protected-route/role handling.
- [ ] TON Connect manifest, wallet connection and wallet proof/verification flow.
- [ ] Production TON NFT ownership verification adapter / blockchain watcher.
- [ ] Telegram Gifts adapter and validated transfer flow.
- [ ] Listing publishing after a live ownership re-check.
- [ ] Orders/deals, escrow ledger, dispute flow, payment capture/refunds/payouts.
- [ ] Deal chat, notification pipeline and full admin panel.
- [ ] Production hardening, monitoring, backup/restore and deployment runbook.
- [ ] End-to-end browser tests.

### Recommended next implementation sequence

1. Finish and review the frontend catalog/detail task against the existing API contract.
2. Merge PostgreSQL integration coverage after review; add real API-level integration tests using a dedicated test DB.
3. Implement asset verification behind explicit TON NFT / Telegram Gifts adapters; do not enable listing publication until live ownership checks exist.
4. Build listing management and order/deal domain with state-transition tests and audit trail.
5. Decide and validate compliant payment/escrow/transfer flows before implementing real-money operations.
6. Add admin, chat, notifications, E2E tests and production operations.

## 11. First 10 minutes for a new agent

1. Read this file and the relevant sections of `README.md`.
2. Check current open issues and PRs: https://github.com/AzizIo/Vstore/issues and https://github.com/AzizIo/Vstore/pulls
3. Check out the latest `main`, then create a task-specific branch.
4. Open only the files listed in the relevant section above; follow imports/tests when necessary.
5. Confirm the exact API/database contract before coding.
6. Add tests with the feature, run checks, and open a focused PR.

If this guide conflicts with the current code, **the code, migrations, tests and latest merged PRs are authoritative**. Update this guide when architecture or project status materially changes.
