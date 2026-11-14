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
2. **One escrow per single-sale listing is the PoC default.** A ListingEscrow instance holds the listing NFT and, after a purchase, the buyer's TON. It is single-use for one sale. The factory/registry maps one stable listing key to one escrow address. The contract agent may challenge this with a concrete security or TON-runtime reason before ABI freeze.
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
| escrow_address | Address of the single-sale ListingEscrow instance | Persist canonical raw form as well as display-friendly form |
| nft_item_address | Expected TEP-62 NFT item contract | Must match the item that deposits and the item escrow transfers |
| seller_wallet, buyer_wallet | TON addresses bound to transaction actors | Normalize before comparison; do not trust client-supplied actor identities |
| operation_id | Backend UUID identifying one requested user operation | Unique in the database; mapped to an on-chain query identifier |
| query_id | Contract-message correlation/replay identifier | Unique in the relevant escrow scope; never use it as the only chain-event identity |
| price_nano | Exact listing price in nanotons | Integer/string representation only; never float |
| fee_bps | Immutable fee snapshot in basis points | Range 0..10,000; fee calculation and rounding must be explicit |
| deadline_unix | UTC Unix timestamp for a contract-enforced deadline | Exact start event must be specified; never infer from UI time |

Amounts crossing API boundaries are decimal strings containing integer nanotons. Frontend conversion to TON is presentation-only. Attached TON needed for storage/compute/forwarding is separate from the agreed listing price and must be displayed before wallet signing. The contract must reject or safely quarantine underpayment, overpayment and unexpected-value cases; it must never silently reinterpret attached value as a changed listing price.

## 3. Canonical escrow state machine

The escrow state is independent of the existing backend OrderStatus.

| State | Meaning | Allowed next states |
|---|---|---|
| awaiting_nft_deposit | Escrow is initialized; expected NFT has not been accepted | listed, deposit_rejected, cancelled |
| listed | Expected NFT is held by escrow and the single sale is available | payment_received, cancelled |
| payment_received | Exact buyer price is accepted and funds are locked | delivery_pending, delivery_exception, refundable_failure |
| delivery_pending | Contract initiated outgoing TEP-62 transfer; delivery is not yet accepted as complete | buyer_confirmation_window, disputed, delivery_exception, refundable_failure |
| buyer_confirmation_window | Buyer explicitly confirmed receipt; dispute deadline is running | settled, disputed |
| disputed | Settlement is frozen until authorized resolution completes | settled, refund_pending_nft_return, refundable_failure, delivery_exception |
| refund_pending_nft_return | Buyer-favourable resolution requires NFT to be returned to escrow | refunded, delivery_exception |
| delivery_exception | Chain outcome is ambiguous or a message bounced; assets/proceeds remain locked | buyer_confirmation_window, disputed, refundable_failure |
| refundable_failure | Specific failure is proven and buyer refund is authorized | refunded |
| settled | Seller proceeds and treasury fee are fixed as claimable entitlements | terminal deal state |
| refunded | Buyer refund is fixed as a claimable entitlement | terminal deal state |
| cancelled | Unsold listing is cancelled; seller may withdraw NFT | terminal sale state |
| deposit_rejected | Deposit did not satisfy configured item/seller/listing checks | terminal sale state, subject to explicit safe asset recovery |

### 3.1 Critical delivery / timeout rule

**The buyer-confirmation timer must not start merely because escrow emitted an outbound NFT transfer message.** TON messages are asynchronous, and sending a message is not proof that the buyer became the NFT owner.

For this PoC, the conservative default is:

- Escrow enters delivery_pending after it initiates the NFT transfer.
- The buyer may call confirm_receipt only after checking the NFT in their wallet. That signed action moves the deal into buyer_confirmation_window and starts the dispute deadline.
- The buyer may instead open a dispute while delivery is pending.
- If the buyer never confirms, the contract must not release seller proceeds just because a timer measured from message emission expired. The deal remains locked/recoverable until a reviewed evidence or dispute-resolution path is executed.
- An oracle/attestor that can start the timer without buyer confirmation is a separate trust decision. Do not add one implicitly; document its authority, compromise impact and verification model first.

This is intentionally conservative: it may leave a deal pending, but it does not pay the seller on unproven delivery.

### 3.2 Resolution and asset-return rule

- Seller-favourable resolution may move disputed to settled.
- Buyer-favourable resolution before the NFT has left escrow may authorize refundable_failure or refunded, according to actual chain evidence.
- Buyer-favourable resolution after the NFT reached the buyer must move to refund_pending_nft_return. The buyer must transfer the same NFT item back to escrow, and escrow must verify the return before the buyer refund becomes claimable.
- A contract cannot forcibly retrieve an NFT from a buyer-controlled wallet. Never promise an unconditional refund after irreversible NFT delivery.

### 3.3 Claims are operations, not new sale states

settled means the seller's net amount and platform fee have been fixed and are claimable; it does not mean the TON transfer to either recipient has completed. refunded means the buyer refund is claimable; it does not mean the refund transfer has completed.

