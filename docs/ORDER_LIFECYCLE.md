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
