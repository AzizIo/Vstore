# Stage B B1 — TON NFT transfer evidence provider

Status: implementation draft for Issue #46. This is a read-only provider adapter and test fixture set; it is **not an order-completion workflow**.

## Provider endpoints and evidence fields

The adapter uses the network-specific TON Center API v3 base URL:

- `GET /nft/transfers`, filtered by exact `item_address`, paginated with `limit`, `offset`, and descending `sort`.
- `GET /traces`, filtered by the transfer's `trace_id`, with `include_actions=true`.

It correlates the returned NFT transfer row by exact item address and the immutable per-attempt `query_id`. The transfer row must report the exact snapshotted `old_owner` and `new_owner`, a transaction hash, trace ID, and `transaction_aborted=false`.

The trace must be complete (`is_incomplete=false`) and have a positive `mc_seqno_end`. The trace must contain the exact NFT item-account transaction identified by the transfer row's transaction hash. The transaction must have:

- `account` equal to the exact NFT item contract;
- inbound message `source` equal to the snapshotted seller;
- inbound message `destination` equal to the NFT item contract;
- inbound message opcode equal to TEP-62 `transfer#5fcc3d14`;
- `description.aborted=false`, `description.compute_ph.success=true`, and `description.action.success=true`.

Missing or inconsistent chain/indexer fields do not produce a success result.

## Result model

- `not_found`: no indexed transfer matches the item + attempt query ID yet. This is not proof of failure.
- `inconclusive`: the transfer may exist, but its trace is not indexed or is incomplete.
- `failed`: indexed evidence identifies a wrong source/destination or an aborted/failed item transaction.
- `verified_finalized`: all adapter checks pass and the trace is recorded with masterchain inclusion metadata.

Provider/network/configuration failures raise typed `ProviderUnavailable` or `InvalidProviderData`; they are not converted into a successful or failed business transition.

The optional client-supplied transaction hash is only a hint. The adapter does not select or accept evidence from that value; it returns the canonical transfer hash found through the indexed transfer + trace correlation. TON Center's published API v3 migration notice states that hashes are returned in Base64, not hex; Base64 is case-sensitive, so the adapter preserves its exact case when correlating transfer and trace records.

Reference for the current hash representation: [TON Center API v3 migration notice](https://t.me/toncenter_news/6).

## Trust boundary

TON Center API v3 is an indexed data layer. This adapter validates consistency across the transfer row and transaction trace, but does not independently verify a Merkle proof or query a local liteserver. Its `verified_finalized` result is therefore an **indexer-backed evidence result**, not a cryptographic proof.

The Streaming API supports `pending`, `confirmed`, and `finalized` trace finality. Only `finalized` is suitable for low-latency success signals. Streaming does not recover missed historical events after an outage, so the v3 historical adapter remains necessary for reconciliation and gap recovery. This B1 implementation intentionally ships the v3 read-only path first; it does not yet subscribe to Streaming API events.

## Scope and non-goals

This change does not:

- alter Order or OrderEvent state values;
- add a database table, Alembic migration, API route, worker, or notification event;
- call Tonkeeper or broadcast a wallet transaction;
- mark an order completed, cancel an order, or reopen a listing;
- add payment, escrow, refund, fee, payout, or custody logic.

The next implementation slice is delivery-attempt persistence and approved state transitions (B2), followed by prepare/submission APIs and the reconciliation observer (B3/B4). Keep ambiguous results in observation/manual review; never relist based on a missing indexer row.
