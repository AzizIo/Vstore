# TON Escrow Shared Interface Contract

- **Status:** Draft integration contract for an isolated testnet PoC
- **Version:** 0.1
- **Date:** 2026-11-14
- **Companion architecture:** [MRKT-style TON Escrow Architecture](MRKT_STYLE_TON_ESCROW_ARCHITECTURE.md)
- **Decision record:** [ADR-0001](adr/0001-compliant-payments-and-escrow.md)
- **Scope:** standard TEP-62 TON NFTs and native TON only

> This file is the coordinator-owned contract between the contract, backend and frontend workstreams. It defines shared meanings, state/evidence rules and minimum data semantics. It does **not** freeze numeric opcodes, cell bit layouts, BOCs, FunC/Tact method names or deployment addresses. The contract workstream owns those details and must submit them for cross-workstream review before the ABI is frozen.

## 1. Non-negotiable boundaries

1. **Testnet only.** Use valueless test NFTs and test TON. Mainnet configuration, production wallets, real-value payments and deployment are out of scope.
2. **One immutable escrow contract per deal is the PoC default.** Each DealEscrow fixes one seller, one buyer, one TEP-62 NFT, one TON principal and one deal salt. It holds the NFT and buyer principal for that single deal. A new purchase requires a new deal instance. This matches the existing testnet threat-model proposal in docs/TON_TESTNET_ESCROW_ARCHITECTURE.md.
3. **The contract is the on-chain source of truth.** Backend tables are rebuildable projections. A database write, API callback, client status, submitted transaction hash or emitted outbound message does not itself prove a state transition.
4. **Stars are separate.** The existing Telegram Stars ledger and bot remain their own test-only payment domain. Stars must never be treated as TON escrow funds, converted into seller TON balances, or used as proof of NFT delivery.
5. **No new states in the existing orders table.** Escrow lifecycle and chain evidence live in separate escrow_* records. Existing reservation and non-custodial delivery behavior must not be silently repurposed.
6. **No wallet custody by the backend.** Users sign their own TON Connect transactions. Never request or store seed phrases or private keys.
7. **Platform gate remains.** Current Telegram rules say digital goods/services inside bots and Mini Apps use Stars (XTR), while Mini Apps with crypto wallet functionality must use TON and TON Connect. These requirements do not by themselves establish that a TON-paid P2P NFT checkout is permitted inside the Mini App. Do not enable an in-app TON purchase CTA until a written platform ruling and qualified legal review are recorded. See ADR-0001 and Issue #155.

## 2. Canonical identifiers and amounts

| Field | Shared meaning | Rules |
|---|---|---|
| listing_id | Backend/database UUID for the marketplace listing | Stable, immutable and never reused |
| listing_key | On-chain 256-bit opaque identifier derived/assigned for exactly one listing | Contract owner specifies exact encoding and derivation; store the exact value returned by the trusted deployment intent |
| escrow_address | Address of the immutable single-deal DealEscrow instance | Persist canonical raw form as well as display-friendly form |
| nft_item_address | Expected TEP-62 NFT item contract | Must match the item that deposits and the item escrow transfers |
| seller_wallet, buyer_wallet | TON addresses bound to transaction actors | Normalize before comparison; do not trust client-supplied actor identities |
| operation_id | Backend UUID identifying one requested user operation | Unique in the database; mapped to an on-chain query identifier |
| query_id | Contract-message correlation/replay identifier | Unique in the relevant escrow scope; never use it as the only chain-event identity |
| price_nano | Exact listing price in nanotons | Integer/string representation only; never float |
| fee_bps | Future fee snapshot field; fixed to zero for the initial PoC | Reject nonzero fee configuration until commission logic is separately reviewed and tested |
| deadline_unix | UTC Unix timestamp for a contract-enforced deadline | Exact start event must be specified; never infer from UI time |