The interface must separately expose idempotent claim operations and their outcomes:

- claim_seller_proceeds
- claim_treasury_fee
- claim_buyer_refund
- withdraw_unsold_nft (only after cancelled)

A payout is not complete merely because an outbound message was emitted. The contract must retain enough accounting to handle duplicate claims and bounced transfers without losing or double-crediting claimable value. Claim processing may use separate pending/claimed accounting while the deal state remains terminal.

## 4. Canonical user / contract actions

These are semantic action names, not frozen opcodes.

| Action | Authorized actor | Preconditions | Required result |
|---|---|---|---|
| create_listing_escrow | Factory deploy authority / configured seller flow | Valid immutable listing config; unique listing key | One escrow address mapped to listing key |
| deposit_nft | Seller via TEP-62 transfer | Expected NFT item, seller as previous owner, matching listing/deposit correlation data | awaiting_nft_deposit -> listed only after verified notification |
| buy | Buyer | State listed; exact configured price; no existing buyer | Funds locked once; listed -> payment_received |
| initiate_nft_delivery | Escrow contract | Payment locked; exact buyer/item snapshot | payment_received -> delivery_pending; transfer request recorded |
| confirm_receipt | Bound buyer wallet | Buyer independently checked NFT ownership | delivery_pending -> buyer_confirmation_window; deadline begins |
| open_dispute | Bound buyer wallet | Deal pending or in confirmation window; before relevant deadline where applicable | Deal frozen in disputed |
| resolve_dispute_seller | Narrowly configured dispute resolver | Deal is disputed | disputed -> settled |
| resolve_dispute_buyer | Narrowly configured dispute resolver | Deal is disputed | disputed -> refund_pending_nft_return if NFT left escrow; otherwise proven refundable path |
| return_nft_to_escrow | Bound buyer via TEP-62 transfer | Buyer-favourable resolution requires return | Verify exact item and expected owner; refund_pending_nft_return -> refunded |
| claim_seller_proceeds | Bound seller wallet | settled; positive seller claimable balance | Idempotent payout with bounce-safe accounting |
| claim_treasury_fee | Configured treasury | settled; positive treasury claimable balance | Idempotent payout with bounce-safe accounting |
| claim_buyer_refund | Bound buyer wallet | refunded; positive buyer claimable balance | Idempotent payout with bounce-safe accounting |
| cancel_listing | Bound seller wallet | listed; no buyer funds accepted | listed -> cancelled |
| withdraw_unsold_nft | Bound seller wallet | cancelled; NFT is still escrow-owned | Transfer exact NFT to seller; safe retry/recovery semantics |

Any additional action must specify actor, source state, destination state, replay key, attached-value requirements, bounce behavior and chain evidence before it is added to the ABI.

## 5. NFT deposit and authenticity requirements

The contract must not trust an arbitrary incoming NFT notification. At minimum, validate the notification sender against the expected NFT item contract, previous owner against the configured seller, and forwarded listing/deposit correlation data against escrow configuration.

The PoC must explicitly choose and test an authenticity strategy:

- fixed allowlist of exact test NFT item addresses; or
- a reviewed collection/item derivation strategy that the contract can verify without pretending it can synchronously call another contract's getter.

Backend collection metadata or an API response is not on-chain proof. Unsolicited, wrong-item, wrong-seller, duplicate and malformed notifications must not make a listing active. Define a safe recovery path for an NFT that has already reached the escrow address but fails validation.

## 6. Chain evidence and backend projection

TON contracts do not produce EVM-style receipt logs. The backend observer must parse relevant account transactions and inbound/outbound messages, correlate the complete message trace where necessary, and reconcile the contract's current state/getters. The normalized event names below are an application-level projection, not a claim that TON emits Solidity logs.

### 6.1 Normalized event vocabulary

Use stable semantic names across backend and frontend:

- escrow_created
- nft_deposit_observed
- listing_activated
- buyer_payment_observed
- nft_delivery_requested
- nft_delivery_bounced
- buyer_receipt_confirmed
- dispute_opened
- dispute_resolved_seller
- dispute_resolved_buyer
- nft_return_observed
- seller_proceeds_claimed
- treasury_fee_claimed
- buyer_refund_claimed
- listing_cancelled
- unsold_nft_withdrawn
- delivery_exception_opened
- escrow_reconciled

An observer may emit more than one normalized event for one transaction trace. Event consumers must be idempotent.

### 6.2 Minimum observation record

Every persisted chain observation must carry enough evidence to be independently replayed:

| Field | Purpose |
|---|---|
| network | Explicit testnet in this PoC |
| account_address | Contract/item account whose transaction is observed |
| transaction_hash and logical_time | Transaction identity and ordering |
| message_hash | Exact inbound/outbound message identity when available |
| source_address, destination_address, attached_value_nano | Message routing and value |
| query_id / operation_id | Correlation and replay detection |
| listing_key | Listing identity |
| normalized_event_type | Semantic event type |
| observed_state, contract_state | Observed and reconciled state |
| raw_evidence_hash | Hash/reference for retained raw trace evidence |
| finality_status | Provider/chain finality classification used by observer |
| observed_at | Backend UTC timestamp; not a chain deadline |

