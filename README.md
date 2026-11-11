# VILTARA SHOP

VILTARA SHOP is a Telegram Mini App and optional bot for a peer-to-peer marketplace foundation built around **TON NFTs that implement TEP-62**. Sellers can create priced listings for assets whose current ownership has been checked by the backend. Buyers can reserve a listing and view the resulting order; direct-transfer coordination and independent delivery confirmation are planned, not yet available.

**Reservation is not payment.** The current product stage does not collect funds, provide escrow, transfer NFTs on behalf of users, or verify post-reservation delivery. A reservation records the buyer, seller, listing, price/currency snapshot, expiry and lifecycle events; it does not mean that the seller has transferred the NFT or that the buyer has paid.

Product boundaries and decisions approved for the current MVP are recorded in [docs/PRODUCT_MODEL.md](docs/PRODUCT_MODEL.md).

## Current MVP status

| Capability | Status on main |
|---|---|
| Public catalogue, filters, sorting and pagination | Implemented |
| Listings with seller-set price/currency; create draft, publish, edit and unpublish | Implemented |
| Telegram Mini App initData verification and API bearer session | Implemented |
| TON NFT (TEP-62) on-chain ownership verifier via TON Center v3 | Implemented |
| NFT inventory GET /api/assets/me and full sync POST /api/assets/me/sync | Implemented; paginated reads, provider reconciliation, multi-wallet ownership checks and guarded stale-listing/order invalidation |
| Fresh ownership check before publishing and reservation | Implemented; provider errors fail closed |
| Order reservation, price/currency snapshot, idempotency, cancellation and expiry | Implemented; **not a payment flow** |
| Telegram order notifications using a durable outbox | Implemented; optional bot container |
| TON Connect frontend challenge → proof → backend verification and manifest | Implemented in main via [PR #51](https://github.com/AzizIo/Vstore/pull/51); live Telegram/Tonkeeper acceptance remains open in [Issue #43](https://github.com/AzizIo/Vstore/issues/43) |
| Full inventory reconciliation/sync and dedicated My NFT screen | Implemented in main via [PR #58](https://github.com/AzizIo/Vstore/pull/58); live testnet/provider acceptance remains open in [Issue #44](https://github.com/AzizIo/Vstore/issues/44) |
| Server-side verification that a reserved NFT was delivered to the buyer | Not implemented; design proposal in [docs/STAGE_B_ORDER_LIFECYCLE.md](docs/STAGE_B_ORDER_LIFECYCLE.md); implementation tracked in [Issue #46](https://github.com/AzizIo/Vstore/issues/46) |
| Telegram Gifts adapter, deal chat, admin panel | Not implemented |
| Payments, checkout, escrow/guarantee, refunds, commissions and seller payouts | Not implemented |

The internal order status name pending_payment is a legacy name for the current reserved/pending order lifecycle. It **must not** be interpreted or presented as evidence that a payment exists.

## How listing and reservation work today

1. The Telegram Mini App authenticates the user's raw Telegram.WebApp.initData with the backend. Do not trust initDataUnsafe or client-supplied user fields.
2. NFT inventory is sourced from backend-verified TON wallets. The My NFT screen uses the server-side inventory sync and TEP-62 ownership rechecks; wallet connection alone is not proof of wallet control, and client-supplied NFT metadata is not proof of ownership.
3. A seller creates a draft for an eligible, verified asset. Publishing rechecks on-chain ownership immediately before making the listing active.
4. A buyer reserves an active listing. The backend checks seller/asset state, takes a snapshot of price and currency, and uses idempotency/concurrency protections. The order expires or can be cancelled; the reservation does not lock the NFT on-chain.
5. The current product has **no automated NFT delivery confirmation**. The service must not display a reservation as paid, completed, or delivered.

The Stage B architecture is now documented in [docs/STAGE_B_ORDER_LIFECYCLE.md](docs/STAGE_B_ORDER_LIFECYCLE.md) (design merged through [PR #60](https://github.com/AzizIo/Vstore/pull/60)). It remains a proposal: the maintainer decisions in its final section must be approved before implementation begins under [Issue #46](https://github.com/AzizIo/Vstore/issues/46). A transaction hash, screenshot, client callback, or current-owner read alone is not sufficient proof of delivery.

## Planned direct NFT transfer flow (Stage B — not implemented)

The following describes the intended non-custodial flow. It is **not available in the current application** and must not be represented as a completed transaction feature:

1. The buyer connects and proves control of a TON wallet through the backend-verified TON Connect Proof flow.
2. The buyer reserves an active listing. Reservation records the order and price/currency snapshot; it does not transfer or lock the NFT.
3. Before the seller is asked to transfer, the delivery-preparation flow is intended to snapshot the verified seller wallet, buyer destination wallet, exact NFT item and network for that order.
4. The seller initiates and signs the TEP-62 NFT transfer directly from the seller's own wallet to the snapshotted buyer address. The marketplace never receives private keys or takes custody of the NFT.
5. A backend observer independently retrieves and validates chain evidence for the exact item, network, source and destination under an approved finality policy. A transaction hash supplied by a user is only a lookup hint.
6. Only after server-side verification may the order be marked completed. Provider outages, incomplete evidence, wrong recipients or ambiguous transfers must remain non-success states and require reconciliation.

The state machine, proposed API/database contracts, failure handling and decisions required before implementation are described in [docs/STAGE_B_ORDER_LIFECYCLE.md](docs/STAGE_B_ORDER_LIFECYCLE.md). See [Issue #46](https://github.com/AzizIo/Vstore/issues/46) for the implementation work. No payment, escrow, refund or seller-payout behavior is part of this flow.

## Supported assets and wallet security

- **Supported asset domain:** standard TON NFT items implementing TEP-62. Treat the item contract and current owner as authoritative; treat names, images and other metadata as untrusted display input.
- **Telegram Gifts:** separate asset domain with different Telegram Business permissions and transfer rules. No generic Telegram Gifts transfer integration is currently shipped.
- The server must never request, receive, or store seed phrases or private keys. TON Connect delegates wallet operations to the user's wallet.
- The full TON Connect challenge → proof → backend verification flow and manifest are now in main via PR #51. The frontend remains deliberately disabled until VITE_TONCONNECT_MANIFEST_URL is configured and the backend exact-domain TON_CONNECT_ALLOWED_DOMAINS allowlist is non-empty. A connected address alone is never proof; live Tonkeeper acceptance on the real HTTPS Mini App host remains open in Issue #43.
- No payment, escrow, refund, commission, seller payout, custody, or buyer-protection feature is enabled. The future guaranteed-transaction phase remains planned only; its architecture, security, platform-policy and legal review must be completed separately. Read [ADR-0001](docs/adr/0001-compliant-payments-and-escrow.md) and [the payment/escrow design proposal](docs/PAYMENTS_ESCROW_DESIGN.md) as proposals, not as implemented or approved settlement rails.

## Architecture

The repository is a modular monolith:

- **Backend:** Python 3.13+, FastAPI, Pydantic v2, SQLAlchemy async, PostgreSQL, Alembic.
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS, TON Connect UI.
- **Infrastructure:** Docker Compose, PostgreSQL, Redis; optional aiogram bot and notification outbox worker.
- **Assets:** TEP-62/TON Center v3 verification is isolated under backend/app/assets/ton_nft/.
- **Orders:** reservation lifecycle and events are under backend/app/orders/; there is no payment provider wired to the current order flow.

For the platform and asset limitations, see [docs/ASSET_INTEGRATION_AUDIT.md](docs/ASSET_INTEGRATION_AUDIT.md). For notification retry and delivery semantics, see [docs/TELEGRAM_NOTIFICATIONS.md](docs/TELEGRAM_NOTIFICATIONS.md). The current product boundaries are defined by [docs/PRODUCT_MODEL.md](docs/PRODUCT_MODEL.md).

## Local development

Requirements: Docker with Docker Compose, Node/npm for standalone frontend checks, and Python 3.13+ for standalone backend checks.

From the repository root, copy the environment template, configure the required values, and start the stack:

    cp .env.example .env
    # Generate AUTH_SECRET_KEY with: openssl rand -hex 32
    docker compose up --build
    docker compose exec api alembic upgrade head

The PostgreSQL and Redis credentials in the Compose file are development-only. Never use them as production secrets. Never commit .env, bot tokens, JWT secrets, API keys, private keys or real user data.

Local endpoints:

- Mini App: http://localhost:5173
- API: http://localhost:8000
- OpenAPI: http://localhost:8000/docs
- Readiness: http://localhost:8000/api/health/ready

To run the optional Telegram bot/outbox worker, set `BOT_TOKEN` and `TELEGRAM_MINI_APP_URL` in `.env`, then run:

    docker compose --profile bot up --build

`TELEGRAM_MINI_APP_URL` must be the configured Telegram Mini App direct link, not the frontend website origin:

```text
https://t.me/<bot_username>/<app_short_name>
```

Create/configure the named Mini App via [@BotFather](https://t.me/BotFather) and use the exact bot username and app short name from that setup. The bot validates this format before showing a launch button; notification links use the same validator and append an `order_<32-hex-id>` `startapp` value. Telegram Mini App direct links can also use `startapp=listing_<32-hex-id>`. These parameters are navigation hints only; the frontend's existing parser handles order/listing IDs, and authentication still uses verified Telegram `initData`.

See [Telegram Mini Apps direct links](https://core.telegram.org/bots/webapps#direct-link-mini-apps) for details.

Apply schema migrations after starting the stack:

    docker compose exec api alembic upgrade head

Example current API routes (authenticate with a backend Bearer token where indicated):

| Method | Route | Purpose |
|---|---|---|
| POST | /api/auth/telegram | Verify raw Telegram initData and issue an API session |
| GET | /api/users/me | Current user |
| POST | /api/wallets/proof/challenge | Issue a short-lived user-bound TON proof challenge |
| POST | /api/wallets/proof/verify | Cryptographically verify TON Connect Proof and link wallet |
| GET | /api/wallets/me | Current user's linked wallets |
| GET | /api/assets/me | Verified NFT inventory (server-side ownership recheck) |
| GET | /api/listings?limit=24&offset=0&sort=newest | Public listings |
| POST | /api/listings | Create listing draft from a verified eligible asset |
| POST | /api/listings/{listing_id}/publish | Publish after a fresh ownership check |
| POST | /api/orders | Reserve listing (requires Idempotency-Key; **not payment**) |
| GET | /api/orders | Buyer's or seller's orders |
| POST | /api/orders/{order_id}/cancel | Cancel an eligible pending reservation |

For the exact contract, inspect routes, schemas and tests under backend/app/api/ and backend/tests/; do not infer additional endpoints from the roadmap.

Before a customer or investor walkthrough, run the read-only [live demo preflight](docs/DEMO_PREFLIGHT.md) against the public API and Mini App origins. It checks API readiness, the Mini App HTML, and the TON Connect manifest/icon without changing the deployment.

## Quality checks

Backend (from the repository root):

    cd backend
    python -m pip install -e ".[dev]"
    ruff check app tests migrations
    pytest --cov=app --cov-report=term-missing -q

Some PostgreSQL integration tests require a dedicated disposable TEST_DATABASE_URL and are skipped if it is not configured. Never point test fixtures or migrations at a production/shared database. GitHub Actions provisions an isolated PostgreSQL service in Backend CI.

Frontend:

    cd frontend
    npm install
    npm run test:coverage
    npm run build

Frontend CI runs Vitest, TypeScript checks and a production Vite build. Use the CI result for the exact commit you intend to review.

## Roadmap

1. **MVP — non-custodial NFT listing and direct-transfer verification (Issues #42–#47):** Stage A currently provides listings, ownership checks, reservations and expiry/cancellation. Stage B adds the post-reservation transfer lifecycle and complete Telegram user journey; these parts are still in progress and must not be presented as shipped.
2. **Future — guaranteed transactions (not implemented):** a separate product phase requiring its own architecture, security, platform-policy and legal review. Do not assume a custody model, refund policy, payment method or seller settlement has been approved.
3. **Other planned work:** Telegram Gifts (only if a supported transfer path is established), deal chat, admin and production operations.

Prices are part of the Listing model and must not be removed to make the no-payment MVP appear “free”. A reservation is not a payment, and the future guarantee is not available in the current product.

## Contributing

Read [AGENTS.md](AGENTS.md) before changing code. Never commit directly to main; create a task-specific branch and focused PR. Inspect active issues/PRs before starting work, do not overwrite another branch, and do not merge or close issues without authorization.
