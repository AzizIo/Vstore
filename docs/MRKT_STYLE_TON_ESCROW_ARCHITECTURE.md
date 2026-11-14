# MRKT-style TON Escrow Architecture for VILTARA

- **Status:** Proposed architecture / testnet PoC only
- **Version:** 0.1
- **Date:** 2026-11-14
- **Branch:** `docs/mrkt-style-ton-escrow-architecture`
- **Related:** ADR-0001, `docs/PAYMENTS_ESCROW_DESIGN.md`, Issue #153
- **Scope:** TEP-62 TON NFTs and native TON only
- **Explicit non-goals:** mainnet deployment, production custody, real-value checkout, Telegram Stars conversion, Telegram Gifts, private-key custody, and any claim of audited security.

> This document records the product direction selected by the maintainer: a marketplace flow in which the seller deposits an NFT into an on-chain escrow contract and the buyer's TON is held by escrow until the settlement conditions are met. It does not approve production launch or supersede ADR-0001 until the ADR is formally reviewed and amended.

## 1. Product decision

VILTARA is to move from direct seller-to-buyer delivery to a custodial-on-chain marketplace model:

1. Seller deposits the NFT into an escrow contract.
2. The listing becomes purchasable only after the deposit is confirmed.
3. Buyer pays the exact TON amount to the listing escrow.
4. The escrow initiates NFT transfer to the buyer's verified wallet.
5. The TON remains locked during the buyer confirmation / dispute window.
6. On buyer confirmation or expiry without a dispute, the seller can claim the net proceeds and the platform fee is routed to the configured treasury.
7. If delivery fails before the NFT leaves escrow, the buyer can receive a refund under the contract's explicit failure path.
8. If the NFT has already reached the buyer, a buyer-favourable dispute refund requires the NFT to be returned to escrow first. A contract cannot unilaterally seize an NFT from a buyer-controlled wallet.

The product must not describe the system as risk-free or guarantee a refund in cases where the NFT has irreversibly left escrow.

## 2. Important compatibility and launch gates

- Existing `orders` and the current non-custodial delivery observer are implemented on `main`. They must not be silently repurposed as escrow state.
- Existing Telegram Stars test payments remain a separate payment domain. Stars do not represent TON held by an escrow contract and must never credit TON seller balances.
- ADR-0001 currently rejects production escrow and treats TON Connect in-app checkout as unresolved. This proposal requires an explicit ADR amendment and maintainer review.
- Telegram policy classification for peer-to-peer NFT resale inside a Mini App must be obtained in writing before enabling an in-app TON purchase flow. Technical feasibility does not establish platform permission.
- Legal/compliance review is required for custody, disputes, seller settlement, sanctions, tax and consumer protection in the jurisdictions where the service operates.
- Mainnet deployment is blocked until independent smart-contract audit, testnet acceptance, operational runbooks, and policy/legal gates are complete.

## 3. Proposed contract topology

### 3.1 MarketplaceFactory

A small factory / registry contract:

- deploys one isolated ListingEscrow instance per listing;
- binds immutable listing parameters to the instance: seller address, NFT item address, price, currency (TON), fee basis points, treasury address, confirmation window, dispute authority and protocol version;
- emits / exposes deterministic listing-to-escrow mapping;
- prevents duplicate escrow instances for the same listing identifier;
- does not hold buyer funds or NFTs itself.

### 3.2 ListingEscrow

One contract instance per NFT listing. It is the on-chain source of truth for that listing and its active sale:

- receives and holds the seller's NFT;
- accepts exactly the configured purchase price plus explicitly specified network-fee allowance;
- stores the buyer, payment amount, timestamps and state;
- initiates standard TEP-62 NFT transfer;
- holds TON until settlement;
- supports buyer confirmation, dispute opening, seller claim, buyer refund and seller withdrawal only in explicitly allowed states;
- applies the fee snapshot and sends the fee to the treasury only on successful settlement;
- rejects duplicate or out-of-order operations.

The NFT and TON may be held by the same ListingEscrow address. A separate deal contract per purchase is an alternative if the PoC demonstrates that a reusable listing instance creates unsafe state complexity. The first PoC should compare both designs before freezing the ABI.

### 3.3 Treasury

The platform fee destination should be a separately controlled treasury wallet, preferably multisig for operational use. It must not have arbitrary access to buyer funds or NFT custody. Fee percentage and treasury address are snapshotted when the listing is created; changes apply only to future listings.

### 3.4 Dispute authority

A narrowly scoped dispute resolver may submit a resolution for a disputed deal. It must not be able to withdraw arbitrary funds, change seller/buyer addresses, rewrite completed deals or upgrade contract code.

For PoC, use a testnet multisig or a clearly isolated test authority. Production governance requires a separate threat model, signer policy, key-rotation and incident-recovery runbook.

## 4. State machine

The state machine is separate from the existing backend `OrderStatus`.

