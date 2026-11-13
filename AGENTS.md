# VILTARA SHOP — Agent Onboarding

> Read before changing code. This guide is a repository map and a set of collaboration rules; always inspect the exact code, migrations, tests and live GitHub state before relying on status notes.
> Product boundaries are defined in [docs/PRODUCT_MODEL.md](docs/PRODUCT_MODEL.md): listing prices are mandatory, a reservation is not payment, and payment/escrow must not be imitated.

## 1. Product and current status

VILTARA SHOP is a Telegram Mini App and optional bot for a peer-to-peer marketplace of **TEP-62 TON NFTs**. Telegram Gifts are a separate asset domain and are not supported as transferable marketplace assets.

The current main baseline was reviewed on **2026-11-13**, commit **9593f1a003a4f976cf3e6b3b20cb1d3830d83018**. The implementation is more advanced than the earlier Stage A-only descriptions:

| Capability | Status on main |
|---|---|
| Public catalogue and priced seller listings | Implemented; listing prices and currency remain mandatory |
| Telegram Mini App initData authentication and API bearer session | Implemented |
| TON Connect Proof challenge → wallet signing → backend verification | Implemented; UI/proof flow remains fail-closed until public manifest and exact backend domain allowlist are configured |
| Verified NFT inventory and My NFT screen | Implemented; paginated reconciliation, multi-wallet ownership checks and guarded stale listing/order invalidation |
| Listing lifecycle and fresh ownership checks | Implemented; publishing and order reservation revalidate ownership server-side |
| Order reservation, price/currency snapshot, cancellation and expiry | Implemented; **not a payment flow** |
| Direct non-custodial NFT delivery B1–B6 | Implemented on main; backend observer independently verifies finalized transfer evidence and the seller signs from their own wallet |
| Transactional Telegram notification outbox | Implemented; optional bot/worker profile delivers informational order and delivery notifications |
| Admin moderation center and audit history | Implemented; mandatory pending-review approval before listings become public; administrator access is disabled unless the server-side allowlist is configured |
| Public seller profiles and verified reviews | Implemented; only safe public seller fields and reviews backed by completed, independently verified NFT delivery are exposed |
| Private seller overview | Implemented; authenticated user-scoped counts, recent activity and currency-separated price snapshots, including `pending_review` |
| Operations diagnostics | Implemented; read-only outbox health CLI and inventory discrepancy diagnostic; neither retries notifications nor mutates inventory |
| Payments, checkout, Stars settlement, escrow, custody, refunds, commissions and seller payouts | Not implemented |
| Telegram Gifts transfer integration and deal chat | Not implemented |

**Reservation is not payment.** Orders snapshot the listing price and currency, but no funds are collected or settled. The marketplace does not hold NFTs, request private keys, sign transactions for users, or guarantee a transaction.

### TON Connect and inventory configuration