Amounts crossing API boundaries are decimal strings containing integer nanotons. Frontend conversion to TON is presentation-only. Attached TON needed for storage/compute/forwarding is separate from the agreed listing price and must be displayed before wallet signing. The contract must reject or safely quarantine underpayment, overpayment and unexpected-value cases; it must never silently reinterpret attached value as a changed listing price.

## 3. Canonical escrow state machine

The deal state is independent of the existing backend OrderStatus. The semantic states below deliberately align with the existing testnet threat model and the backend agent's current domain vocabulary. A contract implementation may use different enum labels only if the mapping is explicit and lossless.

| State | Meaning | Allowed next states |
|---|---|---|
| INTENT_CREATED | Off-chain intent exists; no contract state is asserted | AWAITING_NFT after finalized contract activation |
| AWAITING_NFT | Deal contract deployed with immutable terms; seller NFT not yet locked | AWAITING_BUYER_FUNDS, MANUAL_REVIEW, EXPIRED |
| AWAITING_BUYER_FUNDS | Exact NFT deposit and ownership notification validated; waiting for buyer principal | FUNDED_REVIEW, EXPIRED, MANUAL_REVIEW |
| FUNDED_REVIEW | Buyer principal is locked and NFT remains in escrow; buyer review/pre-acceptance window is open | NFT_RELEASE_PENDING, DISPUTED, NFT_RETURN_PENDING, MANUAL_REVIEW |
| NFT_RELEASE_PENDING | Buyer accepted; contract initiated TEP-62 transfer to buyer; final delivery is not yet proven | DELIVERED_DISPUTE_WINDOW, MANUAL_REVIEW |
| DELIVERED_DISPUTE_WINDOW | Independent observer/oracle verified the exact NFT transfer at finalized masterchain checkpoint; post-delivery dispute window is running | DISPUTED, SELLER_PAYOUT_PENDING, MANUAL_REVIEW |
| DISPUTED | Valid buyer dispute is open; principal remains locked | NFT_RETURN_PENDING, NFT_RELEASE_PENDING, SELLER_PAYOUT_PENDING, MANUAL_REVIEW |
| NFT_RETURN_PENDING | An NFT return/return-to-seller operation is in progress; direction is bound to dispute phase and attempt ID | BUYER_REFUND_PENDING, DELIVERED_DISPUTE_WINDOW, MANUAL_REVIEW |
| SELLER_PAYOUT_PENDING | Fixed seller payout has been emitted; deal remains pending until exact payout evidence is finalized | SETTLED, MANUAL_REVIEW |
| BUYER_REFUND_PENDING | Fixed buyer refund has been emitted; deal remains pending until exact refund evidence is finalized | REFUNDED, MANUAL_REVIEW |
| SETTLED | Seller payout is finalized; no escrow asset remains | terminal |
| REFUNDED | Buyer refund is finalized and NFT has been returned to seller or remained escrow-owned under the approved path | terminal |
| EXPIRED | Deal expired before buyer funds were accepted and no NFT remains escrow-owned | terminal |
| MANUAL_REVIEW | Evidence conflict, ambiguous chain outcome or timeout race; no automatic asset release | recovery only after fresh finalized evidence or constrained resolver action |

`MANUAL_REVIEW` is a hold state, not a successful or refunded outcome. A DB/manual-review label must not override actual contract state. If an implementation has a separate `delivery_exception` label, it must map to a non-terminal pending/manual-review condition and preserve the underlying on-chain state.

### 3.1 Canonical flow

