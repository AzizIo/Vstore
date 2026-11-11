# VILTARA SHOP — Agent Onboarding

> Read before changing code. This guide documents the repository and collaboration rules; inspect the exact code and live issues/PRs before relying on a status snapshot.
> Product decisions: [docs/PRODUCT_MODEL.md](docs/PRODUCT_MODEL.md) is authoritative for product boundaries — listing prices are mandatory, reservation is not payment, and payment/escrow must not be imitated.

## 1. Product and current status

VILTARA SHOP is a Telegram Mini App and optional bot for a peer-to-peer marketplace of **TEP-62 TON NFTs**. Telegram Gifts are a separate asset domain and are not integrated as transferable assets on main.

This is a marketplace foundation, not a completed buying/selling/guarantee system. Current shipped features are the public listing catalogue, priced seller listings, server-side NFT ownership checks, order reservation/cancellation/expiry, Telegram authentication and informational order notifications.

**Reservation is not payment.** Orders snapshot listing price/currency but no payment provider is wired to the lifecycle. Server-side NFT delivery confirmation after reservation, payment/checkout, escrow/guarantee, refunds, seller payouts, deal chat and admin panel are not implemented. Do not describe roadmap work as shipped.

TON Connect nuance:
- Backend endpoints and cryptographic verification for TON Connect Proof, plus the complete frontend challenge → proof → verify flow and manifest, are merged into main via PR #51.
- The wallet UI is fail-closed: it stays disabled while VITE_TONCONNECT_MANIFEST_URL is empty, and backend proof challenges stay unavailable while TON_CONNECT_ALLOWED_DOMAINS is empty/invalid. A connected address alone never proves control.
- Full NFT inventory reconciliation, secondary-wallet ownership checks, guarded stale-order invalidation and the My NFT screen are merged into main via PR #58.
- Live Telegram/Tonkeeper and testnet/provider acceptance remains open in Issues #43 and #44. Do not claim those manual checks are complete from CI results.

## 2. Repository map

    /
    ├── README.md
    ├── AGENTS.md
    ├── .env.example
    ├── docker-compose.yml
    ├── .github/workflows/{backend,frontend}.yml
    ├── docs/
    │   ├── PRODUCT_MODEL.md
    │   ├── ASSET_INTEGRATION_AUDIT.md
    │   ├── TELEGRAM_NOTIFICATIONS.md
    │   ├── PAYMENTS_ESCROW_DESIGN.md
    │   └── adr/
    ├── backend/
    │   ├── app/main.py                 # FastAPI setup/router registration/lifespan
    │   ├── app/api/                    # auth, users, wallets, assets, listings, orders
    │   ├── app/auth/                   # Telegram initData, JWT sessions and dependencies
    │   ├── app/assets/ton_nft/         # TON Center provider, TEP-62 verifier and contracts
    │   ├── app/orders/                 # reservation lifecycle, status/event rules, payment protocol
    │   ├── app/notifications/          # durable outbox and Telegram delivery worker
    │   ├── app/db/models.py            # SQLAlchemy models, enums and constraints
    │   └── migrations/versions/        # Alembic migrations; DB schema changes must be migrated
    └── frontend/
        ├── src/App.tsx
        ├── src/api/
        ├── src/auth/                   # Telegram initData and session provider
        ├── src/wallet/                 # TON Connect UI
        ├── src/listings/
        ├── src/orders/
        └── src/test/

Architecture is a **modular monolith**. Keep domain boundaries explicit; do not add microservices without a reviewed architectural decision.

## 3. Backend and frontend contracts

- Backend: Python 3.13+, FastAPI, Pydantic v2, SQLAlchemy async, PostgreSQL and Alembic. Router prefixes are /api; configuration loads through backend/app/core/config.py from environment and root .env.
- Frontend: React 19, TypeScript, Vite, Tailwind CSS; API clients are under frontend/src/api/.
- Runtime: Compose runs PostgreSQL, Redis, API and Mini App. The bot/outbox worker is optional under Compose profile bot.
- Database changes go through Alembic revisions in backend/migrations/versions/; never hand-edit production schema.
- Read the existing route, schema, service/model and tests before changing a contract.

Important current API routes:

| Method | Endpoint | Purpose |
|---|---|---|
| POST | /api/auth/telegram | Verify raw Telegram Mini App initData; issue API JWT |
| GET | /api/users/me | Current user |
| POST | /api/wallets/proof/challenge | Short-lived user-bound TON proof challenge |
| POST | /api/wallets/proof/verify | Cryptographically verify proof and link wallet |
| GET | /api/wallets/me | Current user's wallet records |
| GET | /api/assets/me | Paginated verified inventory with server-side ownership recheck |
| POST | /api/assets/me/sync | User-triggered full inventory reconciliation; bounded pagination, multi-wallet recheck and safe stale listing/order invalidation |
| GET | /api/listings | Public filter/sort/page catalogue |
| POST | /api/listings | Draft from verified eligible asset |
| POST | /api/listings/{listing_id}/publish | Publish after fresh ownership verification |
| POST | /api/orders | Idempotent reservation; snapshots price/currency; not payment |
| GET | /api/orders | Buyer/seller order list |
| POST | /api/orders/{order_id}/cancel | Cancel eligible pending reservation |