| State | Meaning | Allowed next states |
|---|---|---|
| `awaiting_nft_deposit` | Escrow instance created; expected NFT not yet accepted | `listed`, `deposit_rejected`, `cancelled` |
| `listed` | NFT is held by escrow and listing is available | `payment_received`, `seller_withdrawn` |
| `payment_received` | Exact buyer payment accepted and locked | `delivery_pending`, `refundable_failure` |
| `delivery_pending` | Escrow has emitted NFT transfer request | `buyer_confirmation_window`, `delivery_exception` |
| `buyer_confirmation_window` | Transfer flow has progressed; funds remain locked | `settled`, `disputed`, `delivery_exception` |
| `disputed` | Settlement is frozen pending an allowed resolution | `settled`, `refund_pending_nft_return`, `refundable_failure` |
| `refund_pending_nft_return` | Buyer-favourable resolution requires NFT to be returned to escrow | `refunded` |
| `settled` | Seller proceeds and platform fee are claimable/paid | terminal |
| `refunded` | Buyer refund completed under contract rules | terminal |
| `seller_withdrawn` | Seller reclaimed unsold NFT | terminal |
| `deposit_rejected` / `cancelled` / `refundable_failure` | Terminal failure/cancellation paths | terminal or explicit recovery path |

No backend request or database update may directly advance an on-chain state. Backend state is a projection of confirmed chain evidence.

### 4.1 Settlement policy proposed for PoC

- Buyer can confirm receipt at any time during the confirmation window.
- Buyer can open a dispute before the deadline; this freezes settlement.
- If no dispute is opened before the deadline, the seller may claim proceeds after the contract's timeout condition is met.
- A seller-favourable dispute resolution releases the seller proceeds.
- A buyer-favourable dispute resolution refunds the buyer only when the NFT is still held by escrow or has been returned to escrow and the return is confirmed.
- A failed or ambiguous NFT transfer must not automatically be treated as successful delivery or as an unconditional buyer refund. It enters a recoverable exception state and requires explicit evidence / recovery procedure.

The confirmation-window duration, dispute authority, arbitration policy and exact timeout semantics remain configuration decisions for ADR approval.

## 5. NFT deposit and authenticity

TON NFTs follow TEP-62: each item is a separate contract, and ownership transfer is requested using the standard `transfer` message. The escrow must not treat an arbitrary incoming message as proof of a valid deposit.

The PoC must define and test:

- accepted collection policy (allowlist for the first testnet release);
- verification that the item address belongs to the claimed collection;
- expected item address derivation / validation strategy;
- sender and owner checks for the TEP-62 transfer notification;
- exact listing ID / query ID binding to prevent deposit substitution;
- handling of unsolicited NFT transfers;
- handling of zero or insufficient `forward_amount` and missing notifications;
- whether the contract can prove collection membership on-chain for the supported collection implementations.

Backend/indexer verification is useful for catalogue integrity but is not a substitute for on-chain validation where the contract is expected to enforce asset authenticity. TON contracts cannot synchronously call another contract's getter; any cross-contract verification must use messages or deterministic derivation / allowlists.

## 6. Asynchronous delivery and failure semantics

TON contract messages are asynchronous. NFT transfer and TON settlement are not a single atomic operation. The implementation must model every message hop and its bounce / timeout outcomes.

Required rules:

- unique `query_id` / operation ID for every state-changing action;
- idempotent handling of duplicate messages;
- explicit handling of bounced messages before parsing their original operation body;
- no state transition based only on a message being emitted;
- distinguish “transfer request sent”, “NFT item transaction processed”, “buyer wallet notification emitted” and “backend observer independently verified ownership”;
- never infer that a bounce automatically rolls back a previous transaction;
- reserve sufficient TON for storage, compute, forwarding and recovery messages;
- do not send the whole contract balance as a payout;
- reject replayed, stale, wrong-sender and wrong-state messages;
- preserve funds and enter a recoverable state when outcome is ambiguous.

The contract's actual guarantees depend on the exact NFT item implementation. The test matrix must include standard TEP-62 reference items and supported marketplace-compatible item implementations.

## 7. Backend architecture

Keep the current modular monolith. Do not introduce microservices for the first escrow PoC.

Proposed modules (names are provisional):

- `backend/app/escrow/domain.py` — escrow state projection, enums and transition validation;
- `backend/app/escrow/chain.py` — TON provider / transaction evidence adapter;
- `backend/app/escrow/observer.py` — leased, idempotent chain observer with cursor and reorg/finality policy;
- `backend/app/escrow/service.py` — listing/deal orchestration and reconciliation;
- `backend/app/api/escrow.py` — participant-scoped read APIs and wallet transaction payload preparation;
- `backend/app/db/escrow.py` — SQLAlchemy models / repositories;
- dedicated Alembic migration(s) only after schema review.

The backend may:
- create an escrow deployment intent;
- prepare wallet transaction payloads;
- index contract events and transaction traces;
- reconcile contract getters / account state using trusted provider evidence;
- expose buyer/seller status and history;
- notify participants.

The backend may not:
- custody user private keys or sign user transactions;
- claim an NFT is deposited solely because the client says so;
- mark funds paid, refunded or claimable without contract evidence;
- alter contract state in PostgreSQL as if that changed chain state;
- expose admin endpoints that can arbitrarily release escrow funds.

### 7.1 Database projection

Create separate escrow tables, not new payment-like statuses in the existing `orders` table. Suggested records:

- `escrow_listings`: listing ID, escrow address, seller wallet, NFT item address, collection address, price, fee snapshot, deployment state, observed chain state;
- `escrow_deals`: escrow listing ID, buyer wallet, exact amount, operation/query IDs, state projection, deadlines;
- `escrow_chain_events`: unique chain transaction/message identifiers, block/lt/hash, event type, raw evidence hash, processed timestamp;
- `escrow_disputes`: deal ID, opener, reason code, evidence references, resolution actor and resolution evidence;
- `escrow_withdrawals`: claimant, amount, destination, request ID and confirmed chain transaction.

Use unique constraints for chain event identity and operation IDs. Keep an append-only event history. The DB is a rebuildable projection, never the source of truth for escrow ownership or balances.

## 8. Frontend / TON Connect

The Mini App should expose explicit wallet actions:

- Deposit NFT into escrow
- Wait for deposit confirmation
- View locked listing
- Buy with TON
- View payment / NFT transfer progress
- Confirm receipt
- Open dispute
- Return NFT to escrow when required by dispute resolution
- Claim seller proceeds
- Withdraw unsold NFT

Before every wallet signature, show the exact network, contract address, NFT item, amount, fee, recipient and action. No seed phrase or private key collection. Wallet connection alone is not proof of ownership; continue to use the existing TON Proof verification for account binding.

## 9. Contract and integration testing

The testnet PoC must include deterministic local sandbox tests and end-to-end testnet tests.

### Contract unit / sandbox matrix

- valid NFT deposit;
- wrong NFT item / unapproved collection;
- spoofed notification;
- duplicate deposit;
- seller withdrawal before sale;
- withdrawal blocked after purchase starts;
- exact payment;
- underpayment / overpayment / wrong sender;
- two buyers racing for one listing;
- duplicate payment message;
- NFT transfer success path;
- bounced NFT transfer request;
- failed buyer notification;
- duplicate confirmation;
- confirmation after deadline;
- dispute before deadline;
- dispute after settlement;
- seller-favourable resolution;
- buyer-favourable resolution with NFT returned;
- buyer-favourable resolution without NFT return (must not pay refund);
- duplicate seller claim;
- fee calculation and rounding;
- insufficient gas / storage reserve;
- unexpected messages and unsolicited TON;
- replay, stale operation ID and wrong sender;
- contract balance invariants across every terminal state.

### Backend integration matrix

- observer restart and cursor resume;
- duplicate and out-of-order chain events;
- provider outage / lag;
- same transaction trace seen more than once;
- database rebuild from chain evidence;
- participant authorization and IDOR;
- concurrent reservation / purchase attempts;
- DB projection diverges from contract getter;
- no client-side path can fabricate a settled/refunded state.

### Release gates

1. Contract ABI and state machine reviewed.
2. Threat model and failure matrix approved.
3. Local sandbox suite green.
4. Testnet deployment with valueless test NFTs and test TON only.
5. Manual Tonkeeper / TON Connect acceptance.
6. Independent security review of contract code.
7. Written platform policy ruling and qualified legal/compliance review.
8. Explicit maintainer approval before any mainnet or real-value use.

## 10. Workstream boundaries

To avoid file conflicts, implementation should be split only after the ABI and state machine are frozen.

- **Contract workstream:** `contracts/escrow/**`, `contracts/tests/escrow/**`. Owns factory, ListingEscrow, ABI, contract tests and local sandbox.
- **Backend workstream:** `backend/app/escrow/**`, `backend/app/api/escrow.py`, `backend/tests/escrow/**`, escrow-specific migrations. Must not edit existing order/payment modules without coordinator approval.
- **Coordinator / architecture:** this document, ADR amendment, shared ABI contract, end-to-end scenarios and cross-workstream review. Owns no overlapping implementation files.

No agent may deploy to mainnet, access production wallets, request secrets, or modify production services. Each workstream uses its own branch and opens a draft PR; no merge without review.

## 11. Open decisions before implementation freeze

1. One reusable ListingEscrow per listing vs a separate DealEscrow per purchase.
2. Exact NFT collection allowlist and on-chain item authenticity strategy.
3. Confirmation window duration and automatic settlement policy.
4. Who arbitrates disputes and what evidence is accepted.
5. Buyer-favourable dispute path after NFT delivery (NFT return requirement).
6. Whether the platform fee is paid immediately on seller settlement or separately claimable.
7. Contract immutability vs controlled upgrades; default PoC recommendation is immutable code and redeploy/migrate rather than privileged arbitrary upgrades.
8. Telegram in-app policy ruling for TON-priced NFT resale.
9. Jurisdictional legal/compliance review for custody and seller payouts.

Until these are resolved and reviewed, this document is a proposed testnet architecture, not production authorization.