Use a unique chain-event key such as (network, account_address, transaction_hash, message_hash) where available. Do not deduplicate solely by query ID. Store enough raw or content-addressed evidence to replay a decision. A provider outage, incomplete message trace, inconsistent getter result or non-final transaction must leave the projection pending/exceptional, never successful.

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

## 7. Wallet action preparation contract

The backend may prepare an unsigned TON Connect transaction request. It must not sign it or infer that it succeeded.

Minimum semantic response:

- action_id: backend UUID for idempotent preparation/audit;
- action: one of the canonical action names;
- network: testnet only;
- valid_until: explicit expiry;
- messages[]: destination address, amount in nanotons as a string, and exact payload/state-init bytes needed by TON Connect;
- display: human-readable network, contract, NFT, price, fee, recipient and purpose shown before signature.

The exact TypeScript/Pydantic transport schema may be adapted to the current TON Connect SDK, but both teams must preserve these semantics. Bind the action to the authenticated user and server-verified wallet. Never trust client-submitted seller/buyer addresses, amount, fee, contract address or state transition. A returned wallet hash is a lookup hint only; observer evidence is authoritative.

## 8. Shared end-to-end acceptance scenarios

Both contract and backend suites, plus frontend integration tests where applicable, must cover the same cases:

1. **Happy path:** create escrow -> seller deposits exact allowlisted NFT -> backend observes finalized deposit -> listing becomes available -> buyer sends exact TON price -> funds are locked -> escrow requests NFT transfer -> buyer explicitly confirms receipt -> confirmation window expires without dispute -> seller and treasury independently claim the exact split.
2. **Two buyers race:** only one buyer can acquire the single-sale listing; the losing payment is rejected or enters an explicit refundable path, never silently retained.
3. **Wrong NFT / spoofed deposit:** wrong item, wrong previous owner, wrong collection/item, duplicate or mismatched listing key never activates the listing.
4. **Payment mismatch:** underpayment, overpayment, wrong sender, duplicate payment and stale query ID never produce a second sale or an untracked balance.
5. **Buyer never confirms:** timer does not start from the emitted NFT transfer; seller proceeds remain locked. The UI explains the pending state and escalation path.
6. **Outbound transfer bounce / ambiguous trace:** enter recoverable exception; do not assume the prior transaction rolled back; do not auto-release seller funds or auto-refund without proof.
7. **Buyer disputes before receipt confirmation:** freeze settlement; no seller claim.
8. **Buyer-favourable resolution after NFT left escrow:** no refund until exact NFT is returned to escrow and return is verified.
9. **Seller-favourable resolution:** funds become claimable only after authorized on-chain resolution.
10. **Payout bounce / duplicate claim:** claimable balances are neither lost nor paid twice.
11. **Observer restart / replay:** duplicated and out-of-order traces, provider outage, cursor restart and database rebuild preserve the same final projection.
12. **Security / authorization:** IDOR, wrong participant, unverified wallet, client-forged state, wrong network and stale payload are rejected.

## 9. ABI freeze checklist

Before the contract ABI is treated as shared/frozen, all workstreams must review and agree on:

- [ ] exact factory/listing deployment model and deterministic address derivation;
- [ ] exact TEP-62 deposit notification and authenticity/allowlist strategy;
- [ ] action opcodes, cell layouts, query ID widths and forwarded payload format;
- [ ] all state transitions, including delivery exception and payout-bounce recovery;
- [ ] exact payment/forwarding/gas accounting and under/overpayment behavior;
- [ ] fee arithmetic, rounding and claim split;
- [ ] resolver identity/powers and dispute evidence policy;
- [ ] confirmation timer start rule and no-confirmation recovery;
- [ ] getters / state serialization needed by backend reconciliation;
- [ ] ABI fixtures and shared positive/negative transaction vectors;
- [ ] testnet network/address configuration and deployment manifest format.

Until this checklist is reviewed, implementations must label the ABI adapter as provisional and must not invent opcodes or payload layouts independently.

## 10. Workstream ownership

- **Contract agent:** exact on-chain ABI, state storage, TEP-62 message handling, factory, sandbox tests and deployment fixtures under contracts/escrow/**.
- **Backend agent:** observer, projection, API and escrow-only migrations under backend/app/escrow/**, backend/app/api/escrow.py, backend/tests/escrow/** and escrow migrations.
- **Frontend agent:** view models, wallet action rendering, transaction preparation client and UX under frontend/src/escrow/**, frontend/src/api/escrow.ts and escrow tests.
- **Coordinator:** this interface, ADR/design documents, shared fixtures/acceptance matrix and cross-workstream review. No overlapping application implementation files.

A workstream may propose a change to this document, but must not quietly diverge from it. Record the proposed change and its security/compatibility impact for review before implementing dependent work.