- Backend TON Connect Proof verification and the frontend challenge → proof → verify lifecycle are in main (PR #51).
- Wallet UI/proof operations are deliberately fail-closed while the public manifest URL or exact backend domain allowlist is missing or invalid. A wallet connection or displayed address alone is not proof of control.
- Full NFT inventory reconciliation, secondary-wallet ownership checks and the My NFT screen are in main (PR #58).
- Live Telegram/Tonkeeper, manifest/icon, testnet/provider and owner-review acceptance remains open in Issues #43 and #44. CI results do not replace these manual checks.

### Stage B delivery

B1–B6 are implemented on main across PRs #63, #85, #86, #90, #92 and #101. The implemented path includes immutable delivery-intent snapshots, a leased observer, seller preparation/submission/read APIs, exact TEP-62 transfer payload construction, seller-wallet signing through TON Connect, transactional notifications and participant-visible progress.

A submitted wallet reference is only an untrusted lookup hint. A client callback, screenshot, wallet screen, submitted hash or current-owner lookup alone cannot complete an order. Only the backend observer's independent verification of the exact persisted transfer intent and finalized provider evidence can do so.

Live testnet/Tonkeeper transfer acceptance remains open in Issue #46. Do not equate merged code and CI with a verified live transfer.

### Admin moderation

The moderation workspace is available at the Mini App route /admin. The API is mounted under /api/admin. Sellers submit listings into `pending_review`; they are not public until an allowlisted admin approves them. Editing a pending listing returns it to draft and requires resubmission. Admins can approve, reject, suspend and restore eligible listings through a bounded queue with audit history.

Admin access is **fail-closed**: configure the server-side ADMIN_TELEGRAM_IDS JSON array with the intended numeric Telegram user IDs. The default is empty and denies admin access. Never accept a role, actor ID or Telegram ID supplied by the client. Moderation decisions require a reason and Idempotency-Key; approve/restore recheck current TON ownership. The PostgreSQL audit log is append-only. See [docs/ADMIN_MODERATION_AUDIT.md](docs/ADMIN_MODERATION_AUDIT.md).

The moderation center is not a general-purpose dispute, payment, escrow or payout system.

## 2. Repository map

    /
    ├── README.md
    ├── AGENTS.md
    ├── .env.example
    ├── docker-compose.yml
    ├── .github/workflows/
    ├── docs/
    │   ├── PRODUCT_MODEL.md
    │   ├── STAGE_B_ORDER_LIFECYCLE.md
    │   ├── ADMIN_MODERATION_AUDIT.md
    │   ├── PREVIEW_DEPLOYMENT.md
    │   ├── PREVIEW_DEMO_RUNBOOK.md
    │   ├── DEMO_PREFLIGHT.md
    │   ├── API_BACKED_E2E.md
    │   ├── TELEGRAM_NOTIFICATIONS.md
    │   └── adr/
    ├── backend/
    │   ├── app/main.py
    │   ├── app/api/                 # auth, users, wallets, assets, listings, orders
    │   ├── app/admin/               # admin moderation and audit API
    │   ├── app/auth/                # Telegram initData, JWT sessions and dependencies
    │   ├── app/assets/ton_nft/      # TON Center provider, TEP-62 verifier and evidence adapter
    │   ├── app/orders/              # reservation lifecycle, delivery observer, state/event rules
    │   ├── app/notifications/       # durable outbox, read-only health diagnostics and Telegram worker
    │   ├── app/db/models.py
    │   ├── scripts/                 # read-only outbox/inventory diagnostics and Preview safety tools
│   └── migrations/versions/
    └── frontend/
        ├── src/App.tsx
        ├── src/api/
        ├── src/auth/
        ├── src/wallet/
        ├── src/listings/
        ├── src/orders/
        ├── src/overview/            # private seller overview workspace
        ├── src/admin/               # moderation workspace
        └── src/test/

Architecture is a **modular monolith**. Keep domain boundaries explicit; do not add microservices without a reviewed architectural decision.

## 3. Backend and frontend contracts

- Backend: Python 3.13+, FastAPI, Pydantic v2, SQLAlchemy async, PostgreSQL and Alembic. Configuration is loaded through backend/app/core/config.py from the environment and root .env.
- Frontend: React 19, TypeScript, Vite, Tailwind CSS and TON Connect UI; API clients are under frontend/src/api/.
- Runtime: Compose runs PostgreSQL, Redis, API and Mini App. The bot/outbox worker is optional under the bot Compose profile.
- Database changes go through Alembic revisions in backend/migrations/versions/. Never hand-edit a deployed schema.
- Read the route, schema, service/model and tests before changing an API or database contract.

Important API routes on main (all paths are relative to the API origin):

| Method | Endpoint | Purpose |
|---|---|---|
| POST | /api/auth/telegram | Verify raw Telegram Mini App initData and issue API JWT |
| GET | /api/users/me | Current authenticated user |
| GET | /api/users/me/overview | Private seller overview for the verified current user |
| GET | /api/sellers/{seller_id}/profile | Public seller profile, purchasable listings and delivery-verified reviews |
| POST | /api/wallets/proof/challenge | Issue a short-lived user-bound TON Proof challenge |
| POST | /api/wallets/proof/verify | Cryptographically verify TON Proof and link wallet |
| GET | /api/wallets/me | Current user's verified wallet records |
| GET | /api/assets/me | Paginated verified NFT inventory with server-side ownership recheck |
| POST | /api/assets/me/sync | Full bounded inventory reconciliation across verified wallets |
| GET | /api/listings | Public listing catalogue with existing filters/sorting/pagination |
| POST | /api/listings | Create a draft from an eligible verified asset |
| POST | /api/listings/{listing_id}/publish | Submit a draft for admin review after fresh ownership verification |
| POST | /api/orders | Idempotent reservation; snapshots price/currency; not payment |
| GET | /api/orders | Buyer/seller order list |
| GET | /api/orders/{order_id} | Participant-scoped order details |
| POST | /api/orders/{order_id}/cancel | Cancel an eligible reservation before delivery is committed |
| POST | /api/orders/{order_id}/delivery/prepare | Persist buyer/seller wallet and NFT transfer intent snapshot |
| POST | /api/orders/{order_id}/delivery/submissions | Submit an untrusted wallet-returned reference for observer lookup |
| GET | /api/orders/{order_id}/delivery | Read participant-scoped delivery attempt and verification status |
| GET | /api/admin/access | Check whether the verified session is allowlisted for admin access |
| GET | /api/admin/moderation | Read the bounded admin listing moderation queue |
| POST | /api/admin/listings/{listing_id}/decision | Approve/reject/suspend/restore with reason and Idempotency-Key |
| GET | /api/admin/audit | Read bounded moderation audit history |
| GET | /api/admin/listings/{listing_id}/audit | Read audit history for one listing |

The moderation endpoints require the server-side admin allowlist. Do not invent request fields or query parameters; use the current Pydantic schemas, route code and tests as the source of truth. For the exact moderation state transitions and audit guarantees, read [docs/ADMIN_MODERATION_AUDIT.md](docs/ADMIN_MODERATION_AUDIT.md).

The B2 migration renames legacy pending_payment rows/events to reserved in place; this did not represent a payment. Delivery attempt statuses and Order states now support the implemented B1–B6 observer lifecycle. See [docs/STAGE_B_ORDER_LIFECYCLE.md](docs/STAGE_B_ORDER_LIFECYCLE.md) before changing order or delivery behavior.

## 4. Safety and product invariants

1. **Telegram auth:** verify raw Telegram.WebApp.initData server-side; never trust initDataUnsafe or client-supplied Telegram user fields.
2. **Wallet security:** never request/store seed phrases or private keys. Connected status is not verified proof; trust only server cryptographic verification and persisted wallet state.
3. **NFT authenticity/ownership:** verify the TEP-62 item, expected network and current owner through the trusted provider. Names, images, links and client-supplied metadata are untrusted.
4. **Listings:** draft creation requires an eligible verified asset. Publishing and order reservation must preserve fresh server-side ownership checks and race-safe database revalidation.
5. **Orders:** reservations snapshot price and currency but do not deduct funds or lock an NFT on-chain. Never add fake payment, delivery or completion success states.
6. **Delivery:** the seller signs directly in their own wallet. Preserve the immutable transfer-intent snapshot, observer lease/fencing, finality policy, idempotency and independent evidence checks. Never trust a submitted wallet reference as proof.
7. **Product domains:** TON NFT and Telegram Gifts need separate adapters. Telegram Business API rights constrain any future gift operations.
8. **Payment/escrow:** no checkout, custody, refund, commission, seller payout or buyer-protection feature is approved for the current MVP. ADRs/design docs are proposals unless separately approved.
9. **Admin:** every protected request must derive the actor from the verified bearer session and check the server allowlist. Keep audit snapshots minimal and the PostgreSQL audit log append-only.
10. **Fail closed:** provider outage, ambiguous ownership, invalid proof or incomplete chain evidence must never be represented as success.
11. **Concurrency/idempotency:** preserve unique constraints, idempotency keys, lock order, SKIP LOCKED workers, order events, observer leases and outbox guarantees.
12. **Secrets:** never commit .env, tokens, signing secrets, API keys, private keys or real user data.

## 5. Development commands

From repository root:

    test -f .env || cp .env.example .env
    # If .env already exists, preserve it. Generate AUTH_SECRET_KEY locally with: openssl rand -hex 32
    docker compose up --build
    docker compose exec api alembic upgrade head

Optional bot:

    # Configure BOT_TOKEN and TELEGRAM_MINI_APP_URL in the local .env first
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
    npm run test:e2e

Some PostgreSQL integration tests require a dedicated disposable TEST_DATABASE_URL; never point tests or migrations at a production/shared database. GitHub Actions provisions isolated PostgreSQL/Redis services and loopback TON fixtures for API-backed E2E coverage. That coverage is not live blockchain or Telegram/Tonkeeper acceptance.

For the isolated Preview stack, follow [docs/PREVIEW_DEPLOYMENT.md](docs/PREVIEW_DEPLOYMENT.md) and [docs/PREVIEW_DEMO_RUNBOOK.md](docs/PREVIEW_DEMO_RUNBOOK.md). Run the documented Preview safety guard before migrations and the preflight after API startup. The Preview safety checks are not permission to deploy or alter a live environment.

## 6. Collaboration and branch rules (mandatory)

- Never commit directly to main; use a focused task branch and PR.
- Before editing, inspect the latest main, existing branches, open issues and open PRs.
- Do not create duplicate issues, overwrite another person's branch, force-push another person's work or merge someone else's PR without authorization.
- Keep unrelated domains separate. In particular, do not mix UI features, order lifecycle changes, moderation and payment/escrow work.
- For contract changes, update request/response schemas and tests in the same PR; use migrations for every DB schema change.
- Run applicable CI/lint/tests/build, inspect the final diff and report the exact SHA, test results and blockers.
- Do not close an issue merely because a PR exists. Keep manual/live acceptance separate from implementation and CI completion.
- Do not treat an open or Draft PR as shipped functionality. The source of truth for shipped behavior is the current main branch.

## 7. Status snapshot and manual acceptance — 2026-11-13

This status snapshot describes main at 9593f1a003a4f976cf3e6b3b20cb1d3830d83018. Check live GitHub before acting because issues and PRs can change independently of this file.

- **Issue #43:** proof implementation and CI are merged; live Telegram/Tonkeeper proof signing, account/network switching, public manifest/icon and exact-host acceptance remain.
- **Issue #44:** inventory implementation, per-item ownership regression coverage and a read-only discrepancy diagnostic are merged; manual multi-page/multi-wallet/provider-outage testnet checks and owner review evidence remain.
- **Issue #46:** Stage B B1–B6 implementation is on main; live testnet transfer, provider-finality and Tonkeeper acceptance remain. Its implementation checklist may lag merged PRs; verify the manual acceptance section rather than treating unchecked historical implementation boxes as proof the code is absent.
- **Issue #47:** automated backend/frontend/browser/API-backed coverage exists, but full real Telegram mobile journey acceptance remains open.
- **Issue #104:** closed by PR #107, which introduced the admin moderation center and immutable audit history. PR #135 added the mandatory pending-review publication gate and migration `0011_listing_pending_review`.
- **Seller profiles and reviews:** public profile API exposes safe seller details and only delivery-verified reviews; private seller overview is scoped to the authenticated user and separates TON/XTR price snapshots.
- **Operations:** PR #139 added read-only outbox health diagnostics; PR #142 restricted push CI to main, enabled manual CI dispatch and added a dry-run-by-default stale queue cleanup workflow. The cleanup workflow has not been executed.
- **Open PRs:** no open PRs remained at the time of this snapshot. Check live GitHub before acting; features are shipped only after merge to main.

The Preview runbooks and CI prove isolated test behavior, not a publicly deployed and manually accepted Telegram Mini App. Do not claim production deployment, live testnet transfer acceptance or live Tonkeeper success without recorded evidence.

## 8. First 10 minutes for a new contributor

1. Read AGENTS.md, README.md and docs/PRODUCT_MODEL.md.
2. Check [open Issues](https://github.com/AzizIo/Vstore/issues) and [open PRs](https://github.com/AzizIo/Vstore/pulls).
3. Inspect current main and the exact files/tests for your task.
4. Confirm API/DB contracts and existing concurrency/security invariants before editing.
5. Add behavior-level tests, run CI-equivalent checks and open a focused PR.

If this guide conflicts with code, migrations, tests or approved product decisions, those are authoritative. Update this guide when status materially changes.
