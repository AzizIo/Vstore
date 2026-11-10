# VILTARA SHOP (Vstore)

Vstore is a Telegram Mini App project for a **non-custodial, peer-to-peer TON NFT marketplace**. The current MVP focuses on verified NFT listings, wallet connectivity, order coordination, and direct wallet-to-wallet transfer verification. It is not a payment processor or an escrow/guarantee service.

## Current MVP status

This repository is under active development. Treat the status below as the product boundary; an API model or a proposed design document does not by itself mean a feature is available.

### Implemented foundations

- FastAPI backend and React + TypeScript Telegram Mini App.
- PostgreSQL persistence, SQLAlchemy async models, Alembic migrations, and Redis integration.
- Telegram Mini App `initData` validation and bearer-token API authentication.
- TON NFT verification/provider foundations and authenticated asset/listing APIs.
- Public listing/catalog APIs and seller listing workflows, including ownership re-checks and reservation safeguards.
- Order creation/reservation, buyer cancellation, expiration worker, append-only order events, and Telegram notification outbox.
- Local Docker Compose environment.

See [Buyer order lifecycle](docs/ORDER_LIFECYCLE.md) and [Asset integration audit](docs/ASSET_INTEGRATION_AUDIT.md) for implementation boundaries and technical context.

### In progress

