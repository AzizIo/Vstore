# TON escrow backend API — Draft

**Status:** isolated backend prototype; not mounted into the public FastAPI app and not enabled for checkout. The smart-contract ABI, address derivation, event decoder and settlement accounting are not approved.

## Safety boundary

- The module only accepts TON testnet. API mutations require the existing authenticated API session and a verified wallet record owned by that session.
- A listing intent or deal intent is an off-chain request record. Creating one does not reserve an NFT on-chain, deploy a contract, collect TON or guarantee a deal.
- PostgreSQL stores immutable snapshots and a projection of provider evidence. It is not the source of truth for NFT ownership, funds or seller balances.
- TON Connect payload preparation returns HTTP 503 with code contract_abi_pending until a versioned ABI, code hash, state-init/address calculation and exact message layouts are approved. No temporary opcode or payload is invented.
- Client-supplied transaction hashes are not an input to observer state transitions. The observer consumes only provider-normalized events with independent verification and finalized masterchain evidence.
- Telegram Stars (XTR) are rejected by this TON-only prototype and are not represented as TON.
- The backend uses no mainnet provider and the observer's default provider fails closed. It is not started automatically and does not alter the current delivery observer.

## Endpoints in backend/app/api/escrow.py

All paths below are prefixed by /api/escrow after the router is mounted by an approved integration change. The router is intentionally not added to backend/app/main.py in this branch because that file is outside the task's allowed change scope.

| Method | Path | Behavior |
|---|---|---|
| POST | /listing-intents | Validate a seller-owned active TON testnet NFT listing, verified testnet seller wallet, current ownership provider and Idempotency-Key; create an intent_only record. |
| GET | /listing-intents/{intent_id} | Seller-scoped read; foreign IDs return 404. |
| POST | /deals | Verify buyer-owned verified testnet wallet and current NFT ownership; persist an intent_created intent, not an on-chain deal. One active deal intent per listing is enforced in PostgreSQL. |
| GET | /deals/{deal_id} | Participant-only read; non-participants receive 404. |
| POST | /listing-intents/{intent_id}/transaction | Fails closed with 503 until the ABI-gated adapter is implemented. |
| POST | /deals/{deal_id}/receipt | Buyer-scoped request; does not change deal state and fails closed with 503 until an unsigned TON Connect payload can be built from the approved ABI. |
| POST | /deals/{deal_id}/disputes | Records a dispute request only when chain-projected state is dispute-eligible; the record is not an on-chain dispute until contract evidence confirms it. |
| GET | /seller/balance | Returns available_balance_nanotons: null, not a fabricated zero or seller sub-ledger. |
| POST | /withdrawals | Validates ownership of a verified testnet wallet and writes an explicitly blocked intent with null amount and no transaction payload. |

Mutating operations accept an Idempotency-Key header (8–128 characters). Reusing a key with different canonical request data returns 409. The database uses a unique (actor_id, operation, idempotency_key) constraint. All resource reads are scoped by the authenticated user.

## Observer

app.escrow.observer.run_observer_pass() uses a durable escrow_observer_checkpoints row and lease token. It queries the provider outside database transactions, verifies the batch, and commits event persistence plus cursor movement atomically. A provider outage or lost lease leaves the cursor unchanged. Events are deduplicated by (network, transaction_hash, event_index). A hash conflict, stale sequence, wrong NFT, wrong payer/recipient, amount mismatch, non-final event or invalid transition is rejected or marked for manual review; it never marks success from a client callback.

A real TONTestnetEscrowProvider is intentionally not supplied. The accepted ABI must define how contract address/deal IDs are bound, how events are decoded, how trace completeness and masterchain finality are established, and whether any event proof is independently checked.

## Migration

Migration e20261114_ton_escrow creates only escrow-specific tables and a testnet observer checkpoint. It references existing users, wallets, listings and NFT assets, but does not change those tables or order/payment status constraints. It targets main's current payment ledger revision 0012_telegram_stars_payments; the refund-worker PR uses its own proposed 0013_payment_refund_workflow, so maintainers must resolve migration heads if both branches are accepted.

## ABI / product decisions still required

1. Obtain the final ABI and code hash from the smart-contract owner, including deterministic deployment/state-init calculation, message opcodes/layouts, bounce behavior and versioning.
2. Decide whether the agreed design holds NFT and TON together through the entire dispute window, or permits conditional refund after delivery; this affects the contract state machine and refund invariants.
3. Reconcile the design's fixed direct seller payout with the requested seller balance/withdrawal API. Direct settlement to the seller wallet does not create a marketplace withdrawable balance. A balance model requires a separate on-chain accounting decision.
4. Specify what constitutes independent finalized evidence (trace verification, masterchain checkpoint, provider quorum/oracle signatures) and how provider disagreement/reorgs are handled.
5. Decide whether on-chain disputes need a separate resolver transaction, a 2-of-3 threshold attestation, or another approved design, and how resolver keys are operated.
6. Confirm testnet wallet-proof configuration, exact network allowlist, code deployment process and disposable test wallet policy.
7. Resolve the missing requested file path docs/MRKT_STYLE_TON_ESCROW_ARCHITECTURE.md; this branch was implemented against current docs/TON_TESTNET_ESCROW_ARCHITECTURE.md instead.
8. Approve ADR-0001 and relevant product/platform/legal/security gates before any live-value implementation. This backend prototype does not approve those decisions.
