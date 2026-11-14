# TON escrow backend API — Draft

**Status:** isolated testnet-only backend prototype. The router is intentionally not mounted in `backend/app/main.py`; no public checkout or TON signing is enabled.

This API follows `docs/TON_ESCROW_SHARED_INTERFACE.md`. It defines transport semantics only. Numeric opcodes, cell layouts, BOCs, state-init/address derivation and real TON Connect messages remain unavailable until the contract ABI is reviewed and approved.

## Safety boundary

- All authenticated actors come from the verified API session. Wallet IDs are resolved server-side to verified testnet wallet records; client wallet addresses are never authoritative.
- `available_actions` is derived from the authenticated participant and current server-side state. Sellers never receive buyer-only `create_deal_intent` actions, and buyers never receive seller-only actions.
- All amounts are integer nanotons encoded as decimal strings. The seller's listing price is snapshotted as the immutable deal principal.
- A listing intent is an off-chain seller preparation record. It does not claim that the NFT is held by escrow.
- Creating a buyer deal intent locks one buyer, seller, listing key, collection, NFT item, principal, network and unique deal salt into one immutable deal record. ORM guards and a PostgreSQL trigger reject later changes to these terms.
- Deal-scoped deployment is not prepared from a seller-only listing intent.
- The observer stores raw evidence separately from accepted contract events. Accepted NFT deposit/delivery/return events must match both the snapshotted collection and item; raw NFT transfer observations cannot advance canonical deal state.
- Non-final, unverified or unmatched events remain pending and pin the durable cursor. The same provider page is re-queried until it can be promoted or reconciled.
- Event identity is a SHA-256 key over network, transaction hash, message hash (or event index), trace, phase and attempt. Logical time, deal salt, collection/item and contract-state facts remain correlated payload fields; compatible pending evidence may be enriched, while conflicting values are moved to manual review. A provider must keep the identity tuple stable between non-final and final scans.
- No contract adapter/provider is configured. All transaction preparation, wallet-reference submission and settlement actions fail closed with HTTP 503.
- No production/mainnet routes, real TON transfers, production migrations or observer autostart are enabled.

## Endpoints

All routes below are under `/api/escrow` when the isolated router is mounted in a future reviewed integration.

| Method | Path | Scope / behavior |
|---|---|---|
| POST | `/listing-intents` | Seller creates an escrow intent from `asset_id`, verified `seller_wallet_id` and positive `price_nano`. A normal marketplace draft listing is created/reused; publication/moderation is not bypassed. |
| GET | `/marketplace/listing-intents` | Buyer discovery. Returns only active published listings with safe public listing projection. |
| GET | `/listing-intents` | Seller-scoped listing-intent page. |
| GET | `/listing-intents/{listing_id}` | Seller detail, or public detail only while the underlying listing is active. |
| POST | `/deals` | Buyer creates a deal intent using `listing_id` and verified `buyer_wallet_id`. The listing intent is single-sale reserved under a row lock and database uniqueness constraint. |
| GET | `/buyer/deals` | Current buyer's deals. |
| GET | `/seller/deals` | Current seller's deals. |
| GET | `/deals/{deal_id}` | Participant-only deal projection. Other users receive 404. |
| POST | `/deals/{deal_id}/prepare/create-deal-escrow` | Seller-only, deal-scoped deployment preparation; currently 503 until ABI approval. |
| POST | `/deals/{deal_id}/prepare/deposit-nft` | Seller-only, only in `awaiting_nft`; ownership is rechecked; currently 503. |
| POST | `/deals/{deal_id}/prepare/funding` | Bound buyer only, only in `awaiting_buyer_funds`; currently 503. |
| POST | `/deals/{deal_id}/prepare/accept` | Bound buyer only, only in `funded_review`; currently 503. |
| POST | `/deals/{deal_id}/prepare/dispute` | Bound buyer only, only in `funded_review` or `delivered_dispute_window`; currently 503. |
| POST | `/deals/{deal_id}/prepare/nft-return` | Bound buyer only in `disputed`; buyer ownership is rechecked; currently 503. |
| POST | `/deals/{deal_id}/prepare/withdraw-unsold-nft` | Seller only after `expired`; escrow ownership is rechecked; currently 503. |
| POST | `/wallet-references` | Currently 503. A client-supplied hash/BOC is never accepted as evidence or state. |
| GET | `/seller/balance` | Returns unavailable; this design does not define a withdrawable seller balance. |
| GET | `/seller/withdrawals` | Empty page until an approved settlement/withdrawal model exists. |
| POST | `/withdrawals` | Legacy generic withdrawal is blocked with 503. |

