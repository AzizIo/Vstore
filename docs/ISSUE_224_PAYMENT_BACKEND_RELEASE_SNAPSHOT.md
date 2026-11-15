# Issue #224 — release payment backend snapshot

**Snapshot date:** 2026-11-15  
**Implementation base:** `main` at `d29e52182e2d7a8a7cce8fb14544a0e56fa5e279`  
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

This PR adds an authenticated, test-only HTTP contract over the existing ledger:

| Operation | Implemented contract | Authorization / effects |
|---|---|---|
| Create/replay checkout | `POST /api/orders/{order_id}/payment-intent` with `Idempotency-Key` (8–128 chars) | Current authenticated buyer only; service verifies order ownership, XTR, live reserved order, immutable amount and payer identity. A durable PostgreSQL receipt binds the key to the buyer/request. Returns a hosted invoice URL created through Telegram's Test Bot API. |
| Read payment state | `GET /api/orders/{order_id}/payment` | Buyer-owned order only; blocked users can read existing payment state. Returns server-derived status and safe refund summary. |
| Provider callback | No HTTP webhook | Payment confirmation stays in dedicated test-bot long polling. The endpoint never accepts client-supplied success/refund evidence. |

The routes are registered in FastAPI **only** when the test Stars flag is enabled, the environment is local/development/test, the test token differs from `BOT_TOKEN`, and `DATABASE_URL` is a local test-named PostgreSQL database. The service layer repeats its own guards. This PR does not expose these endpoints in production, does not introduce a new provider and does not use a production Telegram API endpoint.

Create response fields: `order_id`, `payment_intent_id`, `payment_status`, `provider`, `amount`, `currency`, `expires_at`, `checkout_url`, and a safe `last_error_code`. Status response fields include `order_id`, `payment_intent_id`, `payment_status`, `provider`, `amount`, `currency`, `expires_at`, `paid_at`, `refunded_at`, `refund_status`, and `last_error_code`. Neither route exposes invoice payloads, raw updates, Telegram/provider charge IDs, payer Telegram IDs, bot tokens or ORM rows.

Public payment statuses: `not_started`, `pending`, `paid`, `refund_pending`, `refunded`, `failed`, `expired`, `unsupported`. Refund status is a separately mapped summary: `none`, `pending`, `processing`, `reconciliation_required`, `manual_review`, `succeeded`. A recorded `pending` intent past its expiry is reported as `expired` without inventing provider success. A conflicting idempotency payload returns `409`; unknown/non-owned order returns `404`; provider/test-runtime unavailability returns `503`; invalid/missing key is rejected by validation. The Mini App still must not treat payment as proof of NFT delivery.

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
- `backend/migrations/versions/0012_telegram_stars_payments.py`, `0013_payment_refund_workflow.py`, `0015_payment_ledger_guards.py`, `0016_refund_evidence_delete_guard.py`, `0017_payment_xtr_invariants.py`, `0018_payment_intent_api_requests.py` — schema and evidence protections.
- `backend/tests/test_payment_api.py` — authenticated routes, idempotency header, safe response and runtime gates.
- `backend/tests/test_payment_runtime_safety.py` — service-level token/database isolation and update-ID handling.
- `backend/tests/test_payment_core_integration.py`, `backend/tests/test_payment_refund_worker.py`, `backend/tests/test_payment_ledger_guards.py` — PostgreSQL payment/refund invariants and failure recovery.

Run the unit/safety checks with:

```bash
cd backend
pytest -q tests/test_payment_api.py tests/test_payment_runtime_safety.py tests/test_payments_test_bot.py
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
- Frontend review of the implemented test-only payment response schema before any future non-test API or production rollout.
- Independent review of production credentials, DB roles/grants, backups, operational refund handling and alerting.
- Exact-head CI and PostgreSQL acceptance in the focused Draft PR; no production rollout is part of this work.

## Official provider references checked 2026-11-15

- Telegram Bot Payments for digital goods: https://core.telegram.org/bots/payments-stars
- Telegram Bot API: https://core.telegram.org/bots/api
- Telegram Bot Platform Developer Terms, §6.2 and §6.2.1: https://telegram.org/tos/bot-developers#6-2-digital-goods-and-services
- Telegram Stars Terms: https://telegram.org/tos/stars

These are platform references, not legal advice or approval for the specific NFT resale flow.