1. Seller creates a deal intent with immutable seller wallet, buyer wallet, NFT item, TON principal, network and random deal salt.
2. A single-deal contract is deployed. The seller transfers the exact NFT to it using TEP-62.
3. The contract validates the notification sender (exact NFT item), previous owner (seller), query ID, deal hash and expected phase. Only then does it enter AWAITING_BUYER_FUNDS.
4. Buyer sends the exact TON principal plus the separately specified execution reserve. Funds are locked once and the deal enters FUNDED_REVIEW. The NFT remains in escrow.
5. Buyer reviews the deal and either accepts (contract starts NFT transfer) or disputes. If the buyer does not accept by the fixed review deadline, the contract returns the NFT to seller and refunds buyer only after finalized NFT-return evidence.
6. After buyer acceptance, the contract enters NFT_RELEASE_PENDING. An outbound message alone is not delivery proof.
7. The observer correlates the exact NFT item transaction and complete message trace. A separately configured evidence oracle/quorum attests the exact finalized delivery (network, contract/deal, NFT, source, destination, query/attempt ID, evidence hash and masterchain checkpoint). Only then does the contract enter DELIVERED_DISPUTE_WINDOW and start the post-delivery dispute timer.
8. If the dispute window closes without a valid dispute, the contract initiates the fixed seller payout. The deal remains SELLER_PAYOUT_PENDING until the exact payout is finalized and reconciled.
9. A valid dispute freezes settlement. Resolution and asset-return steps follow §3.2; no party receives both the NFT and a refund.

### 3.2 Dispute / refund branches

- **Dispute before delivery acceptance:** while the NFT and TON remain in escrow, the resolver's constrained outcome determines whether the NFT is returned to seller and buyer refunded, or NFT delivery proceeds to buyer and seller is paid after finalized evidence.
- **Dispute after delivery:** under the current conditional-recourse model, buyer must return the exact NFT to escrow within the defined return window. The resolver may then decide. A buyer-favourable outcome returns the NFT to seller and refunds buyer after finality. A seller-favourable outcome re-delivers the NFT to buyer and pays seller after finality.
- **No NFT return after a post-delivery dispute:** no buyer refund is permitted while the buyer still owns the NFT. The dispute is rejected/settled according to the reviewed timeout rule. This is conditional recourse, not an unconditional chargeback.
- **Ambiguous return/delivery:** remain pending or MANUAL_REVIEW. A timeout only makes an action eligible; it does not prove that a message failed or that ownership changed.

The canonical testnet timing proposal in docs/TON_TESTNET_ESCROW_ARCHITECTURE.md uses a 24-hour buyer review window, a 30-minute delivery confirmation grace, a 48-hour post-delivery dispute window, a 24-hour NFT return window, and a 7-day arbitration resolution window. These are deterministic testnet defaults only, not production SLAs. The owner must explicitly approve or change them before ABI freeze.

### 3.3 Terminal states and payout accounting

`SETTLED` and `REFUNDED` are reached only after the exact money movement is finalized and reconciled, not when a payout/refund message is merely emitted. The corresponding pending states remain non-terminal and retryable.

For the first PoC, use a **zero platform fee**. This avoids introducing commission arithmetic before the escrow message protocol and failure paths are proven. Keep the fee/treasury design documented as future work; do not test seller payout against principal while simultaneously configuring a non-zero fee.

Payout/refund bounce handling must preserve the fixed recipient and amount, use a stable settlement ID with a fresh transaction attempt ID, and prevent duplicate payment. If the original transfer may still finalize, do not resend. A bounce or provider outage is not proof of final failure; reconcile the canonical trace first.



## 4. Canonical user / contract actions

These are semantic action names, not frozen opcodes.