The end-to-end user journey is still being completed and reviewed: TON Connect proof lifecycle (#43), reliable NFT inventory refresh (#44), final listing acceptance (#45), direct NFT transfer confirmation (#46), and Mini App/bot end-to-end flows (#47). Issue #42 (fresh ownership check before reservation) is merged. Follow the remaining implementation issues: [#43–#47](https://github.com/AzizIo/Vstore/issues/43).

### Not available in the current MVP

- Checkout or payment collection (including Telegram Stars or TON payments).
- Escrow or custody of user funds/NFTs by Vstore.
- Commissions, refunds, seller payouts, or dispute handling.
- A guarantee, buyer protection, or guaranteed recovery of an asset.
- General Telegram Gifts trading. Telegram Gifts and standard TON NFTs are different asset types; the current product path is focused on TON NFTs implementing TEP-62. Do not assume Telegram Gifts are transferable through this app.

## How an MVP NFT transfer is intended to work

1. The seller connects a TON wallet and the backend verifies wallet control through the supported proof flow.
2. The seller synchronizes eligible TON NFTs and publishes a listing only after current ownership is checked.
3. A buyer opens the listing and creates an order; the listing is reserved while the order is active.
4. The seller initiates and signs the NFT transfer from their own wallet directly to the buyer's wallet using TON Connect.
5. The backend independently checks on-chain evidence for the expected NFT item, sender, recipient, and configured network. The order may be marked completed only after that verification succeeds.

**The end-to-end transfer flow is still in progress.** Until the relevant implementation and tests are complete, do not treat this sequence as a claim that every step is already available in production. Creating an order or submitting a transaction hash is not proof of transfer.

## Security model

- Vstore does not custody NFT assets, user funds, seed phrases, or private keys.
- Never enter or share a seed phrase or private key with Vstore, the bot, support, or another user. The app should request wallet approval through the wallet's own interface.
- Wallet connection alone is not proof of ownership or authentication; server-side proof verification is required.
- NFT metadata and images are untrusted display data. Collection membership and current ownership must be verified independently.
- Blockchain data can be delayed or temporarily unavailable. An uncertain transfer must remain pending or require reconciliation, not be shown as successful.
- The current MVP is direct-transfer coordination, not an escrow transaction. A direct transfer may be irreversible.

## Supported assets and network

The planned initial asset path is standard TON NFTs implementing [TEP-62](https://github.com/ton-blockchain/TEPs/blob/master/text/0062-nft-standard.md). Collection authenticity, item address, owner, and network must be checked; metadata alone is not proof.

Telegram Gifts use separate Telegram APIs and account permissions. They are not interchangeable with TEP-62 NFTs. No general Telegram Gifts transfer or resale support is promised by this MVP.

The configured TON network and provider settings are controlled by environment variables. See `.env.example`; do not assume mainnet behavior is suitable for local or testnet development.


## Useful API endpoints

All protected endpoints below require `Authorization: Bearer <access_token>` from a verified Telegram Mini App session.

- `POST /api/auth/telegram` — validate the raw `Telegram.WebApp.initData` and create an API session.
- `GET /api/users/me` — current authenticated profile.
- `GET /api/wallets/me` — wallets linked to the current user.
- `POST /api/wallets/proof/challenge` and `POST /api/wallets/proof/verify` — backend wallet-proof challenge and verification endpoints. Frontend integration is tracked by #43.
- `GET /api/assets/me?limit=24&offset=0` — inventory page for the user's verified wallet; provider errors are not returned as an empty inventory.
- `GET /api/listings?limit=24&offset=0&sort=newest` — public catalog; filters include `asset_type`, `currency`, `search`, and `sort=price_asc|price_desc|newest`. Only currently purchasable active listings are visible.
- `GET /api/listings/{listing_id}` — public detail for a currently visible listing.
- `GET /api/listings/me` — private listings belonging to the current user.
- `POST /api/listings` — create a private draft from an eligible inventory asset.
- `POST /api/orders` — create an authenticated order reservation; this does not collect payment or prove an NFT transfer.

See [Buyer order lifecycle](docs/ORDER_LIFECYCLE.md) for reservation, cancellation, expiry, ownership checks, and notification semantics.

## Current pricing-field caveat

The existing listing model and Mini App still require/store `price_amount` and `price_currency`, display those values, and support price sorting. They are **not connected to payment collection**: there is no checkout, payment confirmation, commission, refund, or seller payout in the MVP. This is a legacy product-scope mismatch to resolve before public launch; do not interpret the displayed value or an order reservation as money changing hands.

## Local development

Requirements: Docker Engine/Desktop with Docker Compose, plus Python 3.13+ and Node.js/npm if running components outside Docker.

1. Create local configuration:

   ```bash
   cp .env.example .env
   ```

2. Set `BOT_TOKEN` if you need Telegram `initData` validation or the optional bot worker. Generate a local API secret and put it in `AUTH_SECRET_KEY`:

   ```bash
   openssl rand -hex 32
   ```

3. Build and start the API, Mini App, PostgreSQL, and Redis:

   ```bash
   docker compose up --build
   ```

4. Apply database migrations:

   ```bash
   docker compose exec api alembic upgrade head
   ```

5. Local endpoints:

   - Mini App: http://localhost:5173
   - API: http://localhost:8000
   - OpenAPI docs: http://localhost:8000/docs
   - Readiness: http://localhost:8000/api/health/ready

6. To run the optional Telegram bot/outbox worker, configure `BOT_TOKEN` and `TELEGRAM_MINI_APP_URL`, then run:

   ```bash
   docker compose --profile bot up --build
   ```

Local Compose database credentials are development-only. Do not deploy them or commit real credentials. Use managed secrets, restricted network access, TLS, backups, and an explicit production configuration before deployment.

## Tests and quality checks

Backend (from the repository root):

```bash
cd backend
python -m pip install -e ".[dev]"
ruff check app tests migrations
pytest --cov=app --cov-report=term-missing -q
```

Frontend:

```bash
cd frontend
npm install
npm run test:coverage
npm run build
```

These commands are defined by the backend `pyproject.toml` and frontend `package.json`. They have been checked against those configuration files for this documentation update; they have **not** been executed in this editing session. Run them in CI or a configured local environment before treating a change as verified.

## Roadmap

### Phase 1 — MVP: non-custodial NFT listing and direct transfer verification

Issue #42 (ownership/reservation safety) is complete. Issues [#43–#47](https://github.com/AzizIo/Vstore/issues/43) track the remaining wallet proof, NFT inventory, final listing acceptance, direct transfer confirmation, and end-to-end Mini App/bot work. This phase excludes payment collection and escrow.

### Phase 2 — Guaranteed transactions (planned)

Vstore intends to explore a protected transaction flow in a later phase. It is **not implemented, approved, or legally/platform-cleared**. Before implementation, the team must decide the architecture and operating model, validate platform/payment-provider rules, obtain appropriate legal review, threat-model the system, and complete security testing. No particular escrow/custody model, payment method, fee, refund outcome, seller payout schedule, or asset recovery is promised.

Related payment documents are background research and proposals, not approved implementation specifications:

- [ADR-0001: Compliant payments and escrow architecture](docs/adr/0001-compliant-payments-and-escrow.md) — proposed, awaiting maintainer review.
- [Payments and escrow design](docs/PAYMENTS_ESCROW_DESIGN.md) — technical design proposal; production blockers remain open.
- [Asset integration audit](docs/ASSET_INTEGRATION_AUDIT.md) — technical assessment, not a legal opinion or security audit.
- [Platform NFT resale classification research](docs/discussions/research/platform-nft-resale-classification.md) — current policy research; the exact P2P resale classification remains unresolved and this is not legal/platform approval.

## Contributing

Please keep pull requests focused, add regression tests for behavior changes, and update documentation when product behavior or API contracts change. Payment, escrow, custody, and seller-payout code must not be introduced as part of the current MVP without a separately reviewed product decision.


### Telegram order notifications

Order creation, buyer cancellation, and automatic expiry enqueue recipient notifications in the
same transaction as the order state change. Delivery is handled by the separate optional bot
container using a PostgreSQL-backed outbox. Configure `BOT_TOKEN` and
`TELEGRAM_MINI_APP_URL` in `.env`, then start the bot profile:

```bash
docker compose --profile bot up --build
```

See [docs/TELEGRAM_NOTIFICATIONS.md](docs/TELEGRAM_NOTIFICATIONS.md) for retry, monitoring,
and delivery-guarantee details.
