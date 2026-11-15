# TON escrow backend API — Draft

**Status:** isolated testnet-only backend prototype. `backend/app/main.py` mounts the router only when `TON_CONNECT_NETWORK=testnet`. The pinned ABI/BOC adapter and unsigned message builders exist, but the API still fails closed: it does not prepare or broadcast transactions.

This API follows `docs/TON_ESCROW_SHARED_INTERFACE.md`. The pinned DealEscrow v1 ABI, code BOC, deterministic StateInit/address derivation and unsigned TON Connect message encoders are implemented and documented in `docs/TON_ESCROW_ABI_ADAPTER.md`. The API does not yet activate those encoders because the complete immutable deployment snapshot and independently verified chain state are not available from the current database/provider.

## Safety boundary

- All authenticated actors come from the verified API session. Wallet IDs are resolved server-side to verified testnet wallet records; client wallet addresses are never authoritative.
- `available_actions` is derived from the authenticated participant and current server-side state. Sellers never receive buyer-only `create_deal_intent` actions, and buyers never receive seller-only actions.
- All amounts are integer nanotons encoded as decimal strings. The seller's listing price is snapshotted as the immutable deal principal.
- A listing intent is an off-chain seller preparation record. It does not claim that the NFT is held by escrow.
- Creating a buyer deal intent locks one buyer, seller, listing key, collection, NFT item, principal, network and unique deal salt into one immutable deal record. ORM guards and a PostgreSQL trigger reject later changes to these terms. The first contract address/ABI-version assignment is permitted after an approved deployment; subsequent replacement or clearing is rejected.
- Deal-scoped deployment is not prepared from a seller-only listing intent.
- The observer stores raw evidence separately from accepted contract events. Accepted NFT deposit/delivery/return events must match both the snapshotted collection and item; raw NFT transfer observations cannot advance canonical deal state.
- Non-final, unverified or unmatched events remain pending and pin the durable cursor. The same provider page is re-queried until it can be promoted or reconciled. Missing deal/contract reconciliation and stale sequence/logical-time events also remain pending; database commit failure rolls back the batch and leaves the durable cursor unchanged. Conflicting immutable event parameters move to manual review.
- Event identity is a SHA-256 key over network, transaction hash, message hash (or event index), trace, phase and attempt. Logical time, deal salt, collection/item and contract-state facts remain correlated payload fields; compatible pending evidence may be enriched, while conflicting values are moved to manual review. A provider must keep the identity tuple stable between non-final and final scans.
- The pinned `PinnedTONEscrowContractAdapter` is implemented and its ABI/BOC/vector checks pass, but the API deliberately instantiates `UnconfiguredTONEscrowContractAdapter`. Preparation remains HTTP 503; each authorized attempt first persists an idempotent `escrow_wallet_actions` record and returns its stable `action_id`. This is an audit/recovery intent, not a transaction payload or permission to broadcast. The API also validates that every required immutable deployment/getter field is persisted before constructing the adapter dataclass. The current `EscrowDeal` schema lacks reserve/refund amounts, query IDs, authority public keys and getter-state fields, so the response is `deployment_snapshot_incomplete` rather than an unhandled constructor error or a fabricated payload. The chain provider also remains unconfigured.
- Durable action identity binds actor, deal, action, idempotency key and the immutable deal/wallet snapshot. Exact retries reuse the row; payload conflicts return HTTP 409. Attempt/query IDs, unsigned BOC digest/reference, submission reference/digest, lease/retry metadata and safe error codes are reserved in the schema.
- The shared marketplace `Listing` row is locked and moved to `RESERVED` in the same transaction as the escrow deal intent. Escrow-only projection state is not sufficient to prevent a parallel ordinary Order.
- No production/mainnet routes, real TON transfers, production migrations or observer autostart are enabled.

## Endpoints

All routes below are under `/api/escrow`. The router is mounted only when `TON_CONNECT_NETWORK=testnet` and the runtime is local/development/test/preview, or the isolated Preview Compose runtime has explicitly set `ENVIRONMENT=production` plus `PREVIEW_MODE=1`. The normal production Compose stack does not set `PREVIEW_MODE`, so an accidental `PROD_TON_CONNECT_NETWORK=testnet` does not expose the testnet escrow API.

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

1. Persist the complete immutable deployment snapshot in `EscrowDeal`: oracle/resolver public keys, execution reserve, seller refund, NFT transfer/deposit/return values, all query IDs and protocol/network terms.
2. Persist exact unsigned payload bytes and response metadata so idempotent retries return the same payload rather than creating a different wallet request.
3. Implement a testnet provider with independently verifiable masterchain/shard inclusion and finality evidence. TON Center indexer observations alone are not proof of finality.
4. Reconcile finalized traces and all contract getters before applying any canonical state transition.
5. Complete PostgreSQL concurrency tests and terminal listing/NFT ownership reconciliation.
6. Execute a valueless live testnet lifecycle run and obtain an independent TON contract/security review.

Until these blockers close, all preparation endpoints remain fail-closed. The router may be conditionally mounted in testnet mode for discovery/projection APIs, but signing, broadcast and mainnet must remain disabled.


## Remaining integration gates before transaction preparation

The testnet-only router is conditionally mounted when `TON_CONNECT_NETWORK=testnet`. That mount exposes the isolated projections and intent APIs; it does not enable wallet transaction preparation. The following gates remain:

1. The versioned DealEscrow ABI, code BOC, StateInit/address derivation and message serializers are now pinned and cross-checked against the generated Acton wrapper. Independent contract/security review and confirmation of oracle/resolver authority policy are still required.
2. Persist the complete immutable deployment snapshot, including all authority public keys, reserve/refund/transfer amounts, query IDs and protocol/network terms. The current `EscrowDeal` row does not contain every required field.
3. Persist exact unsigned TON Connect payloads and response metadata so idempotent retries return the identical payload and query IDs.
4. Implement a testnet provider adapter that proves transaction/message/trace identity, masterchain/shard finality, accepted oracle attestations and getter-state reconciliation. A transaction hash or NFT transfer notification alone is never accepted delivery.
5. Complete PostgreSQL concurrency coverage for ordinary Orders versus escrow reservation and terminal relisting/ownership reconciliation.
6. Execute a valueless live testnet lifecycle run and attach transaction, trace, getter and current-owner evidence. Backend, migration, frontend and API-backed E2E checks must pass on the exact release commit. No migration is run against production or VPS databases.

Payout and refund remain contract-initiated state transitions. The API exposes their pending/finalized state through the deal projection and does not provide a manual client-controlled financial trigger.


See [TON escrow durable actions](TON_ESCROW_DURABLE_ACTIONS.md) for the action persistence contract, immutable identity guards, submission-reference policy and migration `e20261115_escrow_actions`.