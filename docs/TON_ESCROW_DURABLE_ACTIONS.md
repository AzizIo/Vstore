# TON escrow durable wallet actions

**Status:** isolated TON testnet backend prototype; the router remains unmounted and the ABI adapter/provider remain fail-closed.

## Durable action contract

Each action has a stable UUID and a unique `(actor_id, action_type, idempotency_key)` identity. Its canonical request hash binds the actor, deal, action and immutable deal/wallet snapshot. Exact retries return the existing action; reusing the key for another payload is a conflict. The immutable request identity is enforced in PostgreSQL as well as in the service layer.

The action record reserves fields for attempt/query IDs, unsigned BOC digest/reference, submission reference/digest, retry count, lease fencing token/expiry, next retry time and safe error code. Do not store private keys, signatures, mnemonic material, or raw signed wallet payloads.

## Submission and finality rules

- Persist the action intent before any future wallet/broadcast side effect.
- A client-supplied hash or reference is only an untrusted hint. A hint is accepted only for an action with a prepared unsigned BOC and is stored as `ambiguous`, never as success.
- A second distinct reference for one action moves it to `manual_review`; database uniqueness prevents the same reference digest being assigned to multiple actions on testnet.
- `submitted`/`ambiguous` do not advance the deal state. Only the observer can apply a canonical event after independent transaction/message/trace binding, masterchain finality proof and contract getter reconciliation.
- An indexer result, transaction hash, wallet callback, or a positive current-owner lookup alone is not finality evidence. The production adapter is intentionally unconfigured until it can verify inclusion/finality independently.
- Unknown outcomes remain pending/ambiguous or manual review; never retry a potentially executed action as if the first attempt definitively failed.

## Reservation concurrency

Escrow and normal orders must lock the same marketplace `Listing` row in a consistent order and commit the `RESERVED` transition together with the escrow deal intent. A unique open escrow intent alone is not enough because it does not exclude an ordinary order. Until the cross-workflow integration tests pass on disposable PostgreSQL, the isolated escrow router stays unmounted.

## Migration

`e20261115_escrow_actions` follows `e20261114_ton_escrow`. It creates only the escrow action table and a guard against mutating action request identity or replacing an already-recorded submission reference. Downgrade drops only the new table/guard; it does not touch marketplace orders or payments. Run upgrade/downgrade tests against disposable PostgreSQL only.