Do not invent route fields/query parameters: use API schemas and tests as source of truth. Legacy database `pending_payment` rows are migrated to `reserved`; no status may be treated as a payment or shown as “paid”. Order states for delivery are schema groundwork only until a delivery API/observer is implemented.

## 4. Safety and product invariants

1. **Telegram auth:** verify raw Telegram.WebApp.initData server-side; never trust initDataUnsafe or client-supplied Telegram user fields.
2. **Wallet security:** never request/store seed phrases or private keys. Connected status is not verified proof; trust only server cryptographic verification and persisted wallet record.
3. **NFT authenticity/ownership:** verify TEP-62 item, expected network, current owner and collection consistency via trusted provider/on-chain source. Names, images, links and client-supplied metadata are untrusted.
4. **Listings:** draft creation requires a verified eligible asset. Publishing must keep its fresh server-side ownership check and race-safe database revalidation.
5. **Orders:** reservations snapshot price and currency but do not deduct funds or lock an NFT on-chain. Current worker handles expiry; do not add fake payment/delivery success states.
6. **Product domains:** TON NFT and Telegram Gifts need separate adapters. Telegram Business API rights constrain gift operations.
7. **Payment/escrow:** no checkout, custody, refund, commission, seller payout or buyer-protection feature is approved for the current MVP. ADRs/design docs are proposals unless expressly approved.
8. **Fail closed:** provider outage, ambiguous ownership, invalid proof or incomplete chain data must never be represented as success.
9. **Concurrency/idempotency:** preserve existing unique constraints, idempotency keys, lock order, SKIP LOCKED workers, order events and outbox guarantees.
10. **Secrets:** never commit .env, tokens, signing secrets, API keys, private keys or real user data.

## 5. Development commands

From repository root:

    cp .env.example .env
    # Generate AUTH_SECRET_KEY with: openssl rand -hex 32
    docker compose up --build
    docker compose exec api alembic upgrade head

Optional bot:

    # Set BOT_TOKEN and TELEGRAM_MINI_APP_URL in .env first
    docker compose --profile bot up --build

Backend checks:

    cd backend
    python -m pip install -e ".[dev]"
    ruff check app tests migrations
    pytest --cov=app --cov-report=term-missing -q

Frontend checks:

    cd frontend
    npm install
    npm run test:coverage
    npm run build

Some PostgreSQL integration tests require a dedicated disposable TEST_DATABASE_URL; never point tests/migrations at a production or shared database.

## 6. Collaboration and branch rules (mandatory)

- Never commit directly to main; use a focused task branch and PR.
- Before editing, inspect the latest main, existing branches, open issues and open PRs.
- Do not create duplicate issues, overwrite another branch, force-push another person's work, or merge someone else's PR without authorization.
- Keep unrelated domains separate. In particular, do not mix UI features, order lifecycle changes and payment/escrow work.
- For contract changes, update request/response schemas and tests in the same PR; use migrations for every DB schema change.
- Run applicable CI/lint/tests/build, inspect the diff and report the exact SHA, tests and blockers.
- Do not close an issue merely because a PR exists. Live/manual acceptance criteria must be verified before calling a task complete.

## 7. Roadmap/status snapshot — 2026-11-11

Treat this as a dated snapshot and check live GitHub before acting.

- **Current Stage A:** priced listings, backend-verified TON Connect Proof (UI gated until public URLs/domain allowlist are configured), full TEP-62 NFT inventory sync/reconciliation, listing lifecycle, order reservation with price/currency snapshot, cancellation/expiry and durable informational Telegram notifications.
- **Issue #43 / PR #51 merged:** code and CI are complete. Live Telegram/Tonkeeper proof signing, account/network switch and public manifest/icon checks remain open in Issue #43; do not enable production wallet configuration before those checks.
- **Issue #44 / PR #58 merged:** full NFT inventory sync/reconciliation and dedicated My NFT UI are in main. Multi-page/multi-wallet/provider/ownership-loss manual acceptance and owner screenshots remain open in Issue #44.
- **Issue #48:** keep docs aligned with approved product model (this document + README.md); do not remove listing prices.
- **Issue #56:** Stage B architecture is documented and merged in `docs/STAGE_B_ORDER_LIFECYCLE.md`. B1 read-only TON Center transfer evidence is merged via PR #63. B2 order-status migration and delivery-attempt persistence are in PR #64; this adds no prepare/submit API or observer. Do not mark orders delivered until B3/B4 add server-side state transitions and reconciliation.
- **Future guaranteed transactions:** a separate later phase. No payments, checkout, escrow/custody, refunds, commissions or seller payout should be implemented under current Stage A.

## 8. First 10 minutes for a new contributor

1. Read AGENTS.md, README.md and docs/PRODUCT_MODEL.md.
2. Check [open Issues](https://github.com/AzizIo/Vstore/issues) and [open PRs](https://github.com/AzizIo/Vstore/pulls).
3. Inspect current main and the exact files/tests for your task.
4. Confirm API/DB contract and existing concurrency/security invariants before editing.
5. Add behavior-level tests, run CI-equivalent checks, then open a focused PR.

If this guide conflicts with code, migrations, tests or approved product decisions, those are authoritative. Update this guide when status materially changes.
