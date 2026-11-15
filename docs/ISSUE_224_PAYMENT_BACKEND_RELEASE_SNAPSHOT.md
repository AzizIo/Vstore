# Issue #224 — release payment backend snapshot

**Snapshot date:** 2026-11-15  
**Implementation base:** `main` at `6dafdcf4c462718df14ea024f29fd277c90f6d39`  
**Scope:** backend payment authority, Telegram Stars transport, ledger, refunds and reconciliation.  
**Release posture:** sandbox/test only. This document does not approve live sales, production credentials, real charges/refunds, seller payouts or custody.

## 1. Provider decision

The only existing in-Telegram digital-goods payment path is **Telegram Stars (`XTR`)**. It remains a candidate for a future compliant product flow, but the repository currently implements it only against Telegram's dedicated test Bot API environment.

No external card/PSP provider is integrated or selected. Selecting one would require a confirmed legal entity, merchant of record, country coverage, marketplace/NFT underwriting, settlement and dispute model. TON/TON Connect is not a card-payment provider and must not be used to bypass Stars for digital purchases inside Telegram.

Telegram's current Bot Payments guidance says digital goods/services sold inside Telegram apps use Stars, and its developer terms expressly discourage real-time sales of virtual items with inherent value that cannot be reclaimed or reversed after a successful dispute. This is a product/platform launch blocker for irreversible NFT delivery, not something a backend test can resolve. See the official references below.

## 2. Actual transport and trust boundary

The implemented flow is:

1. A user invokes `/pay ORDER_UUID` on the dedicated test bot.
2. The server loads the order and buyer from PostgreSQL, verifies that the buyer is the Telegram account owner, and creates/reuses one immutable XTR intent for the order.
3. The bot sends the invoice through Telegram's **test** Bot API namespace.
4. A `pre_checkout_query` is checked against the stored invoice payload, payer Telegram ID, exact integer amount, XTR currency and both order/intent expiry and status.
5. Only a Telegram `successful_payment` update is recorded as payment evidence. A pre-checkout approval or frontend claim is never proof of capture.
6. The event journal stores `update:<telegram update_id>` as its provider-event identity; the provider charge ID is stored separately under a unique database constraint. Re-delivery of the same update is idempotent, while a second charge against the same invoice is recorded as separate refundable evidence.

The transport is **long polling only** through the dedicated test Bot API namespace. There is no public payment webhook route, no configured webhook secret and no active webhook signature-verification path. Therefore this release slice does not claim webhook support or signature-verification coverage. If a webhook is introduced later, it must be separately designed, require Telegram's `X-Telegram-Bot-Api-Secret-Token`, compare it in constant time before parsing, and preserve the same order/payer/amount/currency/charge checks.

The Telegram bot identity is selected by the dedicated test bot token. The payment update supplies the payer and charge evidence, but it does not provide an independent merchant-account identifier for the backend to verify. Do not represent the current integration as a multi-merchant or seller-settlement integration.

## 3. Ledger and state semantics

| Record | States / meaning |
|---|---|
| Payment intent | `pending`, `paid`, `refund_pending`, `refunded`, `failed`, `expired` |
| Payment transaction | `captured`, `refund_pending`, `refunded`; one row per provider charge |
| Refund workflow | `queued`, `processing`, `retry_wait`, `reconciliation_required`, `succeeded`, `manual_review` |
| Order | Retains the independent delivery lifecycle; payment does not set the order to `completed` |

The first valid payment may mark the intent paid. Extra charges, late charges and mismatched payer/amount/currency evidence are retained and routed to refund work; they are not silently discarded. PostgreSQL unique keys, row locks, immutable evidence triggers and the append-only payment event journal protect the core identity/evidence. The later payment-hardening change set also adds whole-Star and provider constraints; keep that change coordinated with PR #223 rather than adding a duplicate migration in this branch.

Telegram's Stars refund method returns the **full** charge. The current adapter does not implement partial refunds. Provider timeouts/ambiguous results are reconciled against transaction history; an unknown or incomplete history remains pending or goes to manual review and never authorizes a blind second refund.

## 4. Backend API contract status

There is **no public HTTP payment-intent, payment-status or webhook endpoint** in the current backend API. Existing HTTP order routes reserve/read/cancel orders and manage delivery; they do not accept client payment-success or refund claims. The current payment entry point is the test bot's `/pay ORDER_UUID` command.

The payment tables and internal statuses are not a frontend API contract. Do not have the Mini App read database-shaped models or infer payment success from an order status. The following is the **proposed frontend-facing contract for coordination only**; none of these routes are implemented by this PR:

