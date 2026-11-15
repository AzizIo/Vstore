# Backend release-candidate audit — 2026-11-15

**Audit baseline:** `main` at `19d50682441c06faa80622d837c4762f2d23cec1`  
**Scope:** auth/session handling, API ownership boundaries, orders, Stars payment ledger/refunds, PostgreSQL migrations, escrow API/action integration boundaries.  
**Decision:** implementation hardening is not production launch approval.

## Verified architecture

- Telegram Mini App `initData` is verified using Telegram's HMAC-SHA-256 scheme and an auth-date freshness window before user data is trusted.
- API bearer sessions use HS256 and a configured secret. Each protected request resolves the user from the database; the API does not trust the JWT's Telegram ID/role as authorization.
- Admin routes use a server-side Telegram ID allowlist. Blocked-account restrictions are enforced in server dependencies and explicitly guarded write routes.
- Order creation is a reservation with a persisted price/currency snapshot. It is not payment. The delivery observer remains the only authority that can complete NFT delivery.
- Stars payment intents, charge transactions, event journal and durable refund workflow are separate from order delivery state. Payment success does not change an order to completed.
- Refund work uses a durable per-charge row, PostgreSQL leases/fencing, provider IO outside DB transactions and reconciliation of ambiguous outcomes. Unknown provider history does not permit a blind second refund.
- TON escrow has durable action/idempotency primitives and a pinned unsigned-message adapter. Contract signing is not performed by the backend.

## RC changes in this branch

1. Migration `0017_payment_xtr_invariants` adds PostgreSQL CHECK constraints for whole-Star payment-intent and transaction amounts, plus the fixed `telegram_stars` transaction provider. It runs a preflight check and aborts rather than rewriting historical records.
2. Payment transaction currency is deliberately preserved as provider evidence. A trusted but unexpected currency must be persisted verbatim as `refund_pending` so the durable refund worker can reconcile that charge. The invoice intent itself remains constrained to XTR; the service only captures a matching XTR charge.
3. Escrow router registration now requires testnet and an allowed runtime. Normal production does not mount testnet escrow routes, even if its network setting is accidentally changed to testnet. The isolated Preview stack explicitly opts in with `PREVIEW_MODE=1`.
4. Escrow action preparation now builds a typed deployment snapshot only when every required immutable deployment term, action query ID, authority public key and getter-state fact is persisted. Until then it stores a durable `blocked_abi` action and returns HTTP 503 `deployment_snapshot_incomplete`, instead of constructing an incomplete dataclass and failing as an unhandled server error.

## Stars/webhook status

The current Stars test bot uses the dedicated Telegram **test** Bot API namespace and long polling. The application has no public Stars webhook route today, so Telegram's `X-Telegram-Bot-Api-Secret-Token` is not an active request path. Do not report webhook authentication as implemented or add an unused endpoint just to claim webhook coverage.

A future webhook transport requires a separate design/review: constant-time secret comparison before update processing, strict body size limits, replay protection using Telegram update identity and the unique charge IDs, exact persisted invoice/payer/amount/currency checks, and secret-safe logging. No production Telegram bot token or live Bot API call is used by this PR.

## Escrow integration status

The backend has idempotent action records, query-ID/BOC/submission-reference retention fields, leases and immutable identity guards. The pinned adapter and ABI vectors are available. However:
- the current persisted `EscrowDeal` schema does not include all deployment economics/reserves/refunds, action query IDs, oracle/resolver keys and initial/getter-state facts required by the adapter;
- the API intentionally uses `UnconfiguredTONEscrowContractAdapter`;
- there is no configured cryptographic TON testnet masterchain-finality provider or active action worker/reconciler;
- wallet references are untrusted lookup hints and cannot advance deal state.

No unsigned transaction payload is returned in this release candidate. No contract/ABI code is changed here; this remains coordinated with the escrow/contract owners (#206, #213, #214 and #197).

## Release blockers

- Complete the real Telegram Test Server invoice → pre-checkout → successful-payment manual round trip using test credentials and a disposable PostgreSQL database. CI fixtures are not live Telegram acceptance.
- No public paid checkout, live refund execution, marketplace commission, seller balance or seller payout is approved. Issue #155 still lacks a written Telegram ruling for this exact NFT resale flow.
- Build and independently verify the TON testnet finality/current-owner provider and action worker only after the complete immutable deployment snapshot and contract owner approval are agreed.
- Execute a valueless testnet lifecycle acceptance with transaction/trace/getter/current-owner evidence; a transaction hash or wallet callback alone is insufficient.
- Production database migration, secrets, VPS network, backup recovery and monitoring require owner-controlled operational acceptance.

## Test evidence

The PR CI must run on the exact PR head:
- Ruff and the complete backend pytest suite;
- disposable PostgreSQL migration-to-head and integration tests;
- PostgreSQL negative writes for invalid provider/fractional Stars values;
- runtime-gate and escrow snapshot unit tests;
- Frontend, production build, Playwright and API-backed E2E regression checks.

No production database, production token, private key, live payment/refund, payout or mainnet chain operation has been used by this work.