| Action | Authorized actor | Preconditions | Required result |
|---|---|---|---|
| create_deal_escrow | Factory/deployment flow | Immutable seller, buyer, NFT, principal, network, salt and deadline config | One single-deal contract address |
| deposit_nft | Seller via TEP-62 | Exact item, seller as previous owner, matching deal hash/query ID | AWAITING_NFT -> AWAITING_BUYER_FUNDS only after validated notification |
| fund_deal | Bound buyer wallet | NFT lock validated; exact principal + published execution reserve | Funds locked once; AWAITING_BUYER_FUNDS -> FUNDED_REVIEW |
| accept_deal | Bound buyer wallet | FUNDED_REVIEW and before buyer review deadline | NFT transfer initiated; FUNDED_REVIEW -> NFT_RELEASE_PENDING |
| open_dispute | Bound buyer wallet | FUNDED_REVIEW or DELIVERED_DISPUTE_WINDOW, within applicable deadline | Deal frozen in DISPUTED |
| attest_nft_delivered | Configured evidence oracle/quorum | Exact finalized NFT transfer evidence, exact deal/attempt, no conflicting trace | NFT_RELEASE_PENDING -> DELIVERED_DISPUTE_WINDOW |
| attest_nft_returned | Configured evidence oracle/quorum | Exact finalized return/transfer evidence and expected source/destination | Advance the state-specific return branch |
| resolve_dispute_buyer | 2-of-3 resolver (testnet proposal) | DISPUTED; valid dispute phase and evidence refs | Start buyer-favourable NFT-return/refund branch |
| resolve_dispute_seller | 2-of-3 resolver (testnet proposal) | DISPUTED; valid dispute phase and evidence refs | Start seller-favourable delivery/payout branch |
| timeout | Permissionless keeper | Deadline reached and state-specific finalized chain evidence satisfies the guard | Advance only the eligible state branch; timeout alone proves nothing |
| initiate_seller_payout | Contract/permissionless trigger | DELIVERED_DISPUTE_WINDOW expired without dispute, or seller-favourable resolution | SELLER_PAYOUT_PENDING |
| reconcile_seller_payout | Configured evidence oracle/quorum | Exact finalized fixed-recipient payout evidence | SELLER_PAYOUT_PENDING -> SETTLED |
| initiate_buyer_refund | Contract/permissionless trigger | Buyer-favourable branch; exact NFT return condition met | BUYER_REFUND_PENDING |
| reconcile_buyer_refund | Configured evidence oracle/quorum | Exact finalized fixed-recipient refund evidence | BUYER_REFUND_PENDING -> REFUNDED |
| withdraw_unsold_nft | Bound seller wallet | Pre-funding expiry/cancellation and NFT remains escrow-owned | Return exact NFT to seller; no buyer funds retained |

Every action must specify actor, source state, destination state, replay key, attached-value requirements, bounce behavior and finality evidence before it is added to the ABI.



## 5. NFT deposit and authenticity requirements

The contract must not trust an arbitrary incoming NFT notification. At minimum, validate the notification sender against the expected NFT item contract, previous owner against the configured seller, and forwarded listing/deposit correlation data against escrow configuration.

The PoC should use an immutable single-deal contract and must explicitly choose and test an authenticity strategy:

- fixed allowlist of exact test NFT item addresses; or
- a reviewed collection/item derivation strategy that the contract can verify without pretending it can synchronously call another contract's getter.

Backend collection metadata or an API response is not on-chain proof. Unsolicited, wrong-item, wrong-seller, duplicate and malformed notifications must not make a listing active. Define a safe recovery path for an NFT that has already reached the escrow address but fails validation.

## 6. Chain evidence and backend projection

The threat-model proposal assigns two distinct roles: the backend observer independently parses/indexes transactions and traces; a separately configured evidence oracle/quorum attests evidence to the contract. The observer is not itself a contract authority unless it is explicitly configured as such for the isolated PoC and that trust assumption is documented. The dispute resolver is a separate 2-of-3 authority and must not be conflated with the evidence oracle.

TON contracts do not produce EVM-style receipt logs. The backend observer must parse relevant account transactions and inbound/outbound messages, correlate the complete message trace where necessary, and reconcile the contract's current state/getters. The normalized event names below are an application-level projection, not a claim that TON emits Solidity logs.

### 6.1 Two evidence layers — never conflate them

The backend observer and the escrow contract have different authority:

**Layer A — observed external evidence (off-chain).** The observer finds and validates the exact TEP-62 item transaction/message trace, buyer payment message, NFT return, or payout/refund transaction. These observations are evidence candidates. They do not, by themselves, change the canonical escrow deal state or release funds.

**Layer B — contract-accepted evidence (on-chain).** The configured oracle/quorum submits a domain-separated attestation to DealEscrow. The contract validates the oracle authority, deal/phase/attempt, evidence hash, finalized masterchain checkpoint and replay key, then updates its own state. The backend may project the state transition only after it independently observes/reconciles the resulting contract transaction/getter state. For example, an off-chain NFT transfer observation must not directly move the DB projection to DELIVERED_DISPUTE_WINDOW; only the accepted oracle attestation reflected in contract state may do so.

The dispute resolver is a third role. It chooses a constrained commercial outcome; it must not attest chain facts or replace the evidence oracle.

Use stable semantic event names:

- Evidence observations (off-chain; not state transitions): `nft_deposit_evidence_observed`, `buyer_payment_evidence_observed`, `nft_delivery_evidence_observed`, `nft_return_evidence_observed`, `seller_payout_evidence_observed`, `buyer_refund_evidence_observed`.
- Contract state observations (authoritative after reconciliation): `contract_activated`, `nft_deposit_accepted`, `buyer_payment_accepted`, `buyer_acceptance_recorded`, `oracle_delivery_attestation_accepted`, `dispute_opened_onchain`, `dispute_resolution_accepted`, `oracle_nft_return_attestation_accepted`, `seller_payout_reconciled`, `buyer_refund_reconciled`, `deal_expired`, `manual_review_required`.

Event consumers must be idempotent. Preserve the original evidence observation and the later contract-accepted state transition as separate records linked by evidence hash/attempt ID.

### 6.2 Minimum observation record

Every persisted evidence observation must carry enough information to independently replay and correlate it:

| Field | Purpose |
|---|---|
| `network` | Explicit `testnet` in this PoC |
| `account_address` | NFT item, escrow or recipient account whose transaction is observed |
| `transaction_hash` and `logical_time` | Transaction identity and ordering |
| `message_hash` | Exact inbound/outbound message identity where available |
| `trace_id` / `trace_hash` | Complete message trace identity/evidence |
| `source_address`, `destination_address`, `attached_value_nano` | Message routing and value |
| `query_id`, `operation_id`, `attempt_id` | Correlation and replay detection |
| `deal_salt` / `deal_id` | Exact deal identity |
| `normalized_event_type` | Evidence-observation or contract-state event |
| `observed_contract_state` | Contract getter/state snapshot after reconciliation |
| `raw_evidence_hash` | Hash/reference for retained raw trace evidence |
| `finality_status`, `masterchain_seqno` | Provider/chain finality classification and checkpoint |
| `observed_at` | Backend UTC timestamp; not a chain deadline |

Use a unique chain-event key such as `(network, account_address, transaction_hash, message_hash)` where available. Do not deduplicate solely by query ID. Store enough raw or content-addressed evidence to replay a decision. A provider outage, incomplete message trace, inconsistent getter result or non-final transaction must leave the projection pending/exceptional, never successful. If the provider can return the same transaction before and after finality, do not mark the non-final observation as a terminal rejection and advance past it permanently. Keep it pending/re-queryable and promote only after the finality condition is met; preserve both observation versions for audit.

The database needs to preserve both evidence observations and contract-accepted state transitions. A single normalized `NFT_TRANSFER_CONFIRMED` event is not enough to tell whether the observer saw an NFT item transaction or the contract accepted the oracle attestation. Use distinct event types/records or an equally explicit evidence-layer field. Process per-account events in logical-time order (or use a bounded reorder buffer); masterchain seqno alone is not a total transaction order. An older event arriving after a newer one must be retained/reconciled, not silently applied out of sequence or allowed to force success.

### 6.3 Backend state projection rule

The backend projection must reconcile the exact DealEscrow state/getters after contract transactions. It must not advance a canonical deal state merely because an external NFT item or wallet transaction was observed.

Examples:

- NFT item transaction observed, but no valid escrow ownership notification/state update: remain AWAITING_NFT / MANUAL_REVIEW.
- Buyer payment message observed, but DealEscrow has not accepted the exact principal: remain AWAITING_BUYER_FUNDS.
- Outbound NFT transfer observed at finality, but oracle has not submitted an accepted delivery attestation: remain NFT_RELEASE_PENDING.
- Oracle attestation message submitted but not finalized/accepted by DealEscrow: remain pending.
- Accepted oracle attestation is finalized and contract state is DELIVERED_DISPUTE_WINDOW: only then start the projected post-delivery dispute timer.
- Seller payout/refund transfer observed, but contract reconciliation has not finalized it: remain SELLER_PAYOUT_PENDING / BUYER_REFUND_PENDING.
- Provider or oracle disagreement: do not guess; mark the evidence conflict and preserve assets in MANUAL_REVIEW.

The observer may write evidence rows before the contract state changes. This is not a violation of append-only event history; it is required to preserve the chain of evidence.

### 6.3 Backend/frontend view model

The backend read model should expose, at minimum:

- listing ID/key, network, contract version, escrow address and on-chain state;
- expected NFT item, seller wallet, buyer wallet when present;
- exact price, currency TON, fee snapshot and claimable amount strings in nanotons;
- operation status and relevant transaction references;
- confirmation/dispute deadlines with their exact triggering event;
- available actions derived server-side from verified participant identity and reconciled state;
- a history of normalized events and evidence status.

The frontend must render this read model as observed facts, not local optimistic success. Unknown states must render as a safe pending/error state rather than falling through to success.

### 6.4 Frontend state mapping

Keep listing-intent state separate from deal state. Never use one enum for both.

**Listing intent** (seller preparation only):
- `intent_only`: backend intent exists; no on-chain NFT lock is proven.
- `active`: the exact NFT is locked in the associated deal/escrow according to reconciled contract state and it may be eligible for a buyer deal.
- `reserved`: a deal is already in progress; do not present the asset as available to another buyer.
- `cancelled`: seller cancelled before buyer funds were accepted, and any NFT return is reconciled.
- `manual_review`: do not allow new buyer actions.

**Deal status** — use the backend's snake_case values as stable transport values, with human-readable labels in the frontend:

| Backend status | Frontend meaning | User action |
|---|---|---|
| `intent_created` | Сделка подготовлена, контракт ещё не подтверждён | None |
| `awaiting_nft` | Ожидается депозит NFT продавцом | Seller deposits exact NFT |
| `awaiting_buyer_funds` | NFT зафиксирован, ожидается TON покупателя | Buyer funds exact principal |
| `funded_review` | NFT и TON заблокированы; идёт окно проверки до передачи | Buyer accepts or opens dispute |
| `nft_release_pending` | Запрошена передача NFT; финальность ещё не подтверждена | Wait / open allowed dispute path |
| `delivered_dispute_window` | Oracle-attested delivery at finality; dispute window running | Buyer may dispute before deadline |
| `disputed` | Спор активен, settlement frozen | Wait for resolver / return requirements |
| `nft_return_pending` | NFT возврат/повторная доставка выполняется | Wait; do not promise refund yet |
| `seller_payout_pending` | Выплата продавцу отправлена, но ещё не финализирована | Wait / show pending |
| `buyer_refund_pending` | Возврат покупателю отправлен, но ещё не финализирован | Wait / show pending |
| `settled` | Финализированный payout подтверждён | Read-only |
| `refunded` | Финализированный refund подтверждён и условия возврата NFT выполнены | Read-only |
| `expired` | Сделка завершилась до принятия средств; NFT не остаётся в escrow | Read-only |
| `manual_review` | Конфликт/неполная цепочка доказательств; активы удерживаются | Read-only; show support/escalation |

Do not expose a post-delivery `confirm_receipt` button as a state transition in this model. Buyer acceptance happens in `funded_review` before NFT release. The post-delivery timer begins only after the evidence oracle/quorum attestation is accepted by the contract and its state is reconciled.

