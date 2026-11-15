# RichBounce observer — proof and reconciliation design

## Scope and safety boundary

This implementation handles DealEscrow v1 messages emitted with `BounceMode.RichBounce`. It is testnet-only and performs observation only: it never signs, broadcasts, or submits wallet messages. TON Center v3 is a bounded discovery source, not a source of truth. A discovered bounce is not applied until the containing shard block, transaction, and inbound message are independently checked through the configured trust-level-0 Pytoniq LiteServer path and the contract state is read from the proof-anchored account state.

The implementation does not reinterpret a bounce as a successful NFT transfer, payout, or refund. A critical outbound failure is accepted only when the contract has itself correlated the incoming bounced message to a persisted outbound descriptor and the proof-read contract state reflects `manual_review`. A reserve/allowance refund bounce may preserve the contract's already-terminal state, but it cannot reopen or complete a deal.

## TON body format

The parser in `backend/app/escrow/rich_bounce.py` decodes the TON new bounce body tag `0xfffffffe` using the protocol field layout:

- `original_body:^Cell`
- `original_info:^NewBounceOriginalInfo`
- `bounced_by_phase:uint8`
- `exit_code:int32`
- `compute_phase:(Maybe NewBounceComputePhaseInfo)`

The referenced original info contains `value:CurrencyCollection`, `created_lt:uint64`, and `created_at:uint32`. CurrencyCollection is parsed as Grams plus HashmapE. Extra currencies are retained as a parse fact but are not accepted for the marketplace's current Toncoin-only outbound actions. The optional compute metadata is parsed inline as specified by the Maybe value; it includes gas used and VM steps when present. The parser rejects unknown tags, truncated cells, inconsistent phase/compute metadata and trailing bits or references.

Classic bounce tag `0xffffffff` does not include the complete original body. It is recorded as unmatched forensic evidence and cannot be correlated by body hash.

## Detection and proof chain

1. The observer scans transactions for each configured DealEscrow address and persists a restartable per-account logical-time cursor. A TON Center `bounced` flag or leading body opcode is only a discovery hint.
2. The provider identifies candidates with the RichBounce or classic bounce tag. It does not trust the indexer's trace, status, finality, query id, sender, destination, or phase fields.
3. The provider resolves the candidate shard block through LiteServer, verifies shard inclusion against a masterchain block and verifies the masterchain path from the trusted key block. Configured finality depth must be reached.
4. The transaction is retrieved from the proved shard block and must match exactly one contract-account transaction at the candidate logical time and transaction-cell hash. The inbound internal message cell hash must equal the candidate message hash and its destination must be the snapshotted escrow contract.
5. The successful contract transaction is paired with a proof-read account state. The deployed code hash, constructor snapshot, immutable deal terms and getter storage are checked against the pinned DealEscrow v1 artifact. The decoded `OutboundActionSet` is read from this storage cell, not from indexer data.
6. Only then is the RichBounce cell parsed and correlated to the contract's own outbound descriptor.
7. The original outbound message is then independently proven. The provider reads the escrow account state at the same proof-anchored masterchain height, follows its verified account-transaction hash chain back to the original message's `created_lt`, resolves the originating shard block, verifies the source transaction is included in that proved block, and searches its `out_msgs` for exactly one internal message with the descriptor's original body-cell hash.
8. The original message must have the escrow contract as source, the descriptor destination as target, the exact original value and creation LT/time carried by RichBounce, `bounce=true`, and `bounced=false`. The complete original message-cell hash, source transaction hash and source shard block ID are incorporated into the finality proof digest and persisted on the event. A bounded or incomplete history response remains retryable; it is never interpreted as proof that no source transaction exists.

## Outbound correlation

DealEscrow persists up to two action descriptors in `DealProgress.outboundActions`. Each descriptor contains action kind, query id, deal salt, attempt id, amount, original message value, expected state/pending action, retry window, original message-body cell hash, bounce status, phase/exit code and both address pairs.

The backend requires exactly one descriptor whose body hash equals the body cell hash in RichBounce. It then checks:

- descriptor is marked `BOUNCED` by the contract's `onBouncedMessage` handler;
- the bounced transaction's logical time is later than the original message's created LT;
- bounced-message sender equals the descriptor's original destination;
- original value equals the persisted value (except the explicit carry-all execution-reserve refund, whose amount/value is intentionally variable/zero in the descriptor);
- deal salt, bounce phase and exit code match the descriptor;
- original TEP-62 NFT transfer body, query id, recipient, response address, forward amount, payload magic and deal salt match for NFT actions;
- original settlement body, query id, deal salt and settlement action opcode match for principal, deployment-allowance and execution-reserve messages;
- the action amount and message value match the immutable deployment snapshot;
- the proof-read contract state is `manual_review` for critical NFT/principal actions, or the descriptor's expected state for non-critical reserve/allowance refunds.

Any mismatch, missing descriptor, duplicate descriptor, classic bounce, malformed body, or unsupported extra currency becomes `outbound_bounce_unmatched`. Such observations are retained with a reason code and do not mutate the canonical deal state, NFT custody flags, listing state, or financial ledger.

## State projection and idempotence

A correlated critical bounce becomes `outbound_action_bounced` and may move a non-terminal backend deal to `manual_review` only because the verified contract getter also reports `manual_review`. Non-critical reserve/allowance bounce may preserve the current state only when the proof-read getter and descriptor expected state agree. A late bounce cannot reopen a terminal deal.

Bounce event identity is derived from the network, proved transaction hash, proved message hash, local trace identity, and bounce phase. It does not depend on a query/attempt id that is unavailable until the proof-backed descriptor match. Proof-derived attempt/query identifiers enrich the existing pending event without creating a second identity.

The existing observer lease, cursor, and transaction boundary remain responsible for atomic event persistence and checkpoint advancement. If an event remains unmatched or pending, the observer retains the batch for safe replay. Provider outages and incomplete proof data do not produce accepted events.

## Configuration and operation

The existing opt-in escrow observer configuration remains testnet-only. No new signing or wallet credential is required for RichBounce. A running observer needs the same database migration, deployment snapshot, official testnet TON Center discovery endpoint, and trusted testnet LiteServer configuration as the proof finality provider.

Useful files:

- `backend/app/escrow/rich_bounce.py` — TL-B parser and action matcher.
- `backend/app/escrow/ton_abi.py` — pinned storage-cell decode, including outbound action descriptors.
- `backend/app/escrow/finality_provider.py` — candidate proof, finality, getter read and bounce verification.
- `backend/app/escrow/observer.py` — durable projection and manual-review handling.
- `backend/tests/escrow/test_rich_bounce.py` — real BOC cell parser/correlation fixtures.

Run backend checks from `backend/` using the repository's pinned environment:

```bash
pytest -q tests/escrow/test_rich_bounce.py tests/escrow/test_escrow_ton_abi.py tests/escrow/test_escrow_finality_provider.py tests/escrow/test_escrow_observer.py tests/escrow/test_escrow_domain.py
ruff check app/escrow tests/escrow
```

## Release and acceptance gates

Unit tests exercise actual TON Cell/BOC serialization and positive/negative correlation cases. Those tests do not replace an on-network testnet acceptance run. Before production approval, independently review the pinned Tolk ABI/BOC, run a valueless testnet lifecycle that creates real contract outbound messages and resulting RichBounce transactions, and attach the trusted masterchain/shard proofs, transaction/message hashes and proof-read getter snapshots. Production/mainnet remains deliberately unsupported by this observer.
