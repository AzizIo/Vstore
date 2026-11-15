# Backend release-candidate audit — 2026-11-15

**Audit baseline:** `main` at `19d50682441c06faa80622d837c4762f2d23cec1`  
**Scope:** backend API/auth, orders, Telegram Stars ledger/refunds, Alembic/PostgreSQL invariants, escrow API/action integration boundaries.  
**Status:** code hardening in this branch is not a production launch approval.

## 1. Runtime and access-control review

- Telegram Mini App authentication validates the raw `initData` HMAC, duplicate fields and auth-date freshness before updating the user record.
- Bearer tokens use HS256 with a configured secret of at least 32 characters. Protected dependencies resolve the user from the database on each request rather than trusting Telegram IDs or roles stored in the token.
- Blocked-account policy is enforced server-side. Existing-order routes use the separate allow-blocked identity dependency; order creation and listing writes have explicit blocked-account guards.
- Admin permissions derive from the server-side `ADMIN_TELEGRAM_IDS` allowlist and verified bearer identity.
- User-scoped order and delivery reads are participant-bound. Client transaction references remain untrusted hints; the delivery observer remains the authority for completed NFT transfer.
- The escrow API runtime gate now requires TON testnet **and** a permitted runtime. Local/development/test and an explicitly marked Preview runtime are allowed; normal `ENVIRONMENT=production` does not mount escrow endpoints even if `TON_CONNECT_NETWORK=testnet` is accidentally configured. Production Compose does not set `PREVIEW_MODE`; the isolated Preview Compose stack does.

## 2. Orders, payment ledger and refund flow

Current order states remain a delivery lifecycle; reservation is not payment and Stars payment does not complete an order.

| Area | Current backend source | Safety boundary |
|---|---|---|
| Order reservation | `backend/app/orders/service.py` | Fresh seller NFT ownership, listing row lock, buyer/seller and price/currency snapshots, unique idempotency constraints |
| Delivery preparation | `prepare_delivery` in the same service | Rechecks current seller ownership and both wallet bindings; XTR orders require a paid payment intent before preparation |
| Stars intent | `backend/app/orders/payment_service.py` | Test-mode-only; order lock, buyer binding, XTR integer amount and expiry |
| Successful charge | `record_stars_success` | Exact invoice/payer/amount/currency/unique Telegram charge binding; duplicate and conflicting events are rejected or treated idempotently |
| Event ledger | `PaymentEvent` | Unique provider event identity, payload digest and PostgreSQL append-only journal |
| Refund workflow | `backend/app/orders/refund_worker.py` | One durable row per charge; SKIP LOCKED leases/fencing; provider I/O outside the DB transaction; ambiguous results reconcile before any retry |
| Refund evidence | migrations `0015` and `0016` | Financial snapshot immutability, no TRUNCATE and no row DELETE of refund evidence |

This branch adds database-enforced whole-Star amount constraints and explicit `telegram_stars`/`XTR` checks for payment transactions. Migration `0017_payment_xtr_invariants` checks existing evidence first and aborts rather than rounding or rewriting any historic amount. No provider balance or seller payable balance is created; no automatic seller payout is represented.

## 3. Webhook and provider status

The current Stars bot uses Telegram's dedicated **test** Bot API namespace with long polling. There is no public payment webhook route in the current application. Therefore the application does not currently exercise webhook `secret_token` verification; this audit does not claim otherwise and does not add an unused webhook endpoint.

If a webhook transport is approved later, it must be a separately reviewed ingress with constant-time comparison of `X-Telegram-Bot-Api-Secret-Token`, bounded request bodies, secret verification before update processing, Telegram update-ID and charge-ID replay protection, and exact persisted invoice/payer/currency/integer amount checks. Raw update bodies, invoice payloads, bot tokens and webhook secrets must not be logged.

No production Telegram token, production bot API namespace, live invoice, real refund or production payment database was accessed.

## 4. TON escrow integration boundary

The backend has durable escrow action records and PostgreSQL idempotency/lease/fencing primitives. Listing reservation uses the same marketplace `Listing` row as normal Orders. Provider and observer interfaces demand structured chain-finality, trace/message binding, getter reconciliation and terminal owner evidence; their default implementations remain unconfigured and fail closed.

The pinned ABI adapter can construct unsigned testnet TON Connect messages, but the current database deal snapshot does not persist every required deployment term (including reserve/refund amounts, all action query IDs, authority public keys and initial/getter state). The API deliberately uses `UnconfiguredTONEscrowContractAdapter`. Until the full immutable deployment snapshot and provider evidence contract are agreed with the adapter/contract owners, the backend must keep transaction preparation unavailable and must not synthesize values or store a partial payload as executable.

No private key, signing, broadcast, mainnet action or live testnet wallet submission is part of this work. No Tolk contract or ABI opcode is changed by this branch.

## 5. Release blockers outside this code slice

1. Live Telegram Test Server invoice → pre-checkout → successful-payment round trip is a manual acceptance task; unit tests and mocks are not live Telegram evidence.
2. No production checkout, live refunds, seller payout, escrow custody or seller balance is approved. The platform/legal ruling tracked in Issue #155 and qualified legal review remain blockers for paid NFT sales.
3. Stars currently uses a polling transport, not a webhook. A webhook should not be introduced unless there is a genuine infrastructure need and its secret-rotation/ingress contract is approved.
4. The TON escrow cryptographic testnet finality provider and active action worker/reconciler are still absent. An indexer flag, transaction hash or wallet callback is not finality proof.
5. Complete deal deployment snapshots and independent contract/security acceptance are still required before exposing transaction payload preparation.
6. Production database grants, off-host encrypted backup retention, restore drills and infrastructure acceptance are operational checks outside a code-only PR.

## 6. Verification plan

- Ruff and full backend pytest.
- PostgreSQL migration to head and integration tests against the disposable CI PostgreSQL service.
- Explicit PostgreSQL CHECK-constraint negative tests for alternate provider, non-XTR currency and fractional Stars amount.
- Runtime gate tests for local/test/Preview vs ordinary production route mounting.
- Backend, Frontend and API-backed E2E CI on the exact PR head.

No test result should be interpreted as proof of Telegram policy approval, live payment/refund acceptance, TON chain finality, independent contract audit, production deployment or seller payout readiness.
