# TON testnet escrow architecture (design review)

- **Status:** design-only; not approved for production or deployment
- **Issue:** [#153 — TON testnet buyer-protection PoC](https://github.com/AzizIo/Vstore/issues/153)
- **Policy gate:** [#155 — written Telegram ruling for TON NFT secondary resale](https://github.com/AzizIo/Vstore/issues/155)
- **Payment dependency:** [#152 — Telegram Stars test-environment integration](https://github.com/AzizIo/Vstore/issues/152)
- **Existing delivery baseline:** [#46 — non-custodial NFT delivery observer](https://github.com/AzizIo/Vstore/issues/46)
- **ADR gate:** [ADR-0001](adr/0001-compliant-payments-and-escrow.md), currently Proposed / awaiting maintainer review
- **Reviewed against:** main at a7f8ca859a51e2c34b8ef76ef2903b4d26ddebda
- **Network boundary:** TON testnet only; no mainnet deployment, no production order-flow integration, no real-value funds
- **Implementation decision:** do not implement or deploy the contract until the blockers in §12 are cleared

This document is a technical proposal, not a legal opinion, payment approval, audit, or promise of buyer protection. The current Vstore product remains non-custodial and has no production escrow.

## 1. Executive decision

For a real escrow, use **one immutable, single-deal contract that holds both the NFT and the buyer's native TON testnet deposit**. The seller transfers the NFT into the escrow first. Only after the contract has received and validated the TEP-62 ownership notification may the buyer fund the deal. The buyer then has a review window to accept or dispute. On acceptance, the contract transfers the NFT to the buyer; a separately operated observer confirms the exact transfer at TON masterchain finality. A dispute window follows. The contract pays the seller only after that window closes without a dispute, or after an authorized resolution in the seller's favor.

The contract, not Vstore's API, holds the assets. Vstore's backend is an observer and user-interface coordinator only. It must not hold signing keys, sign TON messages for users, or have an arbitrary withdrawal method.

This is a **testnet-native TON protocol demonstration**, not an in-Telegram checkout design. The contract handles TON, not Telegram Stars (XTR). It cannot lock, escrow, split, or refund a Telegram Stars balance. The existing payment agent's Stars ledger and test bot remain a separate workstream; this document deliberately does not modify them.

### Why hold both assets?

A funds-only escrow would still leave the NFT under the seller's control until the transfer. Holding the NFT in the same per-deal contract prevents the seller from transferring it elsewhere after the buyer has funded the deal, and allows a refund path to return both assets to their original parties. It does add a second TEP-62 transfer and an asynchronous recovery path. TEP-62 does not provide an atomic "safe transfer" rollback if the receiving contract rejects the notification, so the PoC must include recovery for a transfer whose ownership changed but whose callback was not recorded.

## 2. Current Vstore baseline

### 2.1 Order and delivery states

The current OrderStatus in backend/app/db/models.py is:

- reserved
- awaiting_transfer
- observing_transfer
- completed
- cancelled
- expired

OrderDeliveryAttemptStatus is prepared, observing, verified, failed, manual_review or cancelled. There are no production paid, refunded or disputed order states. Do not reintroduce the older pending_payment model from the original payment/escrow design draft, and do not overload delivery states to mean payment states.

The service reserves an active listing after rechecking seller ownership. Delivery preparation snapshots the exact NFT item, network, seller source wallet, buyer destination wallet and a random uint64 query ID. The preparation window is currently 15 minutes. The seller signs the TEP-62 transfer from their own TON Connect wallet; the backend does not sign or broadcast for the seller.

### 2.2 Existing observer

The current delivery observer is a useful model to preserve:

- It uses bounded SKIP LOCKED claims and a per-attempt lease token.
- Provider I/O occurs outside DB transactions; the result is applied only after the lease, order, listing, asset and immutable snapshot are revalidated under locks.
- Candidate hashes from the client are lookup hints, not proof.
- The TON Center v3 adapter requires exact item, sender, recipient and query ID; a non-aborted NFT-item transaction; successful compute and action phases; a complete trace; and a positive mc_seqno_end.
- A successful result stores the transaction hash, trace ID, masterchain seqno and provider source. Incomplete or inconsistent evidence is retried or sent to manual review, not treated as success.
- DB uniqueness constraints prevent reuse of a verified transfer and duplicate active attempts.

The important caveat is already documented by the adapter: TON Center v3 is an indexed data source, not a cryptographic proof verifier. The current mc_seqno_end > 0 check is an indexer-backed finality assertion, not independent Merkle-proof verification.

### 2.3 Payment boundary and parallel work

The current payment work is a separate Stars domain: PaymentIntent, PaymentTransaction and append-only PaymentEvent records, with XTR amount/payer/payload checks and delivery gating on confirmed payment. The active Stars test-bot and PostgreSQL safety-test work is tracked in PRs [#170](https://github.com/AzizIo/Vstore/pull/170) and [#171](https://github.com/AzizIo/Vstore/pull/171), under Issue #152. Do not duplicate, refactor or move that work as part of escrow.

Telegram's digital-goods documentation says covered sales inside Telegram must use Stars and does not permit cryptocurrency as a substitute. Whether Vstore's exact peer-to-peer resale of an already-existing TON NFT is covered remains the unresolved question in Issue #155. Consequently, **no TON deposit CTA, public checkout or escrow claim may be added to the Mini App** on the basis of this PoC.

### 2.4 Stale design document

docs/PAYMENTS_ESCROW_DESIGN.md and ADR-0001 contain useful earlier threat analysis, but some baseline/status passages predate the Stage B order lifecycle. This document is the current escrow-specific proposal; it does not silently amend or accept ADR-0001.

## 3. Custody and trust model

| Actor | Authority | Explicitly cannot do |
|---|---|---|
| Per-deal escrow contract | Holds the one configured NFT and exact TON principal; enforces the state machine and fixed recipient addresses | Upgrade itself, change the NFT/price/parties, withdraw to an arbitrary address, or bypass state guards |
| Seller | Transfer the configured NFT into escrow; receive the fixed payout after settlement | Withdraw the buyer's deposit, replace the NFT after lock, or change payout address |
| Buyer | Fund after NFT lock; accept, dispute, or trigger eligible timeout paths; receive a fixed-address refund | Withdraw while the NFT is still owed to the seller, change refund address, or replay an old action |
| Delivery-evidence oracle | Attest a particular TEP-62 transfer/return outcome with its evidence reference and finalized masterchain checkpoint | Change recipients/price/NFT; choose a dispute winner; withdraw funds |
| Dispute resolver | A 2-of-3 multisig may choose only the enumerated dispute outcome within the dispute state | Upgrade code, alter deal terms, redirect funds or seize either asset |
| Vstore API / UI | Display persisted deal facts and read-only chain observations; build unsigned wallet requests | Custody assets, sign transactions, decide delivery from a client callback, or override the contract |
| TON validators | Establish canonical chain state and masterchain finality | Decide commercial disputes |

**Custody controller:** the immutable on-chain contract controls the escrowed assets through its code. No Vstore operator wallet is the custodian. The resolver multisig is a constrained dispute authority, not a general owner. It must not have an upgrade or arbitrary-withdraw method.

For the PoC, the observer and resolver addresses are immutable constructor parameters. A single hot key is not acceptable for a production oracle or dispute role. The intended production shape is independent threshold-controlled signers, preferably with separate keys and operational owners for evidence and arbitration.

## 4. Deal lifecycle and timing proposal

The following values are **testnet defaults for deterministic testing only**, not a commercial SLA:

| Timer | Proposed value | Starts when | What timeout permits |
|---|---:|---|---|
| Seller NFT deposit | 30 minutes | Deal contract deployment | Expire only if a finalized chain check shows the configured NFT was not deposited |
| Buyer funding | 60 minutes | Valid NFT lock is recorded | Start the NFT-return-to-seller path; no buyer funds exist yet |
| Buyer review / pre-accept dispute | 24 hours | Buyer deposit is accepted | Buyer accepts or disputes; absent action, return NFT and refund buyer |
| NFT outbound confirmation grace | 30 minutes | Contract sends the NFT transfer | Retry only after a finalized no-delivery check; timeout alone is not proof of failure |
| Post-delivery dispute window | 48 hours | Oracle confirms the NFT reached buyer at finality | No dispute: seller payout becomes eligible; dispute: freeze settlement |
| Arbitration resolution | 7 days | Valid dispute is opened | Apply a deterministic default based on where the NFT is proven to be; never infer asset location from elapsed time alone |
| Buyer NFT return after a post-delivery dispute | 24 hours | Dispute is accepted for post-delivery review | Without a finalized return to escrow, reject the refund path and settle seller |

All deadlines are absolute Unix timestamps fixed by the contract. Calls such as timeout are permissionless keepers: they only advance the contract when the on-chain deadline and required proof/state guards pass. The observer's outage or missing indexer row must never itself trigger a refund.

## 5. Contract state machine

### 5.1 States

| State | Meaning |
|---|---|
| AWAITING_NFT | Deal deployed; seller has not yet locked the configured NFT |
| AWAITING_BUYER_FUNDS | Exact NFT ownership notification validated; waiting for buyer deposit |
| FUNDED_REVIEW | Buyer principal is locked and NFT remains in escrow; 24-hour review window is open |
| NFT_RELEASE_PENDING | Buyer accepted; contract sent the TEP-62 transfer to the buyer |
| DELIVERED_DISPUTE_WINDOW | Observer confirmed the exact NFT transfer to buyer at finality; 48-hour dispute window is open |
| DISPUTED | A valid buyer dispute is active; principal cannot be paid or refunded without the state-specific resolution rules |
| NFT_RETURN_PENDING | Contract is returning the NFT to seller or receiving it back from buyer |
| SELLER_PAYOUT_PENDING | NFT delivery and dispute conditions passed; fixed seller payout was emitted but not yet reconciled |
| BUYER_REFUND_PENDING | NFT is proven returned to seller (or remains in escrow on a buyer-win path); fixed buyer refund was emitted but not yet reconciled |
| SETTLED | Seller payment is finalized and no escrow asset remains |
| REFUNDED | Buyer refund is finalized and NFT is returned to seller |
| EXPIRED | Deal expired before any buyer funds were accepted and no NFT remains in escrow |
| MANUAL_REVIEW | Evidence conflicts or is incomplete; contract does not release either asset automatically |

MANUAL_REVIEW is deliberately a hold, not a terminal success/failure state. Recovery needs fresh finalized chain evidence or the resolver path; a database status must not override it.

### 5.2 Normal path

1. Deploy one single-deal instance with immutable seller/buyer addresses, NFT item address, principal in nanotons, unique deal salt, oracle quorum address, resolver multisig, fee policy (zero for the PoC) and deadlines.
2. Seller signs a TEP-62 transfer from their own wallet with new_owner = escrow, response_destination = seller, a fresh query_id, nonzero forward_amount, and a forward payload containing the deal hash.
3. Escrow accepts ownership_assigned only from the configured NFT item, for the expected query ID and deal hash, with prev_owner = seller. It enters AWAITING_BUYER_FUNDS.
4. Buyer sends the exact native TON principal plus the published execution reserve. The contract requires sender = snapshotted buyer, the expected state, exact principal accounting, one deposit only and sufficient execution reserve. It enters FUNDED_REVIEW.
5. Buyer inspects the on-chain item and deal facts. Buyer either disputes within 24 hours or accepts. Acceptance moves the contract to NFT_RELEASE_PENDING; escrow sends a TEP-62 transfer from itself to the snapshotted buyer.
6. The independent observer correlates the exact item-account transaction, escrow source, buyer destination, unique transfer query ID, successful compute/action phases, complete trace and finalized masterchain checkpoint. The configured oracle quorum submits the evidence reference/checkpoint; the contract moves to DELIVERED_DISPUTE_WINDOW.
7. If no dispute arrives within 48 hours, anyone may trigger seller settlement. The contract sends the principal only to the snapshotted seller address and enters SELLER_PAYOUT_PENDING.
8. The payout observer confirms the exact outgoing payment at finality. The contract moves to SETTLED. A bounce or missing finality leaves a retryable pending state; it never marks payout successful optimistically.

### 5.3 Refund and dispute paths

**Buyer does not accept within the review window:** the contract starts returning the NFT to the snapshotted seller. It refunds the buyer only after the NFT return is independently confirmed at finality. If the return message bounces or evidence is unavailable, both principal and NFT remain in a retry/manual-review state.

**Buyer disputes before accepting:** funds and NFT stay in escrow. The 2-of-3 resolver may choose:
- buyer-favouring outcome: return the NFT to seller, wait for finalized return, then refund buyer;
- seller-favouring outcome: transfer NFT to buyer, wait for finalized delivery, then pay seller.

If the resolver does not decide within seven days, the default is buyer-favouring only while the NFT is still proven to be in escrow and can be returned to seller. If the chain evidence is inconclusive, remain in MANUAL_REVIEW.

**Buyer disputes after delivery:** the dispute is accepted only during the 48-hour window. To make a refund possible, buyer must transfer the NFT back to escrow within 24 hours. The resolver then decides:
- buyer wins: contract returns NFT to seller and refunds buyer after finalized return;
- seller wins: contract re-delivers NFT to buyer (if it is in escrow) and pays seller after finalized delivery;
- no NFT return by the buyer deadline: refund is not permitted; dispute is rejected and seller settlement becomes eligible, because buyer still controls the NFT.

If the resolver does not decide within seven days after a valid post-delivery return, default to buyer refund plus NFT return to seller. No refund may be sent while the buyer still owns the NFT.

### 5.4 Timeout is not proof

A deadline only makes an action eligible. It does not prove that an asynchronous NFT transfer failed. Before retry/refund/expiry, the oracle must establish a finalized canonical state that is consistent with the intended branch: exact NFT owner, relevant transfer trace, query ID, and no contradictory in-flight or finalized transfer evidence. If the provider is unavailable, a trace is incomplete, or providers disagree, remain pending/manual review.

## 6. TON message protocol and replay resistance

### 6.1 Standard TEP-62 messages

The contract must implement only the required TEP-62 paths for the configured item:

| Message | Opcode | Use |
|---|---:|---|
| transfer | 0x5fcc3d14 | Seller → escrow, escrow → buyer/seller, or buyer → escrow return |
| ownership_assigned | 0x05138d91 | Confirm that the configured NFT item changed owner to the receiving contract |
| excesses | 0xd53276db | Correlate excess-value return where applicable; not a delivery proof |

The inbound ownership notification is accepted only from the configured NFT item contract. Verify query_id, prev_owner, expected state and deal-hash payload. A notification from any other NFT item must not be able to alter the deal state.

The seller's inbound transfer must use forward_amount > 0; TEP-62 does not emit ownership_assigned when the forward amount is zero. The PoC should use a bounded, explicit amount sufficient for the notification and execution fees.

### 6.2 Contract-specific commands

Project-specific internal commands should be versioned and have explicit TL-B layouts for:

- DEPOSIT — buyer, principal, deal nonce and operation nonce;
- ACCEPT — buyer acceptance of the locked NFT;
- OPEN_DISPUTE — buyer, dispute phase and reason hash (never a free-form trusted claim);
- CONFIRM_NFT_LOCKED / CONFIRM_NFT_DELIVERED / CONFIRM_NFT_RETURNED — oracle quorum attestation with attempt ID, transaction hash, trace hash and finalized masterchain seqno;
- RESOLVE_DISPUTE — resolver multisig and a closed enum outcome;
- TIMEOUT — permissionless, state-specific deadline advancement;
- RECONCILE_PAYOUT / RECONCILE_REFUND — finalized settlement evidence.

Exact custom opcodes and TL-B layouts belong in the reviewed contract source, not in this design-only change.

### 6.3 Replay protection

- Each deal is a separate contract instance with a random 256-bit deal salt and immutable terms.
- Every action includes the deal hash, protocol version, phase/attempt identifier and a unique uint64 query ID.
- The contract stores the active attempt/query ID and accepted evidence hash; old IDs are rejected after a phase transition.
- Every command checks authenticated sender and exact current state. A duplicated deposit cannot increase principal; a duplicated accept/dispute/resolve/settlement command is an idempotent no-op or a rejected transition.
- NFT transfer query IDs are generated once per attempt, never reused; callback sender, previous owner, destination intent and payload must match.
- The observer deduplicates by network + NFT item + transaction hash + deal/attempt ID. Tx hashes/BOCs supplied by a wallet or client remain lookup hints only.
- The resolver and oracle must sign a domain-separated payload containing contract address, network, deal hash, command, attempt ID, expiry and evidence hash. Signatures for a different deal/network/phase cannot be replayed.

## 7. Bounce, retry and settlement safety

TON messages are asynchronous. An outbound message being created by the escrow transaction does not mean the destination transaction has executed.

- All value-bearing internal messages use explicit amounts and bounce-enabled messages. Keep sufficient storage/execution reserve; do not use mode 128 to drain the contract balance.
- Do not suppress principal-transfer action failures with an ignore-errors flag. A failed send must leave the accounting state retryable.
- Parse bounced messages using the bounce marker and original operation/query ID; verify the bounce sender and current phase before changing state.
- An NFT transfer bounce moves the attempt to a retryable state. Do not refund or pay the seller from a bounce alone.
- A seller payout/refund bounce changes only that payout to PAYOUT_RETRY / REFUND_RETRY; principal remains owed to the same snapshotted recipient. A retry reuses the same settlement ID but emits a new chain transaction attempt.
- Bounce is not guaranteed in every failure mode: the sender must have enough remaining TON and the original message must be bounceable. Therefore a missing bounce is not evidence of success or failure; the observer must reconcile the exact trace and recipient state.
- Contract state must separate *_PENDING from SETTLED / REFUNDED. Only finalized payout/refund evidence can close the deal.
- If a payout transaction succeeded but its observation is delayed, never resend while the original transaction may still finalize. Retry only after an explicit finalized failure/bounce or a safe canonical reconciliation result.

## 8. Finality and evidence policy

TON transaction finality is reached when a masterchain block references the relevant shardchain state; TON documentation describes one masterchain reference as final. The observer should consume only an explicit finalized trace or independently verify the shard/masterchain proof. pending and confirmed trace states are not sufficient.

For the testnet PoC, the existing TON Center v3 adapter may be reused as a **trusted indexer input** after it is extended to cover escrow-specific transfers and callbacks. Its current positive mc_seqno_end check is useful evidence but is not a cryptographic proof. The contract's oracle key therefore remains a trust assumption.

Before production, prefer one of:
1. verify the relevant shard/masterchain Merkle proof against a trusted validator/light-client checkpoint; or
2. require a quorum of independently operated providers/oracles with evidence hashes and explicit finality, plus an independently reproducible audit trail.

The backend must persist an immutable escrow intent snapshot and observed evidence references, but no production order status should be advanced merely because the client reports a transaction hash, wallet callback or success screen.

## 9. Threat model

| ID | Threat / failure | Impact | Required mitigation |
|---|---|---|---|
| E1 | Fake ownership_assigned from an arbitrary contract | False NFT lock; buyer deposits against no asset | Accept only from configured NFT item; verify query ID, previous owner, deal hash and state |
| E2 | Wrong NFT, seller or buyer address | Asset substitution or loss | Immutable per-deal addresses; exact normalized address checks in contract and observer |
| E3 | NFT item changes ownership but callback is bounced/lost | Contract owns NFT but state remains stale; asset appears stuck | Nonzero forward amount; observer reconciliation of finalized item state; safe recovery path |
| E4 | Buyer deposits before NFT is locked | Buyer funds without collateral | Contract rejects deposit unless state is AWAITING_BUYER_FUNDS; sender and amount are fixed |
| E5 | Underpayment, overpayment or wrong sender | Insufficient principal or ambiguous accounting | Exact principal accounting, explicit execution reserve, excess handling to fixed sender only |
| E6 | Duplicate/replayed deposit, accept, dispute or oracle attestation | Double accounting or duplicate transfer/payout | Deal nonce, per-phase query IDs, one-way state machine, evidence-hash/idempotency checks |
| E7 | NFT transfer bounce, partial execution or provider lag | Premature refund/payout or stuck assets | Pending states, bounce parser, lease/retry observer, finalized reconciliation; timeout is not proof |
| E8 | Seller or buyer changes wallet/network after intent creation | Funds/NFT sent to an unintended address | Immutable normalized address/network snapshots; fresh TON Proof before intent; no client override |
| E9 | Oracle compromise or false finality attestation | Release or refund on a false chain claim | Testnet-only single-oracle assumption documented; production quorum or light-client proof; oracle cannot redirect assets |
| E10 | Resolver compromise/collusion | Wrong dispute outcome | 2-of-3 independent multisig; limited enum-only authority; append-only decision record; no arbitrary transfer/upgrade |
| E11 | Contract upgrade/admin key compromise | Arbitrary custody theft | Non-upgradeable per-deal code; no admin withdraw; audited reproducible code hash |
| E12 | Transaction finality/indexer reorg or inconsistent providers | Irreversible payout on non-final evidence | Require masterchain-finalized trace/proof; do not rely on client hash or confirmed-only event |
| E13 | Payout/refund bounce or ambiguous delivery | Double payout or stranded principal | Explicit settlement IDs, pending state, bounce correlation and finality observer before terminal state |
| E14 | Timeout race with an in-flight TEP-62 transfer | NFT returned/refunded while a delivery later completes | Timeout only enables reconciliation; require finalized canonical evidence and owner/state checks |
| E15 | Malicious/non-standard NFT item or unsupported collection | Unexpected behavior / locked NFT | Test only known TEP-62 item contracts; production collection/item allowlist and code/behavior validation |
| E16 | Gas griefing or storage depletion | State transitions become unexecutable | Bounded message/trace parsing, minimum reserve, explicit gas budget, no unbounded loops, adversarial gas tests |
| E17 | Accidental mainnet deployment | Real assets could be locked | Build/deploy guard asserts testnet chain ID and testnet endpoint; no mainnet endpoint/key in PoC CI; independent release approval |
| E18 | Telegram policy/payment misclassification | Platform enforcement or non-compliant checkout | Keep contract out of Mini App purchase flow until Issue #155 has written ruling and ADR-0001 is accepted |

## 10. Test scenarios

### Contract unit / sandbox suite

1. Correct seller NFT deposit: exact item, previous owner, query ID, deal hash and notification amount.
2. Wrong item, wrong previous owner, wrong query ID, wrong payload and duplicate ownership notification.
3. Zero forward amount (no notification) and a notification callback that bounces.
4. Buyer deposit before NFT lock; wrong buyer; underpayment; overpayment/excess; duplicate deposit.
5. Accept before funding, accept after deadline, duplicate accept and concurrent accept/dispute.
6. Correct outbound TEP-62 transfer to buyer and to seller on refund; wrong destination and reused query ID.
7. NFT outbound bounce, delayed notification, missing indexer event and finalized success after an initial timeout.
8. Review timeout with NFT still escrowed; buyer refund only after finalized NFT return to seller.
9. Dispute before acceptance, dispute after delivery, dispute outside window, buyer NFT return before/after its deadline.
10. Resolver approval/rejection, 2-of-3 threshold failure, stale decision, replayed decision and arbitration timeout defaults.
11. Seller payout success, refund success, bounce of each, duplicate payout/refund command and ambiguous payout finality.
12. Conflicting oracle evidence, missing masterchain seqno, incomplete trace, confirmed-but-not-finalized trace and provider outage.
13. Storage/gas boundary tests; malicious large payloads; unknown opcodes; non-bounceable inputs; unexpected NFT item.
14. Assert invariant: never both SETTLED and REFUNDED; never release TON while the NFT is in an escrow-owned state; never refund while buyer owns the NFT; never mark settlement complete before finality.

### Backend / observer integration suite

- Persisted immutable escrow intent and deal/attempt identifiers survive worker restart.
- Duplicate events and repeated observer passes do not duplicate contract messages or terminal state.
- Wrong network, item, source, destination or query ID fails closed.
- Delayed indexing/provider outage keeps the state pending/manual review.
- A stale worker lease cannot apply evidence after a newer worker claims the attempt.
- Observer cannot construct or sign a privileged message with a server-held key.
- API/UI callbacks and submitted tx hashes cannot make an escrow state terminal.
- No production Order, listing, migration or Stars payment row is read or written by the PoC harness.

### Testnet manual acceptance (only after all gates)

- Deploy a fresh single-deal instance using testnet-only endpoints and test wallets.
- Verify contract code hash and immutable constructor snapshot.
- Seller sends a known test NFT to escrow from Tonkeeper; confirm exact notification and ownership.
- Buyer funds with test TON; verify contract balance and exact principal accounting.
- Execute accept → NFT transfer to buyer → finalized observer confirmation → dispute window → seller test payout.
- Execute timeout/refund branch, NFT return to seller, and buyer test refund.
- Repeat with a bounce, delayed provider indexing, duplicate/replayed messages and a test-only resolver decision.
- Record testnet addresses, transactions, masterchain seqnos, code hash and reproducible logs. Do not use seed phrases or production wallet credentials.

## 11. Implementation boundaries

When approved, isolate the PoC under a new top-level contract workspace (for example contracts/ton-escrow-poc/) with its own lockfile, Blueprint/Tolk or FunC compiler setup, Sandbox tests and testnet-only scripts. Do not alter:

- backend/app/db/models.py, migrations or any production DB;
- backend/app/orders/payment_service.py, Stars adapters, bot dispatchers or payment tables;
- backend/app/orders/service.py or the existing order lifecycle;
- the existing production delivery observer or production configuration;
- Mini App checkout, CTA, listing price or buyer-facing guarantee wording.

A future read-only testnet observer may live beside the PoC and read contract state/events, but it must be feature-isolated and have no production order-flow side effect. Any integration with Order later requires a new reviewed design, separate feature flag, explicit payment/policy approval and independent schema/API review.

A testnet-only deploy script must assert the expected TON testnet network ID (not merely infer it from a URL), refuse mainnet URLs/configuration, and require explicit confirmation of the target address and code hash. The contract source must not contain a generic upgrade or owner-withdraw operation.

## 12. Gates before a runnable PoC or production consideration

The current architecture does **not** yet permit a responsible testnet deployment from this task:

1. **ADR-0001 is still Proposed / awaiting maintainer acceptance.** Issue #153 explicitly lists acceptance as a dependency.
2. **Issue #155 is open.** Telegram's written classification and permitted UX/payment route for the exact NFT resale flow are unresolved. No purchase UI or public payment promise may be attached to this PoC.
3. **Issue #152 and its Stars test harness are still in progress** (including PRs #170 and #171). Escrow work must not duplicate or change that payment agent's scope.
4. **Issue #46 remains open for live TON testnet/Tonkeeper acceptance.** Automated fixture results do not prove live wallet signing, indexer finality or bounce/recovery behavior.
5. **No independent oracle or resolver operators/testnet signer setup has been approved.** No server-side private key, seed phrase or production signing service will be introduced to make the PoC appear end-to-end.

Accordingly, this change is architecture documentation only. It creates no contract source, testnet address, backend watcher, signing key, DB migration, API endpoint, frontend payment flow or production behavior. Once the gates are accepted, the next isolated deliverable can be a **local Sandbox contract test suite first**, followed by a manually approved TON testnet deployment using external test wallets (never by collecting seed phrases).

### Production blockers beyond the initial PoC

- Telegram's written answer and separate Apple/Google review; qualified legal/compliance review of custody, money transmission, disputes, consumer protection, sanctions/KYC, tax and seller settlement.
- Independent smart-contract audit, formal state/invariant analysis, adversarial asynchronous-message testing and reproducible build/code-hash verification.
- A robust oracle model (preferably light-client proof verification or independent quorum) and independent 2-of-3 dispute resolution operations, including signer recovery and key rotation policy.
- Audited NFT allowlist/TEP-62 compatibility and a recovery process for unexpected or non-standard NFT items.
- Explicit gas/reserve policy, storage economics, monitoring, incident response and a non-custodial exit/refund procedure.
- A new approved product decision for how Stars (if required) and on-chain TON custody coexist. They are not atomically interchangeable.
- No mainnet custody, public escrow promise, automatic seller payout or production integration until all gates are cleared.

## 13. Primary technical references

- [TON TEP-62 NFT standard](https://github.com/ton-blockchain/TEPs/blob/master/text/0062-nft-standard.md) — transfer, ownership_assigned and excesses message layouts; forward amount and callback behavior.
- [TON internal messages and bounces](https://docs.ton.org/foundations/messages/internal) — bounce conditions and internal message behavior.
- [TON transaction/message overview](https://docs.ton.org/foundations/messages/overview) — transaction finality via masterchain inclusion.
- [TON Streaming API finality model](https://docs.ton.org/api/streaming/overview) — pending, confirmed and finalized trace lifecycle.
- [TON payment processing overview](https://docs.ton.org/applications/payments/overview) — practical finality guidance.
- [TON FunC send modes](https://docs.ton.org/languages/func/stdlib) — send modes and error/bounce flags.
- [Telegram Stars Payments API](https://core.telegram.org/bots/payments-stars) — Stars-only rule for covered digital goods/services and dispute/refund responsibilities.
