# Telegram Stars refund worker — threat model

## Scope and deployment boundary

This worker is deliberately limited to Telegram Stars test charges. It requires all of:

- `ENVIRONMENT=local|development|test`
- `TELEGRAM_STARS_TEST_ENABLED=true`
- a dedicated `TELEGRAM_STARS_TEST_BOT_TOKEN`
- `TELEGRAM_STARS_REFUND_WORKER_ENABLED=true`

It runs as a standalone process with `python -m app.payments_refund_worker`. It is not started by the FastAPI lifespan or the production bot. Public checkout, production tokens, production payment flows and TON escrow remain out of scope.

## Assets and trust boundaries

- Buyer / Telegram account: may replay updates, use an old invoice, pay the same invoice twice, or submit a payment whose payer/amount does not match the order.
- Telegram Bot API: trusted source for successful payment evidence and provider transaction history, but network results can be delayed or unavailable.
- PostgreSQL: source of truth for order/payment state, charge uniqueness, refund jobs, leases and the append-only event journal.
- Refund worker: privileged actor that may call `refundStarPayment`; provider calls are always outside DB transactions.
- TON delivery observer: sole authority for marking an NFT transfer completed. Payment and refund workers never change order delivery status.

## Controls by threat

| Threat / scenario | Control | Residual risk |
|---|---|---|
| Repeated `successful_payment` update | Unique provider event ID plus payload digest; order row lock; unique Telegram charge ID. Same evidence is idempotent; changed evidence conflicts. | A provider delivery outage can delay ledger persistence; support/reconciliation is required. |
| Two charges on one reusable invoice | One charge may capture the pending intent; every additional charge gets its own transaction and unique refund job. | User can temporarily have more than one charge captured by Telegram until refund succeeds. |
| Payment after order expiry | Success handler records the incoming charge as `refund_pending` rather than paid; job is created in the same DB transaction. | If the transaction is older than the provider history retention/page limit, it requires manual review. |
| Wrong amount, payer or currency | Compare against immutable intent and current buyer Telegram ID; mismatch is not captured for delivery and is queued for refund. | Refund can fail if Telegram account is unavailable or provider rejects it. |
| Cancellation of a paid order | Order service locks order/payment rows, changes captured transactions to `refund_pending`, writes an event and inserts a unique job atomically. | Cancellation does not mean the external refund is complete. UI/support must show refund pending until provider evidence is confirmed. |
| Seller loses NFT ownership | Ownership invalidation cancels affected reserved orders and queues captured Stars charges in the same DB transaction. | On-chain ownership data may be delayed; delivery still uses the independent observer. |
| Duplicate worker / concurrent request | Unique job per payment transaction, PostgreSQL `FOR UPDATE SKIP LOCKED`, per-claim token and lease. Stale workers cannot finalize another worker's claim. | A paused worker can outlive its lease; token checks protect DB finalization. |
| Crash after provider refund succeeds but before DB commit | Before request, persist `request_started_at`; after restart scan Telegram Stars history for the exact charge ID and exact recipient. A verified refund finalizes ledger/job without a second API request. | If history is incomplete/unavailable, job stays `reconciling` and eventually moves to manual review; it does not blindly repeat the refund request. |
| Repeat refund after success | Refunded payment status is terminal; `record_stars_refund_result` is idempotent; successful history record finalizes the job. Telegram also documents refund transaction IDs as coinciding with the original charge ID. | Bot API does not expose a caller-supplied idempotency key for `refundStarPayment`; this worker does not rely on a provider duplicate-rejection guarantee. A request with an ambiguous outcome is never automatically resent; exact transaction-history evidence or manual review is required. |
| Payment incorrectly completes NFT delivery | Payment service mutates payment records only. `prepare_delivery` checks the paid intent; `OrderStatus.COMPLETED` is written only by the delivery observer after transfer evidence. Refund worker never imports or updates order status. | Existing delivery observer/provider integrity remains a separate high-impact dependency. |

## Refund state machine

- Payment transaction: `captured -> refund_pending -> refunded`.
- Refund job: `pending -> processing -> succeeded`.
- Uncertain provider result: `processing -> reconciling -> processing`, with bounded history scans and retry delay.
- Invalid evidence, exhausted reconciliation, or provider rejection: `manual_review`.
- Each job has a unique transaction FK, claim token, lease expiry, attempt counter and next-attempt timestamp.
- `request_started_at` is intentionally retained after ambiguous provider outcomes. The worker checks history and never automatically repeats an ambiguous refund request. This is a safety-over-availability tradeoff.

## Database and operational safeguards

1. Migration `0013_payment_refund_jobs` is additive and backfills pre-existing `refund_pending` transactions. It is not executed by this change against any live database.
2. The migration is a schema change and must be reviewed by the payment-core schema owner before merge.
3. Integration tests use only `TEST_DATABASE_URL` and synthetic users/orders. They refuse non-PostgreSQL test URLs.
4. Do not place production bot credentials in these variables. Do not enable the worker in production.
5. Monitor counts/age of `pending`, `reconciling` and `manual_review` jobs. Manual review must verify Telegram transaction history before any operator action.
6. The immutable PaymentEvent journal stores identifiers and hashes, not raw Telegram updates, access tokens or private keys.

## Remaining risks and release blockers

- Telegram may delay or temporarily omit a newly created refund from transaction history. The worker therefore reconciles instead of interpreting a missing row as proof of failure.
- History pagination is bounded. An incomplete scan is never treated as proof that a refund did not occur.
- A process can crash after persisting `request_started_at` but before sending the API request. The job may reach manual review rather than risk a duplicate refund.
- `getStarTransactions` is a provider-history reconciliation mechanism, not a transactional distributed lock with Telegram.
- NFT delivery is difficult to reverse. Telegram's own Bot API warns of buyer chargebacks that can debit Stars from the bot balance; delivery/refund policy and platform compliance need a separate decision.
- This PR does not authorize live checkout, seller payouts, custody, escrow or production deployment. Telegram policy/legal classification for peer-to-peer NFT resale remains a separate blocker.