Every mutating request requires an `Idempotency-Key`. Deal/listing creation stores the request hash and returns the original resource on an exact replay; a changed payload under the same key conflicts.

## DTOs

Listing intent creation request:

```json
{
  "asset_id": "UUID",
  "seller_wallet_id": "UUID",
  "price_nano": "2500000000"
}
```

Buyer deal intent request:

```json
{
  "listing_id": "UUID",
  "buyer_wallet_id": "UUID"
}
```

Listing and deal projections contain the frontend's `listing_key`, `available_actions`, `nft`, `price_nano`, participant wallet snapshots, status and timestamps. Listing projection `id` is the marketplace `listing_id`, which is the buyer's deal-intent reference. A 256-bit random `listing_key` is assigned once per listing intent; each deal receives a separate 256-bit `deal_salt`.

## Canonical deal lifecycle

`intent_created → awaiting_nft → awaiting_buyer_funds → funded_review → nft_release_pending → delivered_dispute_window`

Buyer acceptance is a distinct operation in `funded_review`. It is not a receipt confirmation after delivery. The post-delivery dispute window starts only after accepted oracle delivery attestation, finality and contract-state reconciliation.

Payout and refund use pending states; terminal `settled` / `refunded` are not set by a message submission. They require finalized, exact-recipient and exact-amount reconciliation. Dispute resolution and payout/refund contract operations remain blocked pending ABI and resolver decisions.

## Chain event and cursor policy

Normalized event identity includes transaction hash, message hash (or transaction event index fallback), deal ID, trace ID, phase, attempt ID, query ID, operation ID, logical time and deal salt. Different trace/attempt identities are not collapsed.

- Raw observations (`nft_transfer_observed`, payment/return/payout/refund observations and legacy raw event labels) are persisted as evidence only. They do not call the canonical transition function.
- Contract-accepted events are applied only after provider verification, finality and immutable deal snapshot checks.
- Delivery additionally requires an accepted oracle attestation, a finalized trace/attempt and explicit contract-state reconciliation to `delivered_dispute_window`.
- A non-final, unverified or unmatched event is persisted as `pending`. The observer does not advance its durable cursor past that event; it re-queries the same provider page and promotes the same event row when final evidence arrives.
- A conflicting event with the same identity is moved to `manual_review`; distinct attempts/traces remain distinct records.
- Event persistence and cursor advancement share one database transaction. Provider outage, lease loss or database failure leaves the cursor replayable.

## Migration and compatibility

Revision `e20261114_ton_escrow` is chained after the current main Alembic head `0014_admin_user_management`, which itself follows the existing Stars refund migration `0013_payment_refund_workflow`. It creates escrow-only tables and does not alter Stars payment ledger tables, `OrderStatus`, orders or the existing non-custodial delivery workflow. Migration tests must use a disposable test database only; never run this migration on production/VPS.

## Explicit blockers

1. Contract ABI, code hash, factory and deterministic address derivation are not approved.
2. TEP-62 deposit message validation and collection/item authenticity strategy need contract-owner fixtures.
3. Oracle/quorum authority and actual getter reconciliation need reviewed provider contracts.
4. Dispute resolver policy, timing and recovery paths remain proposals.
5. No transaction payload, opcode, state-init, deployment or financial message is implemented here.

Until these blockers close, all preparation endpoints remain fail-closed. The router must remain unmounted and Draft.


## Explicit integration gates before mounting

The isolated router must remain unmounted until all of the following are approved and tested:

1. A versioned DealEscrow ABI and Factory contract are reviewed, including deterministic address derivation, state-init, opcodes, cell layouts and getter semantics. Until then, all transaction preparation returns HTTP 503.
2. A real testnet provider adapter can prove transaction/message/trace identity, masterchain finality, accepted oracle attestations and getter-state reconciliation. A transaction hash or NFT transfer notification alone is never accepted delivery.
3. Marketplace listing reservation is coordinated atomically with the existing Orders workflow so an escrow-reserved listing cannot also be purchased through the ordinary order path. This PR deliberately does not change OrderStatus, Stars payments or the current order workflow; that integration gate must be resolved before public discovery/checkout is enabled.
4. The full backend, migration and API-backed E2E suites pass against disposable test infrastructure. No migration is run against production or VPS databases.

Payout and refund remain contract-initiated state transitions. The API exposes their pending/finalized state through the deal projection and does not provide a manual client-controlled financial trigger.
