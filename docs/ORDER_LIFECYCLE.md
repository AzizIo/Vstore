# Buyer order lifecycle

Orders can only be created from an `ACTIVE` listing. Creating an order atomically snapshots
the listing's amount and currency, changes the listing to `RESERVED`, and appends the initial
order event. A buyer-scoped `Idempotency-Key` prevents retries from creating a second order;
reusing that key for a different listing conflicts.

The implemented state transitions are:

```text
pending_payment -> cancelled  (authenticated buyer)
pending_payment -> expired    (server expiration worker)
```

`paid`, `completed`, `failed`, and `refunded` are intentionally not implemented: this service
does not accept client payment claims, move funds, or transfer assets. Pending orders expire
after `ORDER_PENDING_TTL_SECONDS` (default 900). The API process runs an expiration worker
every `ORDER_EXPIRATION_POLL_SECONDS` (default 30); row locks with `SKIP LOCKED` let multiple
API workers safely share the work. Cancellation or expiration reactivates a reserved listing
unless the listing itself has expired.

Order events are append-only through the application service and include the previous/next
status, actor type, optional actor identity, and timestamp. Buyers can list and inspect their
purchases and cancel their pending orders. Sellers can list sales and see their statuses; they
cannot cancel a buyer's order.

## Future payment adapter boundary

`app.orders.payment.PaymentAdapter` is the trusted server-side boundary for a future payment
provider. A provider implementation must create an intent from the persisted order snapshot
and independently verify provider notifications before any trusted payment-state transition is
introduced. The order and its listing reservation must be reconciled atomically. TON escrow
contract deployment, on-chain payment collection, NFT transfer, refunds, and Telegram Stars
are out of scope until separately designed, security-reviewed, and validated on testnet.

The payment/escrow decision and its state machine are recorded in
[`docs/adr/0001-compliant-payments-and-escrow.md`](adr/0001-compliant-payments-and-escrow.md)
and [`docs/PAYMENTS_ESCROW_DESIGN.md`](PAYMENTS_ESCROW_DESIGN.md).


## Telegram notifications and delivery guarantees

Lifecycle notifications are written to `telegram_notification_outbox` in the same database
transaction as each order transition. The optional Compose bot service consumes this durable
queue; run `docker compose --profile bot up --build` with `BOT_TOKEN` configured.

Set `TELEGRAM_MINI_APP_URL` to the direct Telegram Mini App link, for example
`https://t.me/<bot_username>/<app_short_name>`. Each notification appends a
`startapp=order_<order-id>` parameter. Without this setting, messages are still delivered but
will not contain an in-app deep link.

The worker uses PostgreSQL row locks with `SKIP LOCKED`, a claim lease, and unique event
deduplication keys so multiple bot workers can safely share the outbox. Transient failures are
retried with exponential backoff (5 seconds up to 1 hour by default); Telegram flood-control
`retry_after` values are respected but capped. Permanent recipient/request failures and events
that exhaust the configured attempt count are retained as `failed` with the last error.
Tune with `NOTIFICATION_POLL_SECONDS`, `NOTIFICATION_BATCH_SIZE`,
`NOTIFICATION_CLAIM_LEASE_SECONDS`, `NOTIFICATION_MAX_ATTEMPTS`,
`NOTIFICATION_RETRY_BASE_SECONDS`, and `NOTIFICATION_RETRY_MAX_SECONDS`.

Telegram's `sendMessage` method does not expose a client idempotency key. The outbox guarantees
one persisted event per lifecycle transition and prevents concurrent workers from claiming the
same live lease; delivery is therefore at-least-once. A process crash after Telegram accepted a
message but before the database records success can still result in a duplicate after the lease
expires. Delivered and failed rows remain available for operational inspection; monitor pending
age, attempt counts, and failed rows in the outbox table.

Messages contain only the order reference, lifecycle status, amount/currency, and Mini App link.
They explicitly state that payment is not enabled and never claim that payment was received or an
NFT was transferred.
