# Stage B architecture: NFT delivery confirmation and order lifecycle

- **Status:** Stage B implementation tracker. B1, B2 and B3 are merged; B4 is proposed in [Draft PR #92](https://github.com/AzizIo/Vstore/pull/92) and is not yet in main.
- **Issue:** [#46 — implement non-custodial NFT transfer confirmation lifecycle](https://github.com/AzizIo/Vstore/issues/46); decomposition: [#56](https://github.com/AzizIo/Vstore/issues/56).
- **Baseline reviewed:** main through migration 0006 (delivery observer leases); Draft PR #92 adds migration 0007 and seller delivery APIs.
- **Scope boundary:** TON NFT (TEP-62) transfer confirmation after reservation. This is not a payment, escrow, guarantee, custody, refund, or payout design.

## 1. Executive summary

The current main branch can reserve an active listing, snapshot its price and currency, cancel or expire the reservation, and verify seller ownership at reservation time. B1 (PR #63) adds read-only, fail-closed TON transfer evidence; B2 (PR #85) adds the forward migration from `pending_payment` to `reserved` and immutable delivery-attempt snapshots; B3 (PR #86) adds the leased observer and atomic finalization from exact finalized evidence. B4 is in Draft PR #92: it adds seller preparation, candidate submission and participant read APIs plus persisted preparation idempotency. Until PR #92 merges, main cannot create delivery attempts through the API, so no live order can enter the delivery workflow from a client request.

Stage B should add a server-observed delivery lifecycle for a direct, non-custodial TON NFT transfer. The seller authorizes any transfer in their own wallet. The backend stores a buyer-wallet snapshot and checks chain/provider evidence independently. A submitted transaction hash is only a lookup hint, and a client callback, screenshot, Tonkeeper screen, wallet connection, or current-owner response without transaction correlation is not sufficient proof of delivery.

**Implementation baseline:** the maintainer recorded the Stage B technical decisions in the 2026-11-11 comment on Issue #46. Use those fail-closed defaults: buyer wallet snapshot at delivery preparation (not reservation), fresh seller ownership recheck, a separate 15-minute preparation window, finalized masterchain evidence, and audited manual reconciliation for ambiguous outcomes. Keep payments/escrow out of Stage B.

## 2. Current baseline and gaps

### Implemented on main

| Area | Current behavior |
|---|---|
| Listing | A Listing stores a mandatory positive price and currency; active listings are unique per NFT across active/reserved states. |
| Reservation | POST /api/orders accepts listing_id and Idempotency-Key; the service reads an identity snapshot, checks the seller's verified wallet(s) through the TEP-62 verifier, then locks and revalidates listing → wallet → asset before creating the order. |
| Reservation snapshot | Order stores buyer, seller, listing, price/currency, idempotency key and expires_at. B2 adds an immutable `OrderDeliveryAttempt` snapshot; B4 in Draft PR #92 adds preparation idempotency and the API that creates it. |
| Order schema states (B2) | `reserved`, `awaiting_transfer`, `observing_transfer`, `completed`, `cancelled`, `expired`. B3 observer can move a prepared attempt into observation and atomically complete only exact finalized evidence. B4 APIs are not merged yet. Listing: draft, active, reserved, sold, cancelled, expired. |
| Events | OrderEvent records from/to status and actor; B2 widens constraints to the delivery vocabulary and permits seller actors. B3 writes the system completion event transactionally with listing/order/asset updates; B4 writes the seller preparation/submission transition events. |
| Expiry/cancel | Cancellation and the expiry worker lock listing → asset → order; the release helper will not republish an asset that is locally stale/unverified. |
| Ownership loss | A fresh affirmative owner mismatch invalidates the listing and pending order; provider outage/inconclusive data is not treated as proof that the NFT was transferred. |
| Notifications | Order events enqueue Telegram outbox entries within the database transaction; a separate worker retries sends. |
| TON adapter | TONNFTVerifier reads TEP-62 item state and checks the expected current owner through the configured provider. The verifier currently has no order-delivery watcher or transfer-proof API. |

### Remaining for Stage B

- B4 seller prepare/submit/read APIs are in Draft PR #92, not merged. That PR verifies the selected seller wallet against fresh on-chain ownership, snapshots the buyer's verified primary wallet, persists a 15-minute preparation window and idempotency key, and prevents buyer cancellation once preparation has committed.
- B5: enqueue delivery lifecycle notifications in the transactional outbox in the same transaction as accepted delivery state changes. The current outbox vocabulary covers reservation/cancel/expiry only.
- B6: integrate the seller's wallet-driven transfer initiation and candidate-hash submission plus buyer/seller delivery status UI. Do not let the server sign or broadcast the transfer.
- Testnet/manual acceptance: prove TON Connect signing, the item transfer message and provider finality behavior against known testnet transactions before any mainnet pilot.
- Expand fault/concurrency coverage for prepare vs cancellation, submit vs observer claim, expiry/deadline races, duplicate candidates and provider disagreement.

## 3. Proposed state machine

B2 in PR #85 adds these values to the database/API type vocabulary and migrates legacy rows in place. They are schema states, not a claim that the current services already execute delivery transitions.

### Order states and target transitions

| Proposed state | Meaning | Allowed next states |
|---|---|---|
| reserved | Current listing reservation exists; seller has not obtained a delivery intent | awaiting_transfer, cancelled, expired |
| awaiting_transfer | Buyer destination and seller source are snapshotted; seller can request/sign a transfer using their own wallet | observing_transfer, cancelled only if the system proves no transfer could have been submitted, expired only after reconciliation |
| observing_transfer | A candidate transfer is being checked or the transfer intent could have reached the chain; the listing must not be reopened | completed, awaiting_transfer after a proven safe retry; otherwise remains observing_transfer while the attempt may be manual_review |
| completed | Server has verified delivery to the snapshotted buyer destination and has atomically finalized the order/listing | terminal |
| cancelled | Reservation was cancelled before transfer could occur, or the system conclusively reconciled a non-transfer state | terminal |
| expired | Reservation/delivery deadline elapsed and the system conclusively established that this order cannot still complete | terminal |


`manual_review` is a delivery-attempt status, not an Order status. The Order remains `observing_transfer` while an attempt needs operator review. An ambiguous delivery must never automatically reopen the NFT listing.

### Transition table

| From → To | Actor/trigger | Preconditions and atomic effects |
|---|---|---|
| reserved → awaiting_transfer | Seller requests delivery preparation | Authenticated seller; pending reservation not expired; current verified seller wallet and current NFT owner rechecked; buyer has a fresh verified wallet on the same network; snapshot source/destination addresses, NFT address and network; insert event/intent and establish delivery deadline under locks. |
| awaiting_transfer → observing_transfer | Seller UI reports a candidate transaction, or observer finds a matching on-chain candidate | Treat transaction hash as untrusted hint; create or update a deduplicated observation record; do not mark completed. |
| awaiting_transfer → cancelled | Buyer cancels before a delivery intent can possibly have been submitted | Must be atomic against prepare/start; verify no submitted/candidate transfer and no ambiguous observation. |
| awaiting_transfer → observing_transfer | Delivery deadline reached while a submission might exist | Do not return listing to the catalogue until the observer reconciles chain state. |
| observing_transfer → completed | Backend observer confirms the exact transfer at the required finality | All chain/order correlation checks pass; persist proof, order event, Listing SOLD and completed state in one transaction; enqueue notifications in the outbox. |
| observing_transfer → awaiting_transfer | Observer definitively proves no transfer occurred and the policy permits retry | Preserve attempt history; issue a new attempt identifier; do not reuse an old candidate hash as proof. |
| observing_transfer → observing_transfer | Provider disagreement, ambiguous transfer/recipient, repeated outage, possible reorg, or deadline without conclusive result | Keep the order in observing state; mark the delivery attempt `manual_review`; keep the listing unavailable and preserve evidence. |
| Attempt `manual_review` → verified/failed/cancelled | Explicit audited reconciliation | Requires authoritative chain evidence or a documented resolution rule; the order transition remains server-controlled and never follows an unaudited admin toggle or client-only decision. |

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
                                                                                     └─ ambiguous/provider conflict ─> observing_transfer (attempt=manual_review)

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
- B2 in PR #85 adds a forward migration from `pending_payment` to `reserved`, preserving order/event IDs and all price, currency, idempotency and timestamp data. It updates Order/OrderEvent constraints, the partial unique index, backend/frontend types and fixtures together.
- The migration adds `order_delivery_attempts` with immutable seller/buyer address snapshots and database uniqueness/check constraints. Its downgrade refuses to remove recorded attempts or newer delivery states.
- Do not run this migration against production/VPS until the PR is merged, reviewed, and a separate deployment/backup plan is approved.

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
| B1 | Read-only transaction/trace evidence adapter for TEP-62 transfer correlation | Backend | Maintainer baseline | Implemented in [PR #63](https://github.com/AzizIo/Vstore/pull/63): bounded TON Center v3 correlation, typed outcomes and fail-closed checks. Indexed-provider trust assumptions are documented. |
| B2 | Delivery-attempt persistence, state migration and immutable snapshots | Backend + DB | B1 | Implemented in [PR #85](https://github.com/AzizIo/Vstore/pull/85): preserves historical reservations/events, adds database constraints and uniqueness. |
| B3 | Leased observer/reconciliation worker and deterministic provider polling | Backend | B1, B2 | Implemented in [PR #86](https://github.com/AzizIo/Vstore/pull/86): leased PostgreSQL claims, bounded concurrent provider polling, exact B1 evidence correlation, fail-closed manual review and atomic finalization across attempt/order/listing/asset/event. |
| B4 | Delivery preparation/submission/read APIs with auth, locks and idempotency | Backend | B2, B3 | Snapshot verified buyer destination and freshly verified seller source; client-supplied hashes/addresses never establish completion. |
| B5 | Transactional transfer outbox events/notifications and PostgreSQL concurrency/fault-injection tests | Backend + QA | B3, B4 | Duplicate/out-of-order events are idempotent; failure cases fail closed. |
| B6 | Buyer destination confirmation, seller TON Connect transaction request and status UI | Frontend | B4 API contract | UI shows delivered only from backend persisted verification; no payments UI. |
| B7 | Manual testnet pilot, operational alerts/reconciliation and security review | QA + Maintainer | B1–B6 | Checklist signed off before any mainnet rollout. |

The maintainer has recorded the Stage B technical baseline in Issue #46. Continue with the staged sequence above; do not expose transfer actions in the UI until the B3/B4 backend contract exists. Map work onto existing issues before opening duplicates.

## 12. Maintainer decision baseline (2026-11-11)

The following conservative defaults were explicitly recorded by the maintainer in the Issue #46 technical baseline comment and are the implementation contract for Stage B:

1. **Status naming:** migrate legacy `pending_payment` rows/events to `reserved` in one forward migration; preserve IDs, timestamps, prices, currencies, idempotency keys and event history.
2. **Buyer wallet snapshot:** browsing and reservation do not require a buyer wallet. At seller delivery preparation, require the buyer's verified primary wallet on the configured network and snapshot its normalized address/network plus wallet row ID. The snapshot is immutable for that attempt.
3. **Seller source snapshot:** before preparation, recheck current on-chain ownership and require the selected verified seller wallet to match the actual owner. Snapshot seller address, NFT item, network and a random per-attempt TEP-62 `query_id`.
4. **Timeouts:** keep the reservation TTL at 900 seconds. Add a separate 900-second seller delivery-initiation window after preparation. Expire/release only after reconciliation proves no transfer could have been submitted; possible submission or provider outage remains observing/manual review.
5. **Finality:** Streaming API must report `finality=finalized`; pending/confirmed never complete. The v3 fallback must correlate the exact item-account transaction/trace and finalized masterchain inclusion, successful transaction/action and non-aborted execution. The v3 indexer is a trusted indexed data layer, not a cryptographic proof; fail closed on missing/inconsistent fields and use historical polling for gap recovery.
6. **Transfer evidence:** match the exact TEP-62 item, snapshotted seller source, snapshotted buyer destination, network and finalized successful item transaction. `query_id` and user-supplied transaction hashes are correlation/lookup hints only. A later onward transfer by the buyer does not undo a correctly finalized receipt.
7. **Ambiguous outcomes:** keep the Order in `observing_transfer`; mark the specific delivery attempt `manual_review`. Never auto-complete, auto-relist or use current-owner-only reads as proof. Manual reconciliation is audited and evidence-based.
8. **Cancellation:** buyer cancellation is allowed only while the Order is `reserved`. After delivery preparation, cancellation remains blocked until the observer conclusively proves no transfer could have been submitted.

### Remaining operational decisions

- Exact supported item/collection contract profiles and user-facing fallback for unsupported NFTs.
- Provider lag thresholds, retry/backoff, alert routing and operator permissions for audited reconciliation.
- Retention period and minimization policy for chain evidence/provider diagnostics.

These defaults authorize the staged B1–B7 technical work only. They do not authorize payments, escrow, production migrations, or a live transfer/completion feature before its own review and testnet acceptance.

## 13. Completion criteria for Stage B

- Every terminal completed order has server-persisted chain evidence correlated to its exact item, network, seller and snapshotted buyer destination.
- No client callback, explorer URL, screenshot, submitted transaction hash or wallet connection can directly complete an order.
- Order/listing/asset state, event log and outbox notifications are atomic and idempotent.
- Provider outage and ambiguous state never produce success or automatically reactivate an unsafe listing.
- Migration, backend unit/API/PostgreSQL integration, worker fault tests, frontend tests and testnet manual verification pass.
- The current MVP remains non-custodial and payment-free. No checkout, escrow, guarantee, refund, fee, custody, or seller payout is included in Stage B.

## 14. B3 observer implementation notes

The B3 observer is a backend-only worker. It does not expose an API, ask the seller to sign a transfer, broadcast a transaction, or accept client-supplied evidence as proof.

- Claims due prepared/observing attempts in bounded batches with PostgreSQL FOR UPDATE SKIP LOCKED.
- Uses a persisted random lease token and a timeout-aware lease deadline. Bounded concurrent polling keeps claims inside the lease window; expired leases are reclaimable and a stale worker cannot write after another worker has reclaimed the attempt.
- Releases all database locks before calling TON Center v3. The provider is selected from the attempt's persisted network.
- Uses only the immutable item, seller, buyer, network and query_id snapshots. Candidate transaction hashes remain lookup hints and are not trusted.
- Retries not_found, inconclusive, provider failures and internal transient errors with bounded exponential backoff. At the delivery deadline or retry limit, the attempt moves to manual_review; the order and reserved listing are not released.
- A provider failed result, destination mismatch, changed local order/listing/asset state, duplicate verified transaction, or inconsistent evidence is quarantined as manual_review.
- Only verified_finalized evidence with exact snapshot matches, a transaction hash, trace ID and positive masterchain seqno can complete an order. The attempt, order, listing, asset owner and append-only order event are committed in one transaction after the lease and state are revalidated.
- The v3 provider remains an indexed-data trust assumption, not a cryptographic proof. A verified order is not a payment and does not imply escrow or marketplace custody.
- B3 adds migration 0006_delivery_observer_leases for observer retry count and reclaimable lease metadata. No production/VPS migration is included in PR #86.