Payout is contract-initiated after the dispute window or authorized seller-favourable resolution. The buyer/seller UI should display `seller_payout_pending` and `buyer_refund_pending` as waiting states; do not add manual "claim proceeds" buttons unless a future ABI explicitly implements claimable balances.

### 6.5 Resource and API sequencing — bind the buyer before deployment

The public marketplace listing and the immutable on-chain deal contract are different resources:

1. Seller creates/maintains the existing off-chain marketplace listing and a seller-scoped escrow listing intent. This does not claim that an NFT is already in escrow.
2. Buyer selects the public listing and creates a deal intent. This binds the buyer's verified testnet wallet and snapshots seller wallet, buyer wallet, NFT item, TON principal, network and deal salt.
3. Only after the buyer is bound may the backend prepare deployment of the immutable per-deal DealEscrow. The deployment request is sourced from the deal snapshot, not a seller-only listing intent.
4. Seller signs the deployment/deposit operation from their own verified wallet (exact sequence depends on the reviewed factory UX); the contract address and state-init/code hash are persisted only after independent chain reconciliation.
5. Seller deposits the exact NFT into that DealEscrow. The contract validates the TEP-62 notification and enters AWAITING_BUYER_FUNDS.
6. Buyer may fund only after that contract state is confirmed. The contract then enters FUNDED_REVIEW.
7. Observer evidence, oracle-attested contract transitions and participant-scoped read APIs project the remainder of the deal.

**Do not deploy the immutable DealEscrow from a seller-only intent before a buyer wallet is known.** A `DEPLOY_LISTING` operation that binds no buyer is a different reusable-listing topology and must not be mixed with this per-deal design. Prefer a deal-scoped deployment preparation endpoint. Public buyer discovery also needs an explicit read contract that exposes only approved public listing facts plus the identifier needed to create a deal; a seller-only `GET /listing-intents/{id}` is not sufficient to power the buyer marketplace.

## 7. Wallet action preparation contract

The backend may prepare an unsigned TON Connect transaction request. It must not sign it or infer that it succeeded.

Minimum semantic response:

- action_id: backend UUID for idempotent preparation/audit;
- action: one of the canonical action names;
- network: testnet only;
- valid_until: explicit expiry;
- messages[]: destination address, amount in nanotons as a string, and exact payload/state-init bytes needed by TON Connect;
- display: human-readable network, contract, NFT, price, fee, recipient and purpose shown before signature.

The exact TypeScript/Pydantic transport schema may be adapted to the current TON Connect SDK, but both teams must preserve these semantics. Bind the action to the authenticated user and server-verified wallet. The frontend must validate each message destination against an action-specific allowlist (e.g. NFT item for a seller TEP-62 deposit, DealEscrow for buyer funding/accept/dispute) and show each message destination and amount before signing; a backend-provided summary string alone is insufficient. Never trust client-submitted seller/buyer addresses, amount, fee, contract address or state transition. A returned wallet/BOC hash is a lookup hint only; observer evidence is authoritative. Payout/refund in the PoC are contract-initiated and are not arbitrary frontend-signed withdrawals.

## 8. Shared end-to-end acceptance scenarios

Both contract and backend suites, plus frontend integration tests where applicable, must cover the same cases:

