# MRKT-style TON Escrow Architecture for VILTARA

- **Status:** Proposed architecture / testnet PoC only
- **Version:** 0.1
- **Date:** 2026-11-14
- **Branch:** `docs/mrkt-style-ton-escrow-architecture`
- **Related:** ADR-0001, [PAYMENTS_ESCROW_DESIGN.md](PAYMENTS_ESCROW_DESIGN.md), [TON_ESCROW_SHARED_INTERFACE.md](TON_ESCROW_SHARED_INTERFACE.md), Issue #153
- **Scope:** TEP-62 TON NFTs and native TON only
- **Explicit non-goals:** mainnet deployment, production custody, real-value checkout, Telegram Stars conversion, Telegram Gifts, private-key custody, and any claim of audited security.

> This document records the product direction selected by the maintainer: a marketplace flow in which the seller deposits an NFT into an on-chain escrow contract and the buyer's TON is held by escrow until the settlement conditions are met. It does not approve production launch or supersede ADR-0001 until the ADR is formally reviewed and amended.

## 1. Product decision

VILTARA is to move from direct seller-to-buyer delivery to a custodial-on-chain marketplace model:

1. Seller and buyer wallets, the exact TEP-62 NFT, TON principal and deal salt are snapshotted for one deal.
2. A single-deal immutable escrow contract is deployed; seller deposits the NFT first.
3. The contract validates the exact NFT item, previous owner, query ID and deal hash before accepting buyer funds.
4. Buyer pays the exact TON principal plus a separately specified execution reserve; both NFT and TON are then held by escrow during the buyer review window.
5. Buyer accepts or disputes. On acceptance, the escrow initiates the NFT transfer to the buyer's verified wallet.
6. A separate evidence observer correlates the exact NFT transaction/trace. A configured evidence oracle/quorum attests finalized delivery to the contract; only then does the post-delivery dispute window begin.
7. If that window closes without a dispute, seller payout is initiated and remains pending until finalized payout evidence is reconciled.
8. A buyer-favourable post-delivery dispute requires the same NFT to be returned to escrow first. A contract cannot unilaterally seize an NFT from a buyer-controlled wallet.

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

- deploys one immutable DealEscrow instance per buyer/seller deal, not one reusable escrow for an entire public listing;
- binds a unique deal salt and immutable terms: seller wallet, buyer wallet, exact NFT item, TON principal, network/protocol version, evidence oracle/quorum, dispute resolver and deadlines;
- emits / exposes deterministic deal-to-escrow mapping;
- prevents duplicate instances for the same deal salt;
- does not itself hold buyer funds or NFTs.

A new purchase attempt uses a new deal instance. The backend's listing intent is an off-chain proposal, not a funded order or chain-state assertion. A contract deployment and validated NFT deposit are required before the contract accepts the buyer's principal.

### 3.2 DealEscrow

One contract instance per deal. It is the on-chain source of truth for that deal:

- receives and holds the exact seller NFT;
- accepts the exact buyer TON principal only after the NFT lock is validated;
- stores the immutable buyer, seller, NFT, principal, deal salt and phase deadlines;
- supports buyer review/accept/dispute, NFT delivery, constrained arbitration, NFT return, payout and refund only in explicitly allowed states;
- has no arbitrary withdrawal or upgrade method;
- rejects duplicate, stale, replayed or out-of-order operations;
- keeps every asset/money movement pending until exact finalized evidence is reconciled.

For the first PoC, use a zero platform fee. Validate the lock/release/refund state machine before adding commission splits.

### 3.3 Evidence oracle and dispute resolver

These are distinct trust roles:

- The evidence oracle/quorum attests only exact finalized on-chain facts (NFT deposit, NFT delivery, NFT return, payout/refund finality). Its signed payload must be domain-separated by network, deal address/salt, action, attempt ID, evidence hash and masterchain checkpoint. It cannot choose a dispute winner or redirect assets.
- The dispute resolver is a constrained 2-of-3 testnet multisig proposal. It can select only enumerated buyer-favourable or seller-favourable outcomes for a valid disputed deal. It cannot upgrade code, change parties/price/NFT or withdraw arbitrary assets.

The backend observer indexes/reconciles evidence and submits evidence references to the configured oracle flow; it is not a dispute authority. Oracle and resolver may not be silently implemented as the same key/role.

### 3.4 Testnet fee policy

The initial PoC fee is fixed at zero. Do not configure a nonzero fee while the backend and contract tests assume the seller payout equals the entire principal. Treasury/commission logic is future work requiring a separate reviewed change.



## 4. State machine

The canonical state machine, normalized event vocabulary, action preconditions and backend/frontend projection contract are defined in [TON_ESCROW_SHARED_INTERFACE.md](TON_ESCROW_SHARED_INTERFACE.md). That document is authoritative for cross-workstream integration.

The lifecycle follows the existing testnet threat model:

