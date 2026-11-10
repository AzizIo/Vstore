# Compliant Payments and Escrow — Technical Design

**Status:** research/design proposal only; not approved for implementation.
**Issue:** https://github.com/AzizIo/Vstore/issues/30
**Decision record:** [`docs/adr/0001-compliant-payments-and-escrow.md`](adr/0001-compliant-payments-and-escrow.md)
**Review date for external references:** 2026-11-10
**Product boundary (Issue #48):** The current MVP is non-custodial listing and direct NFT-transfer coordination. No checkout, payment collection, Telegram Stars, TON payment collection, escrow/custody of funds, commissions, refunds, seller payouts, disputes, or buyer-protection claims are available in the MVP. A future guarantee/escrow phase is planned, but its architecture and permissibility are unresolved. This document is background research for that later phase, not an approved implementation specification, and it does not authorize live payment credentials, mainnet contracts, custody of funds or secrets, or enabled paid/completed transitions. It is not legal advice.

## 1. What exists today (baseline)

Historical reference: the original order schema was introduced by
`backend/migrations/versions/0003_orders.py`. The current free-MVP schema is defined by
`backend/app/db/models.py` and the latest migration `0005_free_listings`:

- `OrderStatus` = `pending_payment | cancelled | expired`; the DB check constraint
  rejects any other value. `paid`, `completed`, `failed`, `refunded` are
  intentionally absent.
- Current `Order` rows store `listing_id`, `buyer_id`, `seller_id`, `idempotency_key`,
  `expires_at`, lifecycle status and timestamps. They do not store a price or currency;
  migration `0005_free_listings` removed the legacy display-only columns.
- `OrderEvent` is append-only with `from_status`, `to_status`, `actor_type`
  (`buyer | system`) and `actor_id`.
- Creating an order atomically reserves the listing (`active -> reserved`);
  cancelling or expiring releases it. An in-process worker expires pending orders
  with `SKIP LOCKED` row locks.
- Historical payment proposals below discuss hypothetical amount/currency snapshots. They
  do not describe the current schema or authorize payment implementation.
- `app/orders/payment.PaymentAdapter` defines `create_intent(order_id)` and
  `verify_notification(payload, signature)` returning `PaymentIntent` /
  `VerifiedPayment` dataclasses. It has no implementation, is not imported by
  routes, and stores no provider data.

Everything below is a proposal that extends this baseline **without changing the
meanings** of the existing three states.

## 2. Proposed order and payment state machine

### 2.1 Proposed `OrderStatus` additions

`pending_payment (existing) -> paid -> delivery_pending -> completed`,
plus terminal `cancelled (existing)`, `expired (existing)`, `refunded`, `failed`,
and a hold state `disputed`.

Names are indicative; the ADR gate is that all source transitions are enforced in
one function and mirrored by DB check constraints + `order_events`. The existing
`ck_orders_status` constraint and `ck_order_events_statuses` are widened by a new
Alembic migration only when Phase 1 is accepted.

### 2.2 State transition table

| From | To | Trigger (trusted server event) | Actor type | Guard |
|---|---|---|---|---|
| — | `pending_payment` | `POST /api/orders` reserves listing | `buyer` | listing active, seller ≠ buyer, asset verified |
| `pending_payment` | `paid` | verified Stars `successful_payment` matching stored invoice | `provider` | invoice payload = order id; amount and currency equal snapshot; charge id unseen |
| `pending_payment` | `cancelled` | authenticated buyer cancels | `buyer` | order belongs to buyer |
| `pending_payment` | `expired` | expiration worker | `system` | order or listing TTL reached |
| `paid` | `refunded` | verified Stars refund (full refund before delivery) | `provider` | charge refunded at provider; item not delivered |
| `paid` | `delivery_pending` | seller marks delivery started (after ownership re-check) | `seller` | asset still owned by seller at check time |
| `delivery_pending` | `completed` | server-side post-transfer TEP-62 owner check passes | `system` | owner == buyer's verified wallet |
| `delivery_pending` | `disputed` | buyer opens dispute before completion window closes | `buyer` | within dispute window |
| `disputed` | `refunded` | admin decision + verified refund | `admin` + `provider` | dispute closed in buyer's favor |
| `disputed` | `completed` | admin decision | `admin` | dispute closed in seller's favor |
| `paid` / `delivery_pending` | `failed` | delivery deadline exceeded / irrecoverable transfer failure | `system` | deadline passed; refund initiated separately |

Rules:

- `buyer` and `system` may never move an order to `paid` or `completed` from a
  client request; only `provider` (paid/refunded) and a verified server-side
  ownership observation (`system`, completed) or an authorized `admin` action may.
- Every transition writes `order_events` in the same transaction as the state
  change. Duplicate provider notifications are idempotent no-ops keyed by the
  provider reference.
- A listing moves `reserved -> sold` only on `completed`; `reserved -> active`
  on `cancelled`/`expired`/`refunded` (with listing expiry rules).

### 2.3 Sequence diagram — Stars checkout (Phase 1)

```text
Buyer        Mini App             API                         Telegram
 |  select listing  |             |                             |
 |----------------->|  POST /api/orders (Idempotency-Key)        |
 |                  |------------>| create order (pending_payment)
 |                  |             | reserve listing              |
 |                  |<------------| 201 order (expires_at)       |
 |  pay             |             |                             |
 |----------------->|  POST /api/orders/{id}/payment-intent      |
 |                  |------------>| verify order XTR + window    |
 |                  |             | create invoice link          |
 |                  |             |------------------------------>|
 |                  |<------------| {invoice_url}                |
 |  open invoice    |             |                             |
 |-------------------------------------------------------------->|
 |                  |             |   update: pre_checkout_query |
 |                  |             |<------------------------------|
 |                  |             | answerPreCheckoutQuery ok    |
 |                  |             |------------------------------>|
 |                  |             |   update: successful_payment |
 |                  |             |<------------------------------|
 |                  |             | verify secret token + payload
 |                  |             | match invoice/amount/order   |
 |                  |             | ledger insert (unique charge) |
 |                  |             | order: paid + order_event     |
 |                  |             | acknowledge 200             |
```

### 2.4 Sequence diagram — delivery, completion and the (deferred) escrow variant

```text
                     Phase 1/2 (no escrow)               Phase 3+ (testnet escrow, deferred)
Seller  --NFT transfer--> Buyer wallet        Seller  --deposit--> Escrow contract
API     --TEP-62 owner check--> verify        API     --watcher confirms deposit-->
API     --complete order--> order_events      Buyer   --pays (Stars or reviewed flow)-->
Admin   --manual payout ledger entry-->       Admin   --signs release decision-->
                                              Contract--transfer NFT--> Buyer wallet
```

## 3. Threat model and trust boundaries

| # | Threat | Boundary crossed | Impact | Mitigation |
|---|---|---|---|---|
| T1 | Forged `successful_payment` webhook | internet → API | goods delivered for free | `setWebhook` `secret_token`; reject any request without matching header; verify payload references a stored, unexpired invoice and exact amount/currency/payer |
| T2 | Replayed or duplicated payment notification | provider → API | double delivery / double ledger credit | unique `(provider, provider_reference)` in ledger; transition function idempotent; duplicate events acknowledged but no-op |
| T3 | Amount tampering or client-side paid claim | Mini App → API | underpayment | amount is read from the stored order snapshot, never the request; no public endpoint sets `paid` |
| T4 | Invoice/order mismatch (pay order A, complete order B) | provider payload → order | wrong item delivered | invoice payload must equal order id; compare order snapshot fields, not request fields |
| T5 | Cross-tenant IDOR on payment-intent/refund endpoints | authz | paying/refunding another user's order | derive user from JWT; scope every query by buyer/seller; 404 for foreign resources |
| T6 | Order race: two buyers pay for one reserved asset | concurrency | double sale | partial unique index on listing and order reservation already prevents this; `paid` only allowed while the same order holds the reservation |
| T7 | Seller takes payment then never transfers (no escrow) | product trust | buyer loses money | manual dispute path, seller trust signals, refund window; documented limitation — product must not claim guaranteed delivery |
| T8 | Seller transfers NFT to wrong address | product | asset loss | buyer's destination wallet must be a **verified** wallet bound to the buyer; show exact address before transfer |
| T9 | Refund race with delivery | provider + chain | NFT delivered after refund | block refund once delivery observed; complete only after chain confirmation; explicit `refunded` terminal propagation |
| T10 | Key/secret compromise (bot token, webhook secret) | config → API | forged provider events | secrets only in environment, never in repo/DB; rotation runbook; readiness gate (already partly in place) |
| T11 | Escrow contract admin key compromise (Phase 3+) | chain | funds/assets stolen | multisig/timelock; least-privilege roles; independent audit before mainnet |
| T12 | Reentrancy / failed message handling in escrow contract (Phase 3+) | chain | stuck or stolen funds | adhere to TON message patterns, bounce handling, idempotent op codes, exhaustive failure matrix on testnet |
| T13 | Stars conversion / payout account compromise | operations | payout theft | ledger reconciliation, dual control for manual payouts, audit log of admin actions |
| T14 | Log leakage of secrets or personal data | logging | privacy / account takeover | never log initData, JWTs, charge ids in full, wallet signatures |

Trust boundaries (who must be trusted, and for what):

- **Telegram**: authenticity and delivery of payment updates; it does not
  guarantee the marketplace's own fulfilment.
- **TON Center / indexer**: point-in-time ownership data; not trustless, may lag
  or be wrong — treat as untrusted-verified input with re-checks.
- **Server**: sole authority for payment/order transitions; the wallet
  private keys of users are never held by it.
- **Operator/admin**: manual payouts and dispute decisions — logged, dual-control.
- **Escrow contract (future)**: becomes a trusted component for custody; its admin
  keys and upgrade path are the highest-value targets.

## 4. Data model proposal

New tables are proposals; existing tables are extended with constraints matching
the state table in §2.2. They are not created until Phase 1 is accepted.

### 4.1 `payment_transactions`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `order_id` | UUID FK orders | `ondelete=RESTRICT`, indexed |
| `provider` | text enum (`telegram_stars`, later `ton`) | |
| `provider_reference` | text | charge id; **unique per provider** |
| `kind` | enum (`payment`, `refund`) | |
| `amount` | numeric(24,9) | must equal order snapshot for payment |
| `currency` | `PriceCurrency` | snapshot |
| `status` | enum (`pending`, `succeeded`, `failed`, `refunded`) | |
| `raw_reference_hash` | text | hash of provider payload for audit without storing secrets |
| `created_at`, `updated_at` | timestamptz | |

Unique index: `(provider, provider_reference)` for replay protection.
Check: `amount > 0`.

### 4.2 `seller_payouts` (manual ledger, Phase 1)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `order_id` | UUID FK orders | one payout row per completed order |
| `seller_id` | UUID FK users | |
| `gross_amount`, `fee_amount`, `net_amount` | numeric(24,9) | currency = order snapshot |
| `status` | enum (`pending`, `recorded`, `paid_out`, `reversed`) | |
| `recorded_by` | UUID FK users (admin) nullable | |
| `paid_at`, `created_at`, `updated_at` | timestamptz | optional off-platform tx reference (hashed) |

### 4.3 `disputes`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `order_id` | UUID FK orders | at most one open dispute per order |
| `opened_by` | UUID FK users | buyer |
| `reason` | text (bounded) | |
| `status` | enum (`open`, `resolved_buyer`, `resolved_seller`, `cancelled`) | |
| `resolved_by` | UUID FK users nullable | admin |
| `resolved_at`, `created_at` | timestamptz | |

### 4.4 Order table deltas

Add nullable `paid_at`, `completed_at`, `refunded_at`; extend `ck_orders_status`
and `ck_order_events_statuses` to the widened enum; allow `actor_type` values
`buyer | seller | system | provider | admin`. Bump uniqueness: one open dispute
per order via partial unique index. Keep the existing idempotency and listing
uniqueness constraints unchanged.

## 5. Provider integration boundary

### 5.1 Contract (`PaymentAdapter`, extended)

Existing protocol plus confirmed-notification result already present; proposed
additions:

```text
create_intent(order) -> PaymentIntent        # invoice link + provider ref stored
verify_notification(payload, signature) -> VerifiedPayment | None  # None = ignore/no-op
refund(payment_ref, amount) -> RefundResult  # server-initiated, admin-triggered only
reconcile(order_id) -> ProviderStatus        # periodic lookup, idempotent
```

`verify_notification` **must not raise on unrelated updates**; it returns `None`
so the webhook handler stays 200 for updates it does not own. A signature/secret
mismatch is a hard 401.

### 5.2 Telegram Stars implementation notes (verified 2026-11-10; re-check before launch)

- Invoice via Bot API `createInvoiceLink` with `currency=XTR` and a server-generated
  payload equal to the order id; amount comes from the persisted order snapshot.
- Answer `pre_checkout_query` within Telegram's 10-second deadline, only after
  re-reading the order (status, amount, seller and buyer); never answer "ok" blind.
- A pre-checkout approval is **not proof of payment**. Deliver nothing until a
  matching `successful_payment` update is received and verified.
- Store `telegram_payment_charge_id` as the unique provider reference; hash or
  redact it in logs.
- For webhooks, configure `setWebhook.secret_token` and verify
  `X-Telegram-Bot-Api-Secret-Token` with a constant-time comparison. The current
  bot uses polling; do not mix polling and webhook modes for the same bot.
- Refunds use `refundStarPayment` with the stored charge id; enforce the guards
  in §2.2 and record the refund as a `payment_transactions` row of kind
  `refund`.
- Before any live release, the bot/Mini App must provide `/paysupport` for
  payment disputes, an accessible `/terms` entry point and `/support` (or an
  equally clear contact method).
- Current Telegram terms state a reward equivalent of USD 0.013 per Star; Stars
  may take up to 21 days to become available for rewards. Fragment processes
  rewards and may not be available in some countries. These values and
  eligibility are controlled by Telegram/Fragment, can change, and must not be
  advertised as guaranteed seller payout rates or schedules.
- Telegram's terms discourage real-time sales of virtual items with inherent
  value that cannot be reclaimed, frozen or rescinded after a successful dispute
  or chargeback. A transferred TON NFT may be irreversible; this is a launch
  blocker, not merely a UX caveat.

### 5.3 TON future adapter (Phase 3+, testnet only)

- The adapter is an isolated module `payments/ton` that talks to a configured
  RPC/indexer; no secrets in the app; any wallet used for escrow is funded only on
  testnet during the PoC.
- Finality policy: require the configured confirmation depth/atomic confirmation
  appropriate to the flow before any order transition.
- The escrow contract is described at interface level only in this design; its
  actual code lives in a separate reviewed repository/directory when Phase 3
  starts.

## 6. Reconciliation, idempotency and failure recovery

- **Idempotency keys**: order creation (existing) and payment-intent creation
  (new) both accept `Idempotency-Key`; a unique `(order, key)` row backs it.
- **Reconciliation job**: every N seconds (mirrors the existing expiration worker
  pattern with `SKIP LOCKED`) scan orders in `paid` but not `delivery_pending` /
  not completed past deadline, and re-query the provider for charge status; correct
  classifications written as `system` events. Webhook is the fast path; reconciliation
  is the safety net.
- **Replay protection**: unique provider references; transition function rejects
  any event whose target state is already set.
- **Refunds**: only via verified provider refund; idempotent by refund reference;
  a refund for a delivered order is blocked (T9).
- **Worker failure**: mirror the fix in `d997321` — the worker survives transient
  errors and retries next poll; worth adding a test that a failure does not kill
  the loop.
- **Recovery**: all state is in PostgreSQL with an append-only event log; a stuck
  payment is resolvable by reading provider status and appending a `system` event.
- **Limits/fees**: enforce programmatic maximums per invoice and per-order; keep
  fee calculation in one server-side function validated by tests.

## 7. Test strategy

### 7.1 Phase-1 automated matrix (backend)

1. Unauthenticated payment-intent request rejected.
2. Payment intent for a non-`XTR` order rejected; for a `TON` listing rejected.
3. Payment intent for another user's order → 404.
4. Payment intent after TTL → 409, order expired via the worker.
5. Duplicate payment-intent request with same idempotency key → same invoice ref.
6. Webhook without/with wrong secret token → 401.
7. Webhook `successful_payment` for unknown payload → no state change, 200.
8. Amount/currency mismatch → no state change, 200 (logged).
9. Valid payment → `paid` + exactly one `payment_transactions` row + one event.
10. Replayed valid payment → still one row, no second event.
11. Refund before delivery → `refunded`, ledger `refund` row.
12. Refund attempt after delivery observed → blocked 409.
13. Concurrent payment webhooks for one order → single `paid`, single ledger row
    (PostgreSQL integration test).
14. Buyer/any client cannot POST a paid/completed claim (no such endpoint;
    negative test on the state function).
15. Manual payout: ledger row created once on `completed`, admin-only, reversed
    status path tested.

### 7.2 Integration and E2E

- PostgreSQL integration tests (existing harness, `TEST_DATABASE_URL`) for
  constraints: status check constraints, partial indexes, unique provider refs,
  concurrent transitions.
- A fake `PaymentAdapter` test double for API/worker tests; the real Telegram
  adapter only against a local fake webhook in test env (no live bot token).
- Frontend: invoice-open and polling states with mocked API; no real payment in UI
  tests.
- Bot commands: `/paysupport`, `/terms` and support contact are present and
  tested before a live checkout is enabled.

### 7.3 Testnet-only escrow PoC plan (Phase 3)

- Environment: TON testnet only; disposable wallets funded from a faucet;
  feature flag hard-disabled in any non-test config; build artifacts tagged
  `poc`.
- Scope: deposit, release on admin-accepted evidence, refund path, dispute/hold.
- Failure matrix to reproduce: seller never deposits; seller deposits then
  disappears; buyer pays twice; release attempted before deposit; refund attempted
  after release; message bounce; contract timeout; malformed op; reentrancy-style
  re-entry of release; watcher outage and recovery.
- Deliverables: PoC report with tx hashes/evidence, and an explicit list of defects
  before any mainnet proposal.
- Exit criteria: every failure path terminates deterministically and no path leaves
  funds or assets stuck without an operator action.

## 8. Production blockers and required external reviews

The following must be closed **before** production, not necessarily before Phase 1
code:

1. Re-verify current Telegram Stars terms, fees, payout conversion, hold period
   and refund window from live docs; capture exact text and date in the PR.
2. Written legal review of peer-to-peer NFT resale, marketplace classification,
   money-transmission/custody questions, VAT/sales tax, consumer protection and
   dispute obligations for target jurisdictions.
3. KYC/AML obligations for sellers receiving payouts, and sanctions screening
   implications.
4. Operational runbook for manual payouts with dual control, reconciliation and
   audit logging; named responsible operator(s).
5. Independent security review of the Stars integration (webhook authenticity,
   update verification) and the escrow contract threat model before Phase 3.
6. Strict separation of mainnet and testnet configuration; fail-closed defaults;
   no live secrets in development environments.
7. Product copy review: no guarantee/escrow/automatic-delivery claims until the
   corresponding phase is implemented, tested and reviewed.
8. Written platform/legal assessment that this peer-to-peer NFT resale flow is
   acceptable under current Telegram/store rules, including the warning against
   real-time sale of irreversible virtual items; define a credible refund/
   compensation procedure for the case where an NFT cannot be reclaimed.
9. Written review of the TPA-owner Stars balance and Fragment reward model:
   seller settlement is not automatic, reward availability may be delayed up to
   21 days, and Fragment eligibility varies by country. Do not promise a fixed
   cash conversion or payout date.
10. Implement and test the required `/paysupport`, `/terms` and support contact
    surfaces before any live Stars checkout.

## 9. Open questions for maintainers

1. Is a manual-payout Phase 1 acceptable operationally, or must payout automation
   gate the launch?
2. What product, provider, platform, legal and security gates must be satisfied before a
   separately approved paid/guaranteed phase can be designed or implemented?
3. Preferred dispute window length and whether it is seller- or admin-triggered?
4. Which jurisdiction's legal review is the primary target before Phase 4?

## 10. References

- Telegram Stars and digital-goods checkout: https://core.telegram.org/bots/payments-stars
- Telegram Bot Platform Developer Terms, §6.2 (Stars, refunds, reward value/delay,
  Fragment and irreversible virtual-item disputes):
  https://telegram.org/tos/bot-developers#6-2-digital-goods-and-services
- Telegram Bot Platform Developer Terms, §7 (TON / TON Connect requirements):
  https://telegram.org/tos/bot-developers#7-blockchain-integration
- Bot API payments: https://core.telegram.org/bots/api#sendinvoice
- Bot API `setWebhook` (secret token): https://core.telegram.org/bots/api#setwebhook
- Bot API refunds: https://core.telegram.org/bots/api#refundstarpayment
- Mini App rules: https://core.telegram.org/bots/webapps
- TEP-62 NFT standard: https://github.com/ton-blockchain/TEPs/blob/master/text/0062-nft-standard.md
- TON NFT how it works: https://docs.ton.org/contracts/standard/tokens/nft/how-it-works
- Prior asset audit: [`docs/ASSET_INTEGRATION_AUDIT.md`](ASSET_INTEGRATION_AUDIT.md)
- Order lifecycle: [`docs/ORDER_LIFECYCLE.md`](ORDER_LIFECYCLE.md)

---

This document is a technical design, not an implementation, a security audit, or
legal advice. All real-value paths require the reviews listed in §8 before launch.
