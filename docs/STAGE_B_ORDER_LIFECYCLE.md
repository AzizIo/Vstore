# Stage B architecture: NFT delivery confirmation and order lifecycle

- **Status:** proposal for review; no runtime code, API contract, or database schema is changed by this document.
- **Issue:** [#56 — decompose NFT delivery confirmation and post-reservation order lifecycle](https://github.com/AzizIo/Vstore/issues/56).
- **Baseline reviewed:** current main, models and migrations through 0004, order/listing services, API schemas, TON NFT verifier and notification outbox.
- **Scope boundary:** TON NFT (TEP-62) transfer confirmation after reservation. This is not a payment, escrow, guarantee, custody, refund, or payout design.

## 1. Executive summary

The current application can reserve an active listing, snapshot its price and currency, cancel or expire the reservation, and verify that the seller still owns the NFT at reservation time. It cannot independently confirm that the seller later transferred the exact NFT to the buyer. The current Order statuses are pending_payment, cancelled and expired; pending_payment is a legacy reservation label, not a payment event.

Stage B should add a server-observed delivery lifecycle for a direct, non-custodial TON NFT transfer. The seller authorizes any transfer in their own wallet. The backend stores a buyer-wallet snapshot and checks chain/provider evidence independently. A submitted transaction hash is only a lookup hint, and a client callback, screenshot, Tonkeeper screen, wallet connection, or current-owner response without transaction correlation is not sufficient proof of delivery.

**Recommendation:** keep the current reservation lifecycle intact until the owner approves the proposed status vocabulary, delivery deadline semantics, finality policy, and buyer-wallet snapshot rule. Then implement the server observer and persistence contracts behind feature flags or a controlled rollout. Do not add payment/escrow behavior to Stage B.

## 2. Current baseline and gaps

### Implemented on main

| Area | Current behavior |
|---|---|
| Listing | A Listing stores a mandatory positive price and currency; active listings are unique per NFT across active/reserved states. |
| Reservation | POST /api/orders accepts listing_id and Idempotency-Key; the service reads an identity snapshot, checks the seller's verified wallet(s) through the TEP-62 verifier, then locks and revalidates listing → wallet → asset before creating the order. |
| Reservation snapshot | Order stores buyer, seller, listing, price/currency, idempotency key and expires_at. It does not store an immutable buyer destination wallet or delivery attempt. |
| Existing states | Order: pending_payment, cancelled, expired. Listing: draft, active, reserved, sold, cancelled, expired. |
| Events | OrderEvent records from/to status and actor; its database checks allow only the current Order status values. |
| Expiry/cancel | Cancellation and the expiry worker lock listing → asset → order; the release helper will not republish an asset that is locally stale/unverified. |
| Ownership loss | A fresh affirmative owner mismatch invalidates the listing and pending order; provider outage/inconclusive data is not treated as proof that the NFT was transferred. |
| Notifications | Order events enqueue Telegram outbox entries within the database transaction; a separate worker retries sends. |
| TON adapter | TONNFTVerifier reads TEP-62 item state and checks the expected current owner through the configured provider. The verifier currently has no order-delivery watcher or transfer-proof API. |

### Missing for Stage B

- A verified, immutable buyer destination address associated with this specific order and network.
- A delivery deadline distinct from the initial reservation expiry, plus rules for when seller transfer intent locks cancellation/relisting.
- Persistence for transfer observation attempts, provider cursor/transaction identity, failure reason and final proof.
- A server-side observer that correlates an on-chain TEP-62 transfer with the exact order, seller, buyer destination, NFT item and configured network.
- Deduplication, confirmation/finality policy, recovery after provider downtime, reorg/incomplete-index behavior and safe/manual reconciliation.
- Order state transitions for transfer started, observed, completed and uncertain outcomes.
- Tests for simultaneous buyer cancellation, seller transfer, expiry, duplicated events, and provider disagreement.

## 3. Proposed state machine

These names are a proposal, not an approved schema change. Prefer replacing the misleading pending_payment label with reserved during the Stage B migration, but only after the owner approves the API compatibility and data-migration plan.

### Proposed order states

| Proposed state | Meaning | Allowed next states |
|---|---|---|
| reserved | Current listing reservation exists; seller has not obtained a delivery intent | awaiting_transfer, cancelled, expired |
| awaiting_transfer | Buyer destination and seller source are snapshotted; seller can request/sign a transfer using their own wallet | observing_transfer, cancelled only if the system proves no transfer could have been submitted, expired only after reconciliation |
| observing_transfer | A candidate transfer is being checked or the transfer intent could have reached the chain; the listing must not be reopened | completed, awaiting_transfer after a proven safe retry, manual_review |
| completed | Server has verified delivery to the snapshotted buyer destination and has atomically finalized the order/listing | terminal |
| cancelled | Reservation was cancelled before transfer could occur, or the system conclusively reconciled a non-transfer state | terminal |
| expired | Reservation/delivery deadline elapsed and the system conclusively established that this order cannot still complete | terminal |
| manual_review | Available evidence is conflicting, incomplete for longer than the operational threshold, or cannot safely determine whether delivery occurred | completed or cancelled/expired only after a reviewed, audited reconciliation; no automatic listing release |

The existing cancelled and expired states can remain terminal. Whether a separate manual_review state is needed, or whether it should be represented by a delivery-attempt status while the order stays observing_transfer, is an owner decision. The important invariant is that an ambiguous delivery must not automatically reopen the NFT listing.

### Transition table

| From → To | Actor/trigger | Preconditions and atomic effects |
|---|---|---|
| reserved → awaiting_transfer | Seller requests delivery preparation | Authenticated seller; pending reservation not expired; current verified seller wallet and current NFT owner rechecked; buyer has a fresh verified wallet on the same network; snapshot source/destination addresses, NFT address and network; insert event/intent and establish delivery deadline under locks. |
| awaiting_transfer → observing_transfer | Seller UI reports a candidate transaction, or observer finds a matching on-chain candidate | Treat transaction hash as untrusted hint; create or update a deduplicated observation record; do not mark completed. |
| awaiting_transfer → cancelled | Buyer cancels before a delivery intent can possibly have been submitted | Must be atomic against prepare/start; verify no submitted/candidate transfer and no ambiguous observation. |
| awaiting_transfer → observing_transfer | Delivery deadline reached while a submission might exist | Do not return listing to the catalogue until the observer reconciles chain state. |
| observing_transfer → completed | Backend observer confirms the exact transfer at the required finality | All chain/order correlation checks pass; persist proof, order event, Listing SOLD and completed state in one transaction; enqueue notifications in the outbox. |
| observing_transfer → awaiting_transfer | Observer definitively proves no transfer occurred and the policy permits retry | Preserve attempt history; issue a new attempt identifier; do not reuse an old candidate hash as proof. |
| observing_transfer → manual_review | Provider disagreement, ambiguous transfer/recipient, repeated outage, possible reorg, or deadline without conclusive result | Keep listing unavailable and preserve observation evidence; alert operators through an auditable path. |
| manual_review → completed / cancelled / expired | Explicit audited reconciliation | Requires authoritative chain evidence or a documented resolution rule; never an unaudited admin toggle or client-only decision. |

Suggested state flow (illustrative):

    reserved
      ├─ cancel before delivery intent ──────────────> cancelled
      ├─ reservation deadline + no attempt ──────────> expired
      └─ seller prepares transfer + buyer snapshot ──> awaiting_transfer
                                                          ├─ candidate found ──> observing_transfer
                                                          ├─ safe cancel/reconcile ─> cancelled/expired
                                                          └─ deadline uncertain ─> observing_transfer
                                                                                     ├─ proof complete ─> completed
                                                                                     ├─ conclusively no transfer ─> awaiting_transfer
                                                                                     └─ ambiguous/provider conflict ─> manual_review

A cancellation/expiry path must share the same lock-order and transition guard as delivery preparation. If a transfer may have been submitted, it is unsafe to release a listing solely because the local deadline elapsed.

## 4. Transfer verification design

### Trust boundary

The client is a requester, never the source of truth. A Tonkeeper prompt authorizes a blockchain action from the user's wallet; it does not authorize the server to believe that action succeeded. The backend must query trusted chain/indexer data and verify the transfer independently.

The TON NFT item implements TEP-62. Its transfer message includes the opcode 0x5fcc3d14, query_id, new_owner, response_destination, custom_payload, forward_amount and forward_payload. The standard exposes get_nft_data(), including initialization, item index, collection address and owner address. Collection membership should be verified where a collection is expected. References: [TEP-62 standard](https://github.com/ton-blockchain/TEPs/blob/master/text/0062-nft-standard.md), [TON NFT messages and get methods](https://docs.ton.org/contracts/standard/tokens/nft/api), and [TON Center v3 overview](https://docs.ton.org/ecosystem/api/toncenter/v3/overview).

### Required server-side checks

For an order to be completed, the observer must be able to establish all of the following from the configured network and trusted provider data:

1. The order is in a state where delivery is expected and its immutable listing/asset/seller/buyer identity has not changed.
2. The item address and network exactly match the order's verified NFT asset. The item is initialized, and the configured network/provider is the expected one.
3. The source of the transfer is the seller wallet snapshotted for this delivery attempt, not just any wallet belonging to the seller at a later time.
4. The parsed TEP-62 transfer is for the exact item contract and its new_owner field exactly matches the buyer wallet snapshot. If the provider only shows an item-state update but cannot correlate it with this transfer/source/destination, the result is inconclusive.
5. The item contract transaction and its relevant trace/actions indicate successful execution; an external message accepted by a wallet, a pending transaction, or a failed/rejected transaction is not delivery.
6. The transaction belongs to the selected TON network and meets the explicitly configured inclusion/finality rule. If provider data is stale, incomplete, inconsistent or unavailable, the order cannot be marked completed.
7. The evidence is new for this order and not already accepted for a different order or attempt. Record stable transaction identity (network + item transaction hash/lt or provider-native immutable identity) and use a database uniqueness guard.
8. The order has not already been finalized by another worker/request. Re-read and lock the order/listing in the prescribed order and finalize exactly once.

A candidate transaction hash supplied by the frontend may help the worker find a transaction faster, but the worker must retrieve and validate that transaction itself. The transaction hash must never be an authorization token or a direct “complete order” command.

### Current-owner reads are necessary but not sufficient

The verifier's current-owner read is necessary for inventory/publication safety, but it does not by itself prove that the NFT was transferred from this seller to this buyer for this order. A current-owner read can lag or change again after another transfer. Use transaction-level evidence correlated with a fresh get_nft_data state; when the chosen provider cannot reliably expose enough evidence, keep the order in observing_transfer/manual_review rather than inventing a successful result.

The standard is general and wallet/NFT contracts may vary. Unsupported contract behaviors must be rejected as unsupported, not silently accepted. Validate transfer parsing and collection checks against testnet fixtures and the chosen provider before enabling mainnet.

### Confirmation/finality policy — decision required

Do not hardcode an arbitrary number of confirmations in the implementation PR. Select an explicit policy with the maintainer and provider owner:
- Which provider fields are the canonical transaction/block identity and how are masterchain inclusion/finality represented?
- How does the provider flag failed compute/action phases and aborted traces?
- How do we detect an indexed-but-not-final or reorged/inconsistent result?
- What is the maximum indexing lag before an order moves to manual_review?
- Is there a second independent read/provider required for a high-value case?

The policy should be configurable and documented. Before policy decisions are made, automated delivery should remain disabled.

## 5. API contracts — proposal only

Keep the existing reservation endpoints and contracts intact in the first implementation step. Add delivery-specific endpoints rather than repurposing create/cancel or introducing payment semantics.

| Proposed method/route | Actor | Purpose | Important behavior |
|---|---|---|---|
| POST /api/orders/{order_id}/delivery/prepare | Seller | Atomically create a delivery intent and snapshot source/destination wallet addresses, item, network and deadline | Requires verified seller wallet, verified buyer wallet on the same network and fresh seller ownership recheck; idempotent request key; does not send a transaction. |
| POST /api/orders/{order_id}/delivery/submissions | Seller | Submit a candidate transaction hash or wallet attempt reference | Hint only. Validate format/size, persist idempotently, enqueue observer; never change to completed in this handler. |
| GET /api/orders/{order_id}/delivery | Buyer or seller | Read current delivery state, deadline and safe public evidence summary | Same order visibility authorization as GET order; do not expose provider credentials or internal logs. |
| Internal worker operation (not public API) | Worker | Poll/reconcile item and transaction state and finalize only on verified evidence | Bounded retries, lease/claim, idempotent writes and outbox in one DB transaction. |

Questions to settle before implementation:
- Does seller preparation require the buyer's verified wallet at reservation time, or allow the buyer to connect/verify it just before delivery? Recommendation: snapshot only at explicit prepare/start time, before any seller transfer is enabled; buyer must sign/verify the destination wallet via TON Connect Proof.
- Should an order allow buyer destination changes before transfer begins? Recommendation: yes only before a delivery intent exists; after prepare, destination is immutable for that attempt.
- What is the exact timeout for reservation versus delivery? They should be separate concepts, with explicitly approved configuration values.
- What safe retry operation is permitted after the observer proves no transaction was submitted/accepted?

Do not add a public endpoint accepting arbitrary status or arbitrary buyer address. Seller/buyer IDs, listing, item and price must be derived from persisted order/listing rows.

## 6. Database and event contracts — proposal only

### Existing tables to preserve

- Listing holds asset_id, seller_id, status, mandatory price/currency and listing expiry.
- NFTAsset holds the normalized item address, network, owner_id and verification status.
- Order holds buyer_id, seller_id, listing_id, idempotency key, price/currency snapshot and current reservation expiry.
- OrderEvent stores status changes and actor.
- TelegramNotificationOutbox gives transactional, deduplicated notification enqueueing.

### Proposed additions

**Order delivery snapshot (either columns on Order or a dedicated one-to-one intent table):**
- order_id (unique FK), network, item_address, seller_wallet_id (nullable FK for historical retention), seller_address_snapshot, buyer_wallet_id (nullable FK for historical retention), buyer_address_snapshot;
- prepared_at, delivery_deadline, current attempt id, observed/final transaction reference, verified_at, verifier version/source and a compact evidence digest.
- Snapshot addresses should remain readable if a user later unlinks a wallet. Store raw normalized addresses and network as immutable order evidence; wallet rows are references, not the sole historical record.

**OrderDeliveryAttempt (recommended if retries or multiple candidate transactions are allowed):**
- id, order_id, attempt_number, state, candidate_hash (optional/untrusted), verified item transaction identity, network, source/destination/item snapshots, provider first-seen time, observation/check timestamps, finality evidence, reason code and created/updated timestamps.
- Unique (order_id, attempt_number); unique network + verified item transaction identity to prevent accepting one transfer for two orders; index states/next-check time for worker claims.
- Never persist credentials or private keys. Bound raw provider payload retention; store only what is required for audits and diagnostics.

**OrderEvent extension:**
- Expand allowed transition values only through a migration that updates OrderStatus, OrderEvent from/to constraints and partial indexes/checks. Add explicit actor types for seller/system/worker only if required and constrained.
- Record old/new state, actor, attempt_id/correlation_id, event time and reason code. Keep this append-only and transactional with state transition/outbox changes.

**Migration and compatibility:**
- The current schema explicitly constrains Order and OrderEvent to pending_payment/cancelled/expired, and the pending-order partial unique index keys off pending_payment. New status names cannot be introduced by editing only the Python Enum.
- If owner approves a rename, write a forward data migration for existing rows and update constraints, indexes, API schemas, frontend types, test fixtures and any notification/event queries in the same PR. Do not run a destructive or ad-hoc production migration.
- The existing pending_payment label is not an authorization decision. Until the owner approves a rename, keep it unchanged and keep documentation/UI wording neutral.

## 7. Concurrency and idempotency invariants

1. One open order per listing remains enforced by PostgreSQL's partial unique index; one active/reserved listing per asset remains enforced by the listing index.
2. Use the existing lock order (listing → wallet → asset; then order where the service contract requires it) consistently. Review all cancellation, expiry, delivery preparation and finalization paths for deadlock cycles before adding worker locks.
3. Recheck order state and delivery intent after acquiring locks; do not trust a previously fetched ORM object or transaction/provider result without checking that its snapshot still matches.
4. Use a unique idempotency key for client commands and a separate stable idempotency key for each candidate/verified chain event. Retries must return the same logical result, not duplicate attempts/events/outbox rows.
5. Claim work with bounded leases or SKIP LOCKED and a reclaimable lease; a process crash must not leave an order permanently locked.
6. A worker must be safe if two instances observe the same transfer simultaneously. Database uniqueness and a state/version guard must allow exactly one transition to completed.
7. Outbox entries are written in the same transaction as the completed/cancelled/expired event. Notification failure must not roll back a verified chain event or duplicate business transitions.
8. Do not call TON Center while holding database row locks. Query first, then enter a short transaction, lock/revalidate the state snapshot and persist.
9. On timeout/provider outage, do not change status to completed, do not release a listing with uncertain ownership and do not assume the transfer failed.
10. If the NFT leaves the seller while the order remains open, atomically invalidate the listing/order as appropriate and notify both parties without ever restoring a no-longer-owned NFT to the active catalogue.

## 8. Threat model

| Threat | Mitigation / rejection rule |
|---|---|
| Fake transaction hash or explorer URL | Server fetches canonical provider data and independently validates transaction/message/item; frontend string is only a hint. |
| Transfer to attacker-controlled address | Compare TEP-62 new_owner and resulting ownership against the immutable buyer destination snapshot. |
| Wrong NFT with similar metadata/name | Use exact normalized item contract address and network; metadata is not identity. |
| Wrong chain/testnet | Persist explicit network and query the matching provider; reject network mismatch. |
| Fake/stale current owner | Correlate transaction history and current get_nft_data; fail closed on inconsistent provider snapshots. |
| Replay same transfer across orders | Unique verified transaction identity plus state guard and an order-bound immutable intent. |
| Proof arrives after order cancellation/expiry | Recheck allowed transition under locks; ambiguous transfer after cancellation becomes observing/manual_review, not silent completion or listing reopen. |
| Buyer changes wallet after transfer begins | Destination snapshot immutable for that attempt; no retroactive destination update. |
| Seller transfers after order expiration | Watcher reconciliation and freshness check before releasing/relisting; no automatic relist while transfer outcome is ambiguous. |
| Provider outage, rate limit, delayed index or inconsistent replicas | Retry with bounded backoff; keep pending/observing; escalate to manual_review; never treat error as success or ownership loss. |
| Reorg or late indexed transaction | Require approved finality policy; retain attempt/evidence and allow reconciliation; avoid irreversible status changes before finality. |
| Duplicate workers or race with cancellation | Locks in consistent order, leases, unique constraints, optimistic/state guard, idempotent event/outbox writes. |
| Malicious metadata/image URL | TEP-62 chain state is authoritative; sanitize display metadata separately; never dereference user URL as proof. |
| Admin/operator misuse | No unaudited state override; scoped permission, mandatory reason and immutable audit event if manual resolution is eventually implemented. |

## 9. Failure modes and recovery matrix

| Failure | Required behavior | Recovery |
|---|---|---|
| TON provider timeout/429/5xx | Do not complete or expire conclusively; retain state/attempt | Exponential backoff with bounded retry and alert on sustained lag |
| Transaction not found yet | Treat as not-yet-indexed, not failure, during allowed observation window | Re-query transaction/account with cursor/window |
| Valid transfer intent but contract execution failed | Never complete; store reason and failed transaction evidence if available | Safe retry only when failure and no ownership change are conclusive |
| Transfer completed to wrong destination | Never complete; never infer buyer delivery from item moved | Mark conflict/manual_review and notify both parties; do not relist automatically |
| Item state says buyer, transaction source/correlation is missing | Inconclusive for this order | Remain observing/manual_review; reconcile with stronger provider data |
| Item state changed again after expected transfer | Use verified transaction evidence plus defined policy; current owner alone is ambiguous | Query transaction trail; do not accept an unrelated later owner change |
| Same transaction observed twice | One persisted verified event; no duplicate outbox | Unique constraint and idempotent upsert |
| Two observers both finalize | One transition only | Row/state guard; the second observes terminal state and exits |
| Cancel and transfer-prepare race | One atomic transition wins | Recheck after locks; if submission could already exist, move to observing rather than release listing |
| Expiry runs while transfer is pending | Do not publish active listing on ambiguous evidence | Reconciliation first; expire only on conclusive policy |
| Worker crashes while claimed | No permanent lock | Lease expires; worker resumes from persisted attempt/cursor |
| Wallet unlinked/switched after snapshot | Keep immutable snapshot; wallet record deletion must not erase evidence | Verify transfer to snapshot, not current user's newly selected wallet |
| Unsupported NFT implementation | No automated success | Mark unsupported/manual review; define support policy explicitly |

## 10. Test matrix

### Unit tests

- Parse valid TEP-62 transfer messages including new_owner and query_id.
- Reject malformed opcode/body, invalid address encoding/workchain, wrong item, wrong source, wrong destination, wrong network, unsupported item/collection.
- Reject failed transaction/action/trace, unfinalized evidence, unknown transaction, stale/inconsistent provider snapshot.
- Validate order state transition rules, deadline boundaries, immutable wallet snapshots and reason-code mapping.
- Validate transaction identity normalization/deduplication and provider cursor handling.

### API tests

- Buyer/seller authorization for prepare, submit and read; third-party user gets 404/403 without information leakage.
- Unverified buyer wallet and mismatched network cannot prepare delivery.
- Client-supplied destination, seller ID, asset ID, price or state are ignored/rejected; values come from the stored order/listing snapshot.
- Repeated prepare with the same idempotency key returns one attempt.
- Repeated candidate hash cannot create duplicate attempt or duplicate completion.
- Candidate hash does not complete order until the observer independently verifies chain data.
- Submission after terminal state is rejected or appended to reconciliation without rewriting history.

### PostgreSQL integration and concurrency tests

- Migration from existing pending_payment/cancelled/expired rows preserves orders, prices, currencies, idempotency keys and events.
- Constraints/indexes cover all new statuses and still enforce one pending order per listing and one open listing per asset.
- Two workers observe one transfer concurrently; exactly one completion event and outbox notification set is committed.
- Seller prepare vs buyer cancel; prepare vs expiry worker; observer finalization vs cancel; ownership invalidation vs expiry — no deadlock, duplicate transition or listing reactivation.
- A reserved listing cannot be republished after affirmative ownership loss, delivery conflict or ambiguous provider outage.
- Worker lease expiry/reclaim and crash between provider lookup and DB commit are safe.
- Order event + delivery proof + listing SOLD + outbox entries commit atomically or roll back together.

### Provider/contract integration on testnet

- Valid transfer from seller wallet to buyer snapshot for exact item.
- Same NFT transfer to a different wallet; another NFT transferred to buyer; wrong network; failed transaction; transfer before reservation; transaction outside delivery attempt window.
- Provider indexing lag, rate limits, outage, duplicate/missing pages and inconsistent transaction/current-owner reads.
- Buyer immediately transfers NFT again after receiving; verify the first event is correlated correctly without relying only on current ownership.
- Collection/item relationship mismatch and unsupported contract implementation.
- Re-run every event to validate idempotency and recovery.

### Manual acceptance

- Telegram Mini App authentication remains intact.
- Buyer verifies and snapshots destination address on the selected network.
- Seller's Tonkeeper signs the direct NFT transfer; no private key or seed phrase is requested by VILTARA.
- UI stays pending until backend observer verifies the chain evidence; client success callback alone never displays delivered/completed.
- Outage, wrong recipient, switching account/network, repeated event and timeout display non-success states and never relist an NFT with uncertain ownership.

## 11. Suggested implementation work breakdown

These are proposed tasks to create or map onto existing Issues after maintainer review; this document intentionally does not create or close issues.

| Order | Work item | Owner area | Depends on | Acceptance |
|---|---|---|---|---|
| B0 | Approve state vocabulary, deadline rules, finality policy, buyer wallet snapshot point and API compatibility | Maintainer + Backend | This design | Written decisions resolve the open questions below |
| B1 | Design and implement transaction/trace provider adapter for TEP-62 delivery evidence | Backend | B0 | Typed provider results distinguish confirmed, failed, not-found-yet, unsupported and unavailable |
| B2 | Add delivery intent/snapshot/attempt persistence, state migration and constraints | Backend + DB | B0, B1 contract | Migration preserves old reservations and enforces idempotency/uniqueness |
| B3 | Implement delivery preparation/submission/read API with auth, locks and idempotency | Backend | B2 | Client-supplied hashes/addresses never establish completion |
| B4 | Implement leased observer/reconciliation worker and transactional completion/outbox | Backend | B1, B2, B3 | Duplicate/out-of-order provider events are idempotent; failure cases fail closed |
| B5 | Add testnet contract/provider fixtures, PostgreSQL concurrency suite and fault injection | QA + Backend | B1–B4 | Full matrix above passes |
| B6 | Add buyer destination confirmation, seller TON Connect transaction request and status UI | Frontend | B0, B3 API contract | UI shows delivered only from backend persisted verification; no payments UI |
| B7 | Run manual testnet pilot, confirm operational alerts/reconciliation and review security | QA + Maintainer | B1–B6 | Checklist signed off before mainnet rollout |

Issue #46 should remain blocked until the Stage B design and contracts are approved. Do not start full #47 frontend work until the backend contract and implementation are ready. Map these suggested tasks onto existing issues before opening new ones to avoid duplicates.

## 12. Open decisions for the maintainer

1. **Status naming:** approve migration from pending_payment to reserved, or retain legacy status until a broader order-state migration?
2. **Buyer wallet snapshot:** must the buyer have a verified wallet at reservation time or only before seller delivery preparation? Recommendation: verify/snapshot before preparing the seller transfer.
3. **Delivery timeout:** separate duration from reservation TTL? What should happen when a transaction may be submitted but provider indexing is delayed?
4. **Finality:** which TON Center/other provider fields represent acceptable inclusion/finality, and is a second provider needed?
5. **Manual review:** should manual_review be an Order status or a delivery-attempt status with order kept observing?
6. **Cancellation policy:** can the buyer cancel after the seller's delivery intent is created? Recommendation: not until the observer proves no transfer could have been submitted.
7. **Unsupported NFT contracts:** which code/collection profiles are supported, and what user-facing fallback is acceptable?
8. **Operational controls:** lag thresholds, retry/backoff, alerts and operator authority for audited reconciliation.
9. **Historical retention:** retention period for transaction evidence and provider diagnostics without storing unnecessary raw payloads.

## 13. Completion criteria for Stage B

- Every terminal completed order has server-persisted chain evidence correlated to its exact item, network, seller and snapshotted buyer destination.
- No client callback, explorer URL, screenshot, submitted transaction hash or wallet connection can directly complete an order.
- Order/listing/asset state, event log and outbox notifications are atomic and idempotent.
- Provider outage and ambiguous state never produce success or automatically reactivate an unsafe listing.
- Migration, backend unit/API/PostgreSQL integration, worker fault tests, frontend tests and testnet manual verification pass.
- The current MVP remains non-custodial and payment-free. No checkout, escrow, guarantee, refund, fee, custody, or seller payout is included in Stage B.
