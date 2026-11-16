# TON escrow backend API — Draft

**Current status (2026-11-16):** isolated testnet-only backend prototype. Listing/deal creation and wallet-action preparation require a proof-anchored NFT identity snapshot tied to an explicitly allowlisted standard TEP-62 collection. The collection policy list defaults to empty, so these paths fail closed until an operator reviews and configures the exact collection and item code hashes. No wallet signing, transaction broadcast, mainnet use, or live testnet transfer is enabled.

This API follows `docs/TON_ESCROW_SHARED_INTERFACE.md`. The pinned DealEscrow v1 ABI, code BOC, deterministic StateInit/address derivation and unsigned TON Connect message encoders are documented in `docs/TON_ESCROW_ABI_ADAPTER.md`. Proof-backed NFT identity reads are separate from the opt-in finality observer and do not enable signing or broadcast.

## Safety boundary

- All authenticated actors come from the verified API session. Wallet IDs are resolved server-side to verified testnet wallet records; client wallet addresses are never authoritative.
- `available_actions` is derived from the authenticated participant and current server-side state. Sellers never receive buyer-only `create_deal_intent` actions, and buyers never receive seller-only actions.
- All amounts are integer nanotons encoded as decimal strings. The seller's listing price is snapshotted as the immutable deal principal.
- A listing intent is an off-chain seller preparation record. It does not claim that the NFT is held by escrow.
- Before listing/deal creation, item and collection account state are both read from the same trust-level-0 LiteServer masterchain anchor. The verifier checks explicit code-hash allowlist policy, TEP-62 storage, and locally reconstructs the standard `get_nft_address_by_index(index)` StateInit address. TON Center indexed NFT fields and remote get-method responses are not accepted as this proof.
- Missing/invalid `TON_ESCROW_NFT_COLLECTION_POLICIES`, unlisted collection/code, malformed or stale proof, provider outage, or changed identity anchor blocks listing/deal/action progression. Terminal-owner reconciliation re-proves the owner and requires the original item/collection/code/policy identity to remain unchanged.
- Creating a buyer deal intent locks one buyer, seller, listing key, collection, NFT item, principal, network and unique deal salt into one immutable deal record. ORM guards and a PostgreSQL trigger reject later changes to these terms. The first contract address/ABI-version assignment is permitted after an approved deployment; subsequent replacement or clearing is rejected.
- Deal-scoped deployment is not prepared from a seller-only listing intent.
- The observer stores raw evidence separately from accepted contract events. Accepted NFT deposit/delivery/return events must match both the snapshotted collection and item; raw NFT transfer observations cannot advance canonical deal state.
- Non-final, unverified or unmatched events remain pending and pin the durable cursor. The same provider page is re-queried until it can be promoted or reconciled. Missing deal/contract reconciliation and stale sequence/logical-time events also remain pending; database commit failure rolls back the batch and leaves the durable cursor unchanged. Conflicting immutable event parameters move to manual review.
- Event identity is a SHA-256 key over network, transaction hash, message hash (or event index), trace, phase and attempt. Logical time, deal salt, collection/item and contract-state facts remain correlated payload fields; compatible pending evidence may be enriched, while conflicting values are moved to manual review. A provider must keep the identity tuple stable between non-final and final scans.
- The pinned `PinnedTONEscrowContractAdapter` produces unsigned wallet payloads only after immutable snapshot, identity, getter, role and state checks. A prepared payload is not proof of submission/finality. The backend never signs or broadcasts.
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
| POST | `/deals/{deal_id}/prepare/create-deal-escrow` | Seller-only, deal-scoped unsigned deployment preparation; requires persisted snapshot and fresh NFT identity evidence; never signs/broadcasts. |
| POST | `/deals/{deal_id}/prepare/deposit-nft` | Seller-only, only in `awaiting_nft`; ownership and NFT identity are rechecked before returning an unsigned payload. |
| POST | `/deals/{deal_id}/prepare/funding` | Bound buyer only, only in `awaiting_buyer_funds`; requires a current identity proof and complete immutable snapshot. |
| POST | `/deals/{deal_id}/prepare/accept` | Bound buyer only, only in `funded_review`; requires a current identity proof and complete immutable snapshot. |
| POST | `/deals/{deal_id}/prepare/dispute` | Bound buyer only, only in `funded_review` or `delivered_dispute_window`; requires a current identity proof and complete immutable snapshot. |
| POST | `/deals/{deal_id}/prepare/nft-return` | Bound buyer only in `disputed`; buyer ownership and NFT identity are rechecked. |
| POST | `/deals/{deal_id}/prepare/withdraw-unsold-nft` | Seller only after `expired`; expected owner and NFT identity are rechecked. |
| POST | `/wallet-references` | Stores a client-reported submission reference only as an untrusted reconciliation hint; never finalizes state. |
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

The escrow schema has durable action/snapshot migrations through `0019_escrow_deployment_snapshots`. Revision `0020_escrow_nft_identity_snapshots` adds the identity-evidence pair to listing intents and deals, with database checks and an immutable-snapshot trigger. Migration tests must use a disposable test database only; never run these migrations against production/VPS.

## Remaining release gates

1. Configure only operator-reviewed standard TEP-62 collection policies in `TON_ESCROW_NFT_COLLECTION_POLICIES`. Keep this list empty until code hashes and collection ownership/provenance have been independently checked.
2. Complete exact-head CI and disposable-PostgreSQL migration verification for the new identity snapshot migration.
3. Complete an independently reviewed, valueless live testnet acceptance lifecycle with transaction, trace, finality, getter and current-owner evidence. Do not enable mainnet or production asset transfers.

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

## NFT identity verification added for Issue #213

See [TON escrow NFT identity proof and allowlist](TON_ESCROW_NFT_IDENTITY.md) for the trust boundary, configuration schema, snapshot immutability, adversarial test inventory and rollout gates.

The implementation uses `backend/app/escrow/nft_identity.py` for TEP-62 storage and address derivation; `backend/app/escrow/finality_provider.py` reads item and collection account states from the same trusted masterchain block and repeats identity/current-owner proof before terminal listing reconciliation; migration `0020_escrow_nft_identity_snapshots` persists immutable evidence on both listing intents and deals.

The default collection policy list is intentionally empty. Do not take code hashes from TON Center metadata or enable a collection without an operator-reviewed policy. No Preview wiring, Tolk source, ABI serializer, signing, broadcast or mainnet behavior is changed by this issue.
