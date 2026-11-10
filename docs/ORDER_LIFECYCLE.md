# Buyer order lifecycle

Orders can only be created from an `ACTIVE` listing. Creating an order atomically snapshots
the listing's amount and currency, changes the listing to `RESERVED`, and appends the initial
order event. A buyer-scoped `Idempotency-Key` prevents retries from creating a second order;
reusing that key for a different listing conflicts.

## Fresh ownership re-check before reservation

Persisted `nft_assets.owner_id` and `verification_status` can be stale after an on-chain
transfer, so a reservation requires more than those columns. Order creation runs in two
phases:

1. **Snapshot (no locks).** Read the listing, asset and the seller's verified wallets on the
   asset's network from server-side data only. Nothing supplied by the buyer beyond the
   listing id and the idempotency key is trusted. The read transaction is released before any
   network call.
2. **Provider check (outside any transaction).** Run the existing TEP-62 verifier for each
   verified seller wallet. No database transaction or row lock is held while the TON provider
   is queried.
3. **Revalidate and reserve (single locked transaction).** Lock the buyer, listing, asset and
   the wallet that proved ownership, then compare every field against the snapshot. The
   listing must still be `ACTIVE`, unexpired, not the buyer's own, and belong to a verified
   TON NFT owned by the same seller.

Outcomes:

| Situation | Result | State change |
|---|---|---|
| Ownership verified, listing unchanged | order created, listing `RESERVED` | order + event + notifications |
| `OWNER_MISMATCH` from the provider | `OrderConflict`, HTTP 409 | asset `STALE`, listing `EXPIRED`, any pending order `CANCELLED` |
| Provider unavailable | `OrderVerificationUnavailable`, HTTP 503 | none — the outage is not proof of lost ownership |
| Provider inconclusive (`NOT_FOUND`, `UNSUPPORTED`, `INVALID_DATA`) | `OrderConflict`, HTTP 409 | none — unconfirmed is not the same as transferred |
| Asset network differs from the verifier's configured network | `OrderVerificationUnavailable`, HTTP 503 | none — the wrong indexer is never queried |
| Listing/asset changed during the check | `OrderConflict`, HTTP 409 | none |
| Verified wallet unbound during the check | `OrderConflict`, HTTP 409 | none |
| Same idempotency key, same listing | returns the existing order id | none; the provider is not called again |

Only an affirmative `OWNER_MISMATCH` marks the asset `STALE`, because only that is evidence the
seller no longer owns the NFT. An inconclusive provider answer fails closed without rewriting
asset state, so a provider quirk cannot destroy a valid listing.

### Invariants added after review

**Ownership can be lost while another buyer already holds the reservation.** The verifying
request then must not leave the listing `RESERVED` with a live pending order, because
cancellation and the expiry worker would otherwise release it back to `ACTIVE` and re-expose an
NFT the seller no longer owns. Losing ownership therefore closes the dependent order
(`CANCELLED`, with an event and notifications for both parties) and moves the listing to
`EXPIRED` in the same transaction, before the 409 is returned.

**`_release_listing` refuses to re-expose an unsellable asset.** The catalog filters on listing
status alone, so a stale or unverified asset — or one whose owner no longer matches the seller —
forces `EXPIRED` instead of `ACTIVE` on every release path.

**Lock order is shared with publication.** `create_order` locks `listing -> wallet -> asset`,
identical to `publish_listing`. Rows of one asset are reachable from both paths concurrently
(a buyer reserving the active listing while the seller publishes a second draft), so diverging
orders deadlock. A regression test reproduces the deadlock by reserving and publishing at once.

The stale-asset transition is committed before the 409 is returned, so the failed reservation
is durable rather than rolled back with the request.

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

`POST /api/orders` resolves the TON NFT verifier from the configured network through the same
dependency used by listing publishing, so reservation and publication share one ownership
check implementation.

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