| Operation | Proposed contract | Authorization / effects |
|---|---|---|
| Create checkout | `POST /api/orders/{order_id}/payment-intent` | Authenticated order buyer only; server reads amount/currency from immutable order, requires a live reserved XTR order, creates/reuses one intent, and returns a provider checkout URL plus expiry. |
| Read payment | `GET /api/orders/{order_id}/payment` | Authenticated order buyer (seller/admin read rules require separate approval); returns the server-derived payment state and safe refund summary. |
| Provider notification | No public route while the bot uses long polling | A future webhook requires a separately approved secret-validation/replay contract and must not run alongside polling for the same bot. |

Proposed response fields: `order_id`, `payment_status`, `provider`, `amount`, `currency`, `expires_at`, and an optional `checkout_url` on intent creation. A safe refund summary may expose `refund_status` and a non-sensitive support/error code; do not expose bot tokens, invoice payloads, raw updates, provider charge IDs, payer Telegram IDs or database rows. The client may request checkout or read status, but must never submit a claimed `paid`, `captured` or `refunded` state.

Stable public payment statuses should be `pending`, `paid`, `refund_pending`, `refunded`, `failed` and `expired`; internal refund worker states (`queued`, `processing`, `retry_wait`, `reconciliation_required`, `manual_review`) should be mapped to a safe refund summary and must not be mistaken for a completed refund. Unknown provider outcomes remain `refund_pending` / manual review, never success.

Expected API errors: `401` unauthenticated, `404` unknown or non-owned order, `409` non-XTR/expired/non-reserved order or incompatible existing intent, and `503` when the configured payment provider is unavailable. The final request/response envelope, status naming and seller/admin read permissions must be agreed with the frontend owner (Issue #227) before implementation.

## 5. Runtime isolation

The payment service now repeats the isolation boundary itself, rather than relying only on its bot/worker entrypoints. Payment mutations require:

- `TELEGRAM_STARS_TEST_ENABLED=true` and a local/development/test environment;
- a dedicated `TELEGRAM_STARS_TEST_BOT_TOKEN` distinct from `BOT_TOKEN`;
- `DATABASE_URL` using `postgresql+asyncpg`, a local test database host, and a database name beginning with `test_` or ending with `_test`.

The test bot and refund worker add their stricter `ENVIRONMENT=test` checks and always use Telegram's test API namespace. The normal application does not gain a public checkout route from this test harness.

## 6. Relevant implementation and test files

- `backend/app/orders/payment_service.py` — intent/pre-checkout/capture/refund state machine and service-level runtime guard.
- `backend/app/payments_bot_handlers.py` — test-bot handlers; journals Telegram update identity separately from the charge ID.
- `backend/app/orders/refund_worker.py` — leased refund execution and reconciliation.
- `backend/app/db/payments.py` — intents, transactions, events and refund workflow records.
- `backend/migrations/versions/0012_telegram_stars_payments.py`, `0013_payment_refund_workflow.py`, `0015_payment_ledger_guards.py`, `0016_refund_evidence_delete_guard.py` — schema and evidence protections.
- `backend/tests/test_payment_runtime_safety.py` — service-level token/database isolation and update-ID handling.
- `backend/tests/test_payment_core_integration.py`, `backend/tests/test_payment_refund_worker.py`, `backend/tests/test_payment_ledger_guards.py` — PostgreSQL payment/refund invariants and failure recovery.

Run the unit/safety checks with:

```bash
cd backend
pytest -q tests/test_payment_runtime_safety.py tests/test_payments_test_bot.py
```

Run the payment and refund PostgreSQL suites only against a disposable local, test-named database:

```bash
cd backend
TEST_DATABASE_URL='postgresql+asyncpg://…@localhost:5432/viltara_test' pytest -q tests/test_payment_core_integration.py tests/test_payment_refund_worker.py tests/test_payment_ledger_guards.py
```

Do not use a shared, staging or production database for these tests.

## 7. Remaining release gates

- Manual Telegram Test Server acceptance of invoice → pre-checkout → successful-payment → refund.
- Written product/platform/legal decision for peer-to-peer NFT resale and irreversible delivery.
- Confirmed legal entity, seller/buyer countries, merchant-of-record and settlement model before evaluating any external PSP or seller payouts.
- Explicit frontend/backend HTTP contract review before exposing payment intent/status endpoints.
- Independent review of production credentials, DB roles/grants, backups, operational refund handling and alerting.
- Exact-head CI and PostgreSQL acceptance in the focused Draft PR; no production rollout is part of this work.

## Official provider references checked 2026-11-15

- Telegram Bot Payments for digital goods: https://core.telegram.org/bots/payments-stars
- Telegram Bot API: https://core.telegram.org/bots/api
- Telegram Bot Platform Developer Terms, §6.2 and §6.2.1: https://telegram.org/tos/bot-developers#6-2-digital-goods-and-services
- Telegram Stars Terms: https://telegram.org/tos/stars

These are platform references, not legal advice or approval for the specific NFT resale flow.