1. **Happy path:** create a single-deal escrow -> seller deposits exact allowlisted NFT -> contract validates and records the NFT lock -> buyer sends exact TON principal plus execution reserve -> funds are locked in FUNDED_REVIEW -> buyer accepts -> escrow requests NFT transfer -> observer records finalized delivery evidence -> evidence oracle/quorum attests it to the contract -> contract state reconciles to DELIVERED_DISPUTE_WINDOW -> dispute window expires without dispute -> seller payout is initiated and independently reconciled at finality -> SETTLED.
2. **Two buyers race:** only one buyer can acquire the single-sale listing; the losing payment is rejected or enters an explicit refundable path, never silently retained.
3. **Wrong NFT / spoofed deposit:** wrong item, wrong previous owner, wrong collection/item, duplicate or mismatched listing key never activates the listing.
4. **Payment mismatch:** underpayment, overpayment, wrong sender, duplicate payment and stale query ID never produce a second sale or an untracked balance.
5. **Buyer never confirms:** timer does not start from the emitted NFT transfer; seller proceeds remain locked. The UI explains the pending state and escalation path.
6. **Outbound transfer bounce / ambiguous trace:** enter recoverable exception; do not assume the prior transaction rolled back; do not auto-release seller funds or auto-refund without proof.
7. **Buyer disputes during FUNDED_REVIEW or DELIVERED_DISPUTE_WINDOW:** freeze settlement and follow the phase-specific resolver / NFT-return path; no seller payout while disputed.
8. **Buyer-favourable resolution after NFT left escrow:** no refund until exact NFT is returned to escrow and return is verified.
9. **Seller-favourable resolution:** seller payout is initiated only after authorized on-chain resolution and finalized NFT delivery evidence, then remains pending until payout finality.
10. **Payout/refund bounce or duplicate trigger:** the pending settlement stays owed to the same fixed recipient; retries are blocked until the original outcome is reconciled, and no duplicate transfer occurs.
11. **Observer restart / replay:** duplicated and out-of-order traces, provider outage, cursor restart and database rebuild preserve the same final projection; a transaction first observed as non-final and later finalized must be promoted exactly once, not stuck as rejected/duplicate.
12. **Security / authorization:** IDOR, wrong participant, unverified wallet, client-forged state, wrong network and stale payload are rejected.

## 9. ABI freeze checklist

Before the contract ABI is treated as shared/frozen, all workstreams must review and agree on:

- [ ] exact factory/single-deal deployment model and deterministic address derivation;
- [ ] exact TEP-62 deposit notification and authenticity/allowlist strategy;
- [ ] action opcodes, cell layouts, query ID widths and forwarded payload format;
- [ ] all state transitions, including delivery exception and payout-bounce recovery;
- [ ] exact payment/forwarding/gas accounting and under/overpayment behavior;
- [ ] zero-fee PoC invariant; fee arithmetic/rounding only in a later explicitly reviewed commission change;
- [ ] resolver identity/powers and dispute evidence policy;
- [ ] buyer review timeout, oracle-attested delivery timer start, dispute timeout and no-confirmation recovery;
- [ ] getters / state serialization needed by backend reconciliation;
- [ ] ABI fixtures and shared positive/negative transaction vectors;
- [ ] testnet network/address configuration and deployment manifest format.

Until this checklist is reviewed, implementations must label the ABI adapter as provisional and must not invent opcodes or payload layouts independently.

## 10. Workstream ownership

- **Contract agent:** exact on-chain ABI, state storage, TEP-62 message handling, factory/single-deal instance, oracle/resolver authority checks, sandbox tests and deployment fixtures under contracts/escrow/**.
- **Backend agent:** observer, projection, API and escrow-only migrations under backend/app/escrow/**, backend/app/api/escrow.py, backend/tests/escrow/** and escrow migrations.
- **Frontend agent:** view models, wallet action rendering, transaction preparation client and UX under frontend/src/escrow/**, frontend/src/api/escrow.ts and escrow tests.
- **Coordinator:** this interface, ADR/design documents, shared fixtures/acceptance matrix and cross-workstream review. No overlapping application implementation files.

The existing docs/TON_TESTNET_ESCROW_ARCHITECTURE.md is the source threat-model proposal; this shared contract reconciles the selected MRKT-like product flow with the existing security review. If a material change is proposed to topology, timers, oracle/resolver powers or refund guarantees, update both documents in one reviewed change. A workstream may propose a change to this document, but must not quietly diverge from it. Record the proposed change and its security/compatibility impact for review before implementing dependent work.