- The buyer's principal is locked while the NFT remains in escrow during FUNDED_REVIEW.
- Buyer acceptance triggers NFT release; the outbound message alone does not prove delivery.
- The post-delivery dispute timer begins only after the evidence oracle/quorum attests the exact NFT transfer at finalized masterchain checkpoint.
- Seller payout and buyer refund each remain pending until their own finalized transfer evidence is reconciled.
- A timeout only makes a state-specific operation eligible. It does not prove transfer failure, NFT ownership or payout success.
- MANUAL_REVIEW is a hold state, never a success/refund state.

### 4.1 Testnet timing proposal

The existing testnet threat-model proposal defines deterministic defaults: seller deposit 30 minutes, buyer funding 60 minutes, buyer review 24 hours, NFT outbound confirmation grace 30 minutes, post-delivery dispute window 48 hours, arbitration resolution 7 days, and post-delivery NFT return 24 hours. These are testnet fixtures, not production SLAs. The owner must explicitly approve the timing before ABI freeze.

### 4.2 Conditional post-delivery recourse

Once the NFT reaches the buyer, the contract cannot force it back. A buyer-favourable dispute refund therefore requires the exact NFT to be returned to escrow within the agreed return window, then returned to seller before the buyer refund is finalized. If the buyer has moved the NFT elsewhere and cannot return it, the refund path is unavailable. This is conditional recourse, not an unconditional chargeback or guaranteed buyer refund.

The alternative of retaining the NFT in escrow for the full dispute window provides stronger asset-backed protection but delays buyer access and requires a different protocol. It is a separate product decision, not an implicit behavior.



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

For the isolated testnet PoC harness, wallet actions follow the single-deal lifecycle:

- Seller prepares a deal, deposits the exact NFT into DealEscrow and waits for finalized deposit acceptance
- Buyer funds the deal with the exact TON principal plus the published execution reserve
- Buyer reviews the locked assets and accepts or opens a dispute before the review deadline
- Buyer may open a dispute during the oracle-attested post-delivery dispute window
- Buyer returns the NFT to escrow only when the post-delivery buyer-favourable dispute path requires it
- Both parties see pending vs finalized payout/refund states separately
- Seller withdraws an unsold NFT only through the valid pre-funding expiry/cancellation path

**Do not mount a TON purchase CTA in the public Telegram Mini App** until Issue #155's written platform ruling and qualified legal/compliance review clear that exact in-app P2P NFT resale flow. A testnet UI prototype is not permission to expose a purchase flow to users. For a testnet wallet-action screen, show the exact network, contract address, NFT item, every outgoing message destination and amount, fee/reserve, recipient and action before signature. Enforce action-specific destination checks; a backend summary string alone is not enough. No seed phrase or private key collection. Wallet connection alone is not proof of ownership; continue to use the existing TON Proof verification for account binding.

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
- duplicate buyer acceptance and duplicate oracle attestation;
- confirmation after deadline;
- dispute before deadline;
- dispute after settlement;
- seller-favourable resolution;
- buyer-favourable pre-delivery resolution with NFT returned to seller and buyer refund after finality;
- buyer-favourable post-delivery resolution only after buyer returns the exact NFT to escrow, followed by return to seller and refund after finality;
- buyer-favourable post-delivery resolution without NFT return (must not pay refund);
- duplicate seller claim;
- zero-fee configuration enforcement; nonzero commission must be rejected until a separate reviewed design;
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

- **Contract workstream:** `contracts/escrow/**`, `contracts/tests/escrow/**`. Owns factory, DealEscrow, ABI, evidence-oracle/resolver checks, contract tests and local sandbox.
- **Backend workstream:** `backend/app/escrow/**`, `backend/app/api/escrow.py`, `backend/tests/escrow/**`, escrow-specific migrations. Must not edit existing order/payment modules without coordinator approval.
- **Coordinator / architecture:** this document, ADR amendment, [shared interface contract](TON_ESCROW_SHARED_INTERFACE.md), end-to-end scenarios and cross-workstream review. Owns no overlapping implementation files.

No agent may deploy to mainnet, access production wallets, request secrets, or modify production services. Each workstream uses its own branch and opens a draft PR; no merge without review.

## 11. Open decisions before implementation freeze

1. Exact NFT collection allowlist and on-chain item authenticity strategy.
2. Exact evidence-oracle trust model and testnet signer arrangement.
3. Confirm the deterministic testnet timers and permissionless timeout guards.
4. Final 2-of-3 resolver identities and enumerated outcome rules.
5. Conditional post-delivery recourse vs retaining the NFT in escrow for the full dispute window.
6. Treasury/commission model after a zero-fee PoC.
7. Contract immutability vs controlled upgrades; default PoC recommendation is immutable code and redeploy/migrate rather than privileged arbitrary upgrades.
8. Telegram in-app policy ruling for TON-priced NFT resale.
9. Jurisdictional legal/compliance review for custody and seller payouts.

Until these are resolved and reviewed, this document is a proposed testnet architecture, not production authorization.
