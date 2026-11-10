> **Historical review note (2026-11-10):** This audit evaluated `main` at `8ab3501`, before PR #34's fresh ownership re-check and the later catalog/listing changes #50, #52 and #53. Its code observations are historical and are not a current-main audit. Re-run the implementation checks before using this report as a release assessment.

# Independent review: ADR-0002 safe-deal architecture

- **Reviewer:** GPT-6 (independent technical/architecture audit)
- **Date:** 2026-11-10
- **Repository:** `AzizIo/Vstore`
- **Reviewed baseline:** `main` at `8ab35010de99b74812aa9426ebfbef57d9caa60b`
- **Inputs:** PR #35, PR #36, PR #37 (unmerged proposals / candidate ADR), ADR-0001, `docs/discussions/0001-safe-deal-payment-and-escrow.md`, `docs/PAYMENTS_ESCROW_DESIGN.md`, current backend order/payment/wallet/NFT-verification code
- **Status:** independent review for discussion; not an approved architecture or legal opinion
- **Code changes:** none. No payment, escrow, wallet-custody, refund, payout or frontend implementation was added.

> **Verdict: NO-GO for real-money sales.** ADR-0002 is a useful consolidation, but it is not yet an implementation-ready payment specification. Resolve the critical findings in §3 and obtain platform/provider/legal confirmation before implementation. PR #36 is the better production research direction; PR #35's Stars-deposit/remedy model should not be used as a launch mechanism.

## 1. Executive assessment

**Readiness score: 6/10 as an architecture discussion; 3/10 as an implementation specification; 0/10 for production payment launch today.** These are reviewer judgments, not measured test results.

The core difficulty is that the marketplace coordinates at least three independently failing systems: Telegram payments, the TON blockchain, and an operator/PSP settlement rail. PostgreSQL can serialize local state transitions, but it cannot make an external refund, a TON transfer and a PSP payout atomic. The design must therefore be an explicit, recoverable saga with durable commands, unknown outcomes and reconciliation—not a promise of atomic exchange.

The key release blockers are:

1. **No demonstrated seller-settlement rail for Telegram Stars.** A database ledger is an obligation record, not money or escrow.
2. **MVP listing reservation does not lock an NFT.** The seller can transfer it after an ownership observation.
3. **Stars refund and operator-funded fiat compensation are different instruments.**
4. **Refund/delivery/payout races cannot be resolved by a database row lock alone.**
5. **Idempotent webhook ingestion does not by itself prevent distinct duplicate charges or duplicate external payouts.**
6. **A TON contract cannot synchronously call another contract's off-chain `get` method.** Collection validation needs a concrete allowlist, proof or oracle model.
7. **TON Center API v3 is indexed data, not automatically a cryptographic proof of chain state.**
8. **The state machine does not consistently separate delivery confirmation, dispute eligibility and payout eligibility.**

No payments were implemented as part of this review. The findings below are designed to be actionable before implementation begins.

## 2. Scope and current-state observations

### 2.1 Proposals

| Input | Main idea | Assessment |
|---|---|---|
| [PR #35 — Claude proposal](https://github.com/AzizIo/Vstore/pull/35) | Stars payments, operator remedy reserve, seller deposit, direct seller-to-buyer NFT transfer; escrow deferred | Identifies buyer-protection risk, but its Stars collateral/settlement assumptions are not demonstrated, and its TEP-62 transfer direction is incorrect in one key passage. |
| [PR #36 — independent TON/PSP proposal](https://github.com/AzizIo/Vstore/pull/36) | External PSP candidate, NFT deposited to TON escrow before capture, explicit NO-GO until validated | Stronger production research direction because it separates money and asset rails and does not claim atomicity. Still lacks implementable contract verification/oracle and complete failure/recovery specification. |
| [PR #37 — candidate ADR-0002](https://github.com/AzizIo/Vstore/pull/37) | Consolidated architecture, options and owner decision points | Best starting point for further discussion, but several statements are contradictory or insufficiently specified. This report does not approve it. |

PRs were inspected as proposals, not treated as merged code. The main baseline and open PR contents can change; re-check before implementation.

### 2.2 Existing implementation inspected

| File / area | Observed baseline | Consequence |
|---|---|---|
| `backend/app/orders/service.py` (create order and transitions) | Creates a DB reservation and pending-payment order from persisted listing/asset state | A DB reservation is not an on-chain lock. The current path must not be described as a fresh, cryptographically verified ownership guarantee. |
| `backend/app/api/orders.py` | Order creation, read/list and buyer cancellation paths | No implemented payment webhook, refund, dispute or payout workflow was found in this baseline. |
| `backend/app/orders/payment.py` | `PaymentAdapter` protocol has intent creation and notification verification abstractions | No concrete provider integration, durable event inbox, refund contract, payout adapter or reconciliation path is supplied by the protocol itself. |
| `backend/app/db/models.py`, `backend/migrations/versions/0003_orders.py` | Order status constraint is limited to early states such as pending payment/cancelled/expired | A production lifecycle requires a reviewed migration and explicit transition matrix, not just enum additions. |
| `backend/app/bot.py` | aiogram starts with `start_polling` | Telegram Bot API webhook and `getUpdates` long polling cannot be used simultaneously for the same bot token. Ingress must be selected. |
| `backend/app/wallets/proof.py` | Validates TON Connect proof data, domain, timestamp, wallet state-init/signature | Proves control of a wallet for the proof flow; does not prove NFT delivery, future ownership or that a seller will send to that address. |
| `backend/app/assets/ton_nft/verifier.py` | Reads NFT/item/collection-owner data through configured provider | An indexed provider response is an observation, not automatically a cryptographic lite-server proof. |
| `backend/app/listings/service.py` | External ownership check followed by DB locking and revalidation of listing/wallet/asset | Useful local race-control pattern, but it cannot make a TON transaction atomic with a database commit or PSP operation. |

**Dependency caveat:** PR #34 was open at the reviewed baseline and was referenced by the candidate ADR. Do not assume its fresh ownership re-check exists in `main` until it is merged and tested or equivalent code is independently verified.

## 3. Findings requiring resolution before ADR-0002 approval

Severity:
- **Critical:** a plausible path to financial loss, invalid settlement assumptions, or incorrect state transitions.
- **High:** likely to cause unresolved funds, unfair disputes, duplicate side effects or a systemic security gap.
- **Medium:** legal/product ambiguity requiring a decision before the affected launch phase.

### F-01 — The MVP does not lock the NFT; “asset lock” is misleading
**Severity: Critical**  
**ADR-0002:** `docs/adr/0002-safe-deal-architecture.md`, especially lines 193–206, 214, 292.

The architecture describes asset movement to a locked position before capture, but the MVP description says the “lock” is only a DB reservation and the NFT stays in the seller's wallet. These are materially different.

A listing reservation only prevents another VILTARA order from reserving the same database listing. It cannot stop the seller from transferring the NFT to another wallet or marketplace. A just-in-time owner read is still only a point-in-time observation.

**Failure scenario:** ownership check says seller owns the NFT; buyer pays Stars; seller transfers NFT to a third party immediately afterwards; payment notification marks the order paid; delivery never occurs. No on-chain asset lock or defined funded compensation mechanism exists.

**Required change:** reserve “asset locked” for an NFT actually deposited into an escrow contract and confirmed on-chain. Call the MVP mechanism a *database listing reservation plus ownership observation*. Either accept the residual risk with an independently funded, legally approved remedy and strict value caps, remain a no-money workflow, or defer sales until a real custody path exists.

### F-02 — Stars do not provide per-seller settlement or operator-owned collateral
**Severity: Critical**  
**PR #35:** `docs/discussions/proposals/claude-fable-viltara-safe-deal.md`, especially lines 77–125, 318–344.  
**ADR-0002:** lines 84, 88–94, 224–245, 424–426.

Telegram's terms say Stars in a TPA balance are not the developer's property; Telegram owns them. Telegram rewards/Fragment is not a per-seller marketplace settlement API. A `seller_ledger` row represents a recorded obligation, not segregated money, a bank balance or legal escrow.

**Failure scenario:** VILTARA accepts Stars and marks the sale complete. It records seller proceeds but has no permitted/documented way to transfer those Stars to the seller. If the operator pays sellers from personal fiat or crypto, that is a separate operator-funded payout obligation—not a transfer of the buyer's Stars.

**Required change:** select and document one of these paths before accepting paid orders:
1. No seller payout in the Stars MVP; do not enable sales until a lawful settlement mechanism exists.
2. Operator-funded fiat settlement through a named legal entity and bank account, with seller terms, funding source, KYC/tax/sanctions handling, FX, payout timing and insolvency exposure.
3. A PSP structure with written approval for the product, seller onboarding, balances and payouts.

Do not imply Telegram/Fragment offers seller sub-accounts or that a database sub-ledger is collateral.

### F-03 — Telegram Stars refunds and fiat compensation are separate flows
**Severity: Critical**  
**ADR-0002:** lines 84, 88, 214, 237–245, 299, 340.

Bot API `refundStarPayment` refunds the original Stars payer using Telegram user ID and the original Telegram payment charge ID. It is not an arbitrary transfer to a seller or buyer, and it does not express a general partial-refund amount. A separately held fiat remedy reserve does not replenish the TPA Stars balance or make the Telegram refund API succeed.

**Failure scenario:** Telegram has withheld/debited Stars, the TPA balance is insufficient or the account is restricted, and the refund call fails or times out. A bank reserve does not make the Stars refund succeed.

**Required change:** keep separate state and accounting for `stars_refund_pending / stars_refunded / stars_refund_unknown` and `operator_compensation_due / paid`. Do not mark a refund complete until the relevant rail confirms it. Define insufficient-balance, account-restriction, duplicate-request and timeout recovery. Do not promise partial Stars refunds without a supported API.

### F-04 — Delivery, dispute window and payout eligibility are conflated
**Severity: Critical**  
**ADR-0002:** lines 277–283, 286, 299–300, 326.

The transition table lets an owner check move delivery to completed, while payout is allowed only after a dispute window. But the dispute transitions do not clearly allow a dispute after the order has already become completed, despite a stated post-delivery window.

**Failure scenario:** the indexer sees the NFT in the buyer wallet and the order becomes completed. The buyer discovers a wrong collection 20 minutes later, within the stated dispute window, but the state machine only allows disputes from earlier states. A valid claim is rejected or implemented as an ad hoc exception.

**Required change:** separate at minimum:
- `delivery_confirmed_unsettled` — chain evidence indicates delivery;
- `disputed` — settlement/payout held;
- `settlement_eligible` — review window elapsed and no active hold;
- `payout_pending / payout_unknown / payout_paid`.

Define buyer acceptance, timeout auto-acceptance, disappearance, and statutory consumer remedies. “Completed” must not ambiguously mean both “asset seen in wallet” and “seller has been paid”.

### F-05 — A PostgreSQL lock cannot serialize an external refund against a TON transfer
**Severity: Critical**  
**ADR-0002:** lines 299, 336.

A row lock serializes DB writers only. It cannot undo a Telegram refund already accepted, a PSP payout already accepted, or a TON transfer already broadcast/included.

**Failure scenario A:** a refund API accepts the request but the response times out before the DB commits. The worker retries after the lock is gone and cannot know from the DB alone whether the first refund happened.  
**Failure scenario B:** the DB selects the refund path while a seller's NFT transfer is already in flight. The DB lock cannot prevent the chain transfer from landing after the refund.

**Required change:** persist a durable command/outbox row in the same DB transaction as the intent. Track `refund_requested / refund_unknown / refund_confirmed`, `delivery_submitted / delivery_unknown` and manual reconciliation. On timeout, query provider/chain state before retrying. Do not relist or declare success on an unknown outcome. Specify the compensation policy if both external effects eventually occur.

### F-06 — Unique charge IDs do not prevent two distinct successful charges or late payments
**Severity: High**  
**ADR-0002:** lines 310–312. Current order TTL is configured in `backend/app/core/config.py`; order creation/transitions are in `backend/app/orders/service.py`.

A unique Telegram charge ID prevents processing the *same* charge twice. It does not guarantee there cannot be two successful charges with different IDs against a reusable invoice, or a success notification arriving after order expiry and listing release.

**Failure scenario:** an invoice is reused or paid twice; each charge ID is unique. Alternatively, order A expires and listing is reserved by buyer B, then a late payment update for A arrives. Blindly marking A paid may leave two buyers believing they own the same item.

**Required change:** bind invoice payload to a stored intent and expected Telegram payer ID; validate payer, payload, currency XTR, exact total, order and reservation state. Enforce one accepted successful payment per order at the DB level. Treat any excess/late charge as a separate refund/manual-review case for the original payer; never resurrect an expired order or take a listing from another buyer. Pre-checkout must re-read/lock the order and respond within Telegram's 10-second deadline. A successful pre-checkout answer is not proof of payment.

### F-07 — Unique local payout rows do not guarantee one external payout
**Severity: High**  
**ADR-0002:** line 326.

A unique `seller_payouts.order_id` prevents duplicate rows, not duplicate transfers. If the PSP accepts a payout and the HTTP response is lost, a worker may submit a second transfer.

**Required change:** persist a stable provider idempotency/reference key before submission; model `created → submitted → unknown → booked → returned/failed/reconciled`; query provider state and reconcile webhooks/statements before retrying. Define returned payout and negative seller balance handling. “Booked” must not automatically mean the seller's bank has finally received funds. Maker-checker controls do not replace idempotency.

### F-08 — Telegram update ingress conflicts with the existing long-polling bot
**Severity: High**  
**ADR-0002:** line 330; current implementation `backend/app/bot.py` lines 41–48.

The bot currently uses aiogram `start_polling`. Telegram Bot API does not allow `getUpdates` long polling while a webhook is set for the same bot token.

**Failure scenario:** implementation configures a payment webhook while the bot container continues polling. One ingress mode fails or deployments oscillate between modes, losing reliable payment-update handling.

**Required change:** choose webhook for all bot updates or keep polling and route payment handling through that dispatcher. Document rollout/recovery and secret rotation. For webhooks, validate Telegram's configured `secret_token` header; it is not a generic body HMAC. Deduplicate by `update_id` and payment charge ID. Keep webhook acknowledgement fast and separate from slow reconciliation.

### F-09 — PR #35 describes the TEP-62 transfer direction incorrectly
**Severity: Critical for PR #35**  
**PR #35:** `docs/discussions/proposals/claude-fable-viltara-safe-deal.md`, lines 139–159.

The text says a seller-to-buyer transfer but describes the buyer as sending the TEP-62 transfer. In a normal direct transfer, the current NFT owner (seller) signs/sends the transfer message and sets the new owner. VILTARA cannot force the seller's wallet to use the buyer's address just because the buyer proved control of that wallet.

**Failure scenario:** seller transfers to another address. The buyer's TON Connect proof does not force the seller to select the proven address, and a notification addressed to the buyer wallet is not automatically a backend webhook.

**Required change:** say the seller wallet initiates the transfer; snapshot the expected destination address; monitor chain traces/indexer and verify the canonical NFT item owner after inclusion. Treat a different recipient as “delivery not confirmed” pending evidence, not automatic proof of fraud.

### F-10 — Current owner does not prove historical delivery or seller fraud
**Severity: High**  
**PR #35:** proposal lines 239–245.

Current ownership is a point-in-time fact. It does not reveal whether the buyer received the NFT and later transferred it, returned it to the seller, or moved it to another wallet.

**Failure scenario:** seller delivers to the snapshotted buyer wallet. Buyer moves the NFT to a second wallet and opens a dispute. A rule “third-party owner means seller fraud” punishes the seller despite delivery.

**Required change:** examine transaction/trace history: item contract, sender, recipient, transaction hash, inclusion/finality and timestamps. Bind the observed transfer to the order. Distinguish current owner from delivery transaction and wallet control. Oracle outage/NOT_FOUND must trigger evidence-pending/manual review, not automatically decide a dispute.

### F-11 — A TON escrow contract cannot call arbitrary NFT/collection get-methods
**Severity: Critical for production**  
**PR #36:** `docs/discussions/proposals/gpt6-safe-deal-architecture.md`, lines 180–186; ADR-0002 lines 192–206, 277, 292, 367.

TON `get` methods are executed off-chain by a node/RPC client. A contract cannot synchronously call another contract's `get_nft_data()` or a collection's `get_nft_address_by_index()` during its own transaction. Inter-contract calls are asynchronous messages.

**Failure scenario:** seller deposits a counterfeit NFT item contract and claims it belongs to an approved collection. The escrow contract cannot dynamically invoke the collection getter as described. If it trusts a user-supplied collection address or generic TEP-62 notification, the counterfeit may be accepted.

**Required change:** specify a concrete validation design:
- immutable allowlist of approved item/collection contracts or deterministic item-address derivation where valid; or
- signed off-chain attestation/oracle binding item, collection, network, order nonce, seller and deposit transaction; or
- a specifically described, feasible and audited proof-verification scheme.

For oracle/attestation, define trusted signers/quorum, key rotation, replay protection, expiry, evidence persistence and outage/conflict policy. “The contract validates the collection” is not implementable until this boundary is explicit.

### F-12 — TON Center v3 data is not a cryptographic chain proof
**Severity: High**  
**ADR-0002:** lines 206, 214, 292, 321, 330; code `backend/app/assets/ton_nft/verifier.py` lines 40–108.

TON Center API v3 is an indexed data layer. A successful API response is useful evidence but is not equivalent to cryptographically verifying a lite-server proof.

**Failure scenario:** an indexer is delayed and reports stale ownership; the service marks the order eligible for settlement although the NFT has moved.

**Required change:** call current API v3 output a “provider-reported ownership observation”, not a cryptographic proof. For production/high-value sales, specify lite-server proof verification or an independent-source quorum with source independence, finality, disagreement and lag handling. Persist transaction identifiers/proof metadata and observation time, not only response JSON.

### F-13 — The external-checkout rule is over-categorical in one place and unresolved in another
**Severity: High**  
**ADR-0002:** lines 155, 170–173.

Telegram's terms require Stars for digital-goods transactions pertaining to a TPA and prohibit using other payment providers for those in-TPA transactions, with classification tied to Apple's/Google's definitions. The text reviewed does not establish that every link to a separate website is itself categorically prohibited. However, deep-linking from a TPA to an external checkout as a workaround for the Stars rule is high risk and must not be assumed permissible.

**Required change:** keep as OPEN whether this particular P2P resale product and any external sales/deep-link flow are allowed; obtain written platform/store guidance. Preserve the hard rule: do not route a transaction that is part of the TPA's digital-goods purchase through a third-party PSP as a Stars workaround.

### F-14 — “Purveyor” does not automatically settle legal merchant-of-record status
**Severity: Medium**  
**ADR-0002:** lines 84, 163, 424.

Telegram Terms impose platform-level delivery/dispute duties on the TPA developer/purveyor. That does not by itself determine merchant-of-record/seller-of-record status under every jurisdiction's tax, consumer, acquiring or financial-services rules.

**Required change:** state that Telegram contractual duties apply, while legal MoR/seller-of-record classification remains a jurisdiction- and contract-specific question for counsel and the provider. Do not equate the two without legal advice.

### F-15 — PSP “booked” payout may later be returned
**Severity: High for production**  
**PR #36:** proposal lines 84–102, 140–153, 178; ADR-0002 lines 283, 326.

Adyen's documentation distinguishes transfer status from final receipt; transfers may fail or be returned, and negative balances/chargebacks may create platform liability depending on the contract and setup.

**Failure scenario:** VILTARA marks the seller paid after a “booked” event. The receiving bank returns the transfer, leaving the seller unpaid while the order ledger says settled.

**Required change:** define provider-specific payout terminal states and returned-transfer handling; reserve for negative balance/chargeback exposure. Do not assume Adyen supports this NFT marketplace until written underwriting approval and account configuration are confirmed.

### F-16 — A 72-hour chain observation is not a complete consumer dispute policy
**Severity: High**  
**PR #35:** lines 235–249; ADR-0002 lines 277–300, 340, 440.

Ownership data does not prove the NFT was accurately described, belonged to the promised collection, had the promised metadata/rights, or met mandatory consumer-law requirements. A contractual review window cannot waive statutory remedies.

**Required change:** separate non-delivery, wrong contract/collection, misdescription/authenticity/rights, chargeback and statutory consumer claims. Define legal policy with counsel. Chain evidence is one input to adjudication, not the whole decision.

### F-17 — Deposit-first escrow is promising but needs a complete asynchronous failure model
**Severity: High for production**  
**PR #36:** lines 128–186, 218–236, 277–284; ADR-0002 lines 193–206, 292, 367–379.

Deposit-first reduces seller non-delivery risk because the seller cannot be paid while retaining the NFT. It does not make PSP and TON operations atomic.

The spec must handle: deposit succeeds but watcher misses it; duplicate/late deposit notification; counterfeit/unapproved NFT; release message bounces; release succeeds but watcher is down; PSP refund succeeds but NFT return fails; escrow return succeeds but PSP refund is unknown; buyer never responds; admin pauses/loses keys while assets are held.

**Required change:** specify the escrow state machine, bounce/retry/recovery behaviour, orphan-deposit path, timeout rules, pause/upgrade/rescue authority, evidence and outbox/inbox reconciliation. Every external effect needs a true “unknown” state. Mainnet deployment requires independent contract audit.

### F-18 — The idempotency plan must cover commands and reconciliation, not just event ingestion
**Severity: High**  
**ADR-0002:** lines 310–330.

An event inbox and unique event IDs are necessary but not sufficient. External systems do not join the PostgreSQL transaction.

**Required change:** include unique Telegram `update_id`, unique charge ID, unique accepted payment per order, excess/late-payment policy, durable refund command, TON transaction/query correlation, stable PSP payout idempotency key, outbox worker leases/retries/dead-letter/manual resolution, and append-only accounting journal with compensating entries. Reconcile provider statements and chain state periodically.

## 4. Comparison: what to retain from each proposal

### PR #35
**Retain:** recognition of buyer-remedy risk; capped/disclosed protection; snapshotting the buyer wallet; preference for chain history over unsupported testimony; dual-control dispute decisions.

**Do not retain as a launch mechanism:** seller Stars deposit; “Stars remedy fund” as operator-controlled collateral; assumption that Stars provide per-seller payout; buyer-initiated seller-to-buyer TEP-62 transfer; adjudication based only on current owner; automatic seller guilt when an oracle is unavailable.

### PR #36
**Retain as a production research direction:** separation of payment/asset/settlement trust boundaries; deposit-before-capture; explicit NO-GO; independent provider underwriting; watcher/webhook/reconciliation; testnet-first and external audit.

**Resolve before implementation:** contract-side NFT/collection validation; watcher/oracle trust model; bounce/replay/orphan-deposit recovery; exact PSP capture/delay capabilities; card chargeback after the NFT has left escrow; return/refund race handling; payout and negative-balance liability.

## 5. Failure matrix the implementation spec must cover

| Event | Safe expected behaviour | Unsafe behaviour to prohibit |
|---|---|---|
| Seller moves NFT after MVP owner check | Treat delivery as unguaranteed; no false “asset locked” claim; apply only an explicitly funded remedy or do not sell | Treat DB reservation as custody |
| Duplicate Telegram update | Inbox deduplicates; no second ledger entry or delivery command | Repeat side effect |
| Two distinct successful charges | One accepted; extra charge becomes refund/manual case | Assume unique charge IDs guarantee one payment per order |
| Payment arrives after order expiry | Do not resurrect order or displace another buyer; refund/reconcile original payer | Mark expired order paid blindly |
| Event arrives before local intent commit | Persist unmatched event and reconcile after commit | Drop event or create an order from webhook payload |
| Polling and webhook both configured | Deployment rejects/confirms one ingress mode | Run both and assume updates arrive on both |
| Telegram balance restricted/insufficient | Refund remains pending/unknown; separate approved compensation if available | Mark refunded because a DB entry exists |
| Refund API times out | Mark unknown; query/reconcile before retry | Blind retry or mark refunded prematurely |
| Indexer unavailable/stale | Evidence pending; no automatic seller guilt or payout | Treat timeout/NOT_FOUND as proof |
| Buyer moves NFT after receiving it | Review exact delivery transaction and history | Decide solely from current owner |
| Wrong NFT/collection | Verify item/collection identity and claim type | Treat buyer ownership as proof of correct delivery |
| PSP capture accepted but response lost | Reconcile intent/provider state before another capture | Submit another capture blindly |
| Payout accepted but response lost | Query using stable provider reference before retry | Issue a second bank transfer |
| PSP payout later returned | Reopen payout reconciliation and keep payable unresolved | Treat “booked” as irreversible final receipt |
| Refund races with TON release | Durable saga state, hold settlement, reconcile both rails | Assume a DB lock reverses external effects |
| Escrow deposit succeeds but watcher misses event | Scan chain and idempotently correlate by order/item | Expire order and strand NFT |
| Release message bounces | Track trace/bounce and recover explicitly | Assume ownership reverted automatically |
| Dispute after delivery observation | Permit dispute while settlement remains held | Make completed state block a valid claim |

## 6. Security audit gates before launch

### Telegram/payment ingress
- Confirm Telegram's classification of this NFT resale product under Apple's/Google's digital-goods rules.
- Select one ingress mode; validate webhook secret token over TLS and rate-limit.
- Bind invoice to persisted intent and expected payer; verify payer, payload, XTR, exact amount, order state and charge reference.
- Handle 10-second pre-checkout deadline, duplicate updates, late/excess charges, expired invoice, forged requests and worker restarts.
- Test refund timeout, insufficient Stars balance, account restriction and support/dispute handling.

### Funds, ledger and payouts
- Independent review of a double-entry immutable journal: provider balances, seller payable, fees, taxes, FX, refunds, chargebacks, reserves, payout returns and compensating entries.
- Daily reconciliation against provider statements and bank records, with out-of-balance alerts.
- Identify actual source of seller payouts and compensation; define legal entity, account, funding, KYC, sanctions, tax and insolvency exposure.
- Maker-checker controls, stable payout idempotency key, returned payout handling, admin audit trail and PII/financial-log redaction.
- Incident playbooks for Telegram/Fragment restrictions, PSP termination, bank freeze and operator insolvency.

### TON escrow and watcher
- Independent contract audit for TEP-62 parsing, sender/current-owner validation, item/collection registry, order nonce, network, replay, bounce, gas and forwarding amounts.
- Invariants: one deposit per order/item; one release or return; no release before valid payment evidence; no payout before required post-release evidence.
- Multisig/threshold governance, pause and recovery policy, upgrade timelock, key rotation and emergency rescue.
- Fake-NFT and unsupported-collection tests; testnet, reproducible build, trace replay, fuzz/property testing and external audit.
- Watcher validates exact item, sender, recipient, transaction trace and inclusion/finality. Store transaction hash, LT/block/proof/source/time; define disagreement, lag, reorg/rollback and outage policy.

### Backend/state machine
- One transition service with state, actor, evidence and ownership guards.
- PostgreSQL concurrency tests across reservation, expiry, cancellation, payment, dispute, refund, delivery and payout.
- Durable inbox/outbox with leases, retries, dead-letter queue, reconciliation and manual resolution.
- Never hold a DB transaction open across slow external calls; revalidate state under lock afterwards.
- No client/admin UI path may directly set paid/completed/refunded/payout states without verified evidence and audited authorization.

## 7. Required edits to ADR-0002

| ADR-0002 area | Required edit |
|---|---|
| Lines 84, 163, 424 | Distinguish Telegram's contractual “purveyor” duties from legal merchant-of-record status. Keep MoR as a counsel/provider decision. |
| Lines 155, 170–173 | Keep external-site/deep-link permission OPEN; don't overstate §6.2 as banning every external link, and don't use a link to bypass Stars for an in-TPA digital-goods sale. |
| Lines 193–206, 214 | Separate MVP DB reservation from actual on-chain escrow deposit. Remove wording implying MVP NFT lock. |
| Lines 224–245 | Specify where seller payout money comes from, who owns/holds it, which rail pays it and what happens when the rail fails. Separate Stars balance from fiat remedy reserve. |
| Lines 277–300 | Redesign transitions around delivered-unsettled, dispute hold, settlement eligibility, refund unknown and payout states. A DB lock does not resolve cross-system races. |
| Lines 310–330 | Add distinct-charge/late-payment handling, one accepted payment per order, durable side-effect commands and provider reconciliation. Resolve webhook vs polling. |
| Lines 292, 321, 330, 367–379 | Specify ownership evidence level and TON escrow oracle/collection validation; don't label indexed API response as cryptographic proof. |
| Lines 326 | Require PSP-supported idempotency and reconciliation of payout returns/unknown outcomes. A unique local row is insufficient. |
| Lines 340, 440 | Separate chain non-delivery from misdescription and statutory consumer claims. Define dispute policy with counsel. |

## 8. Recommended decision path

1. **Do not implement payment or seller payout yet.**
2. Obtain written Telegram/store guidance on the product's digital-goods classification and external checkout/deep-link policy.
3. Decide whether the first release is (a) no-money listing/transfer coordination, (b) Stars-only with no sale enabled until settlement and remedies are real, or (c) an independently underwritten PSP flow.
4. If exploring production escrow, keep PR #36 as the research baseline but write the contract state machine, validation/oracle design, and complete failure matrix before coding.
5. Specify durable financial ledger, inbox/outbox, idempotency and reconciliation semantics.
6. Have payment/legal counsel review seller settlement, consumer claims, KYC/AML/sanctions, tax, chargeback and insolvency exposure.
7. Independently audit the contract and payment integration; test failures on testnet/sandbox; launch only after explicit go/no-go sign-off.

## 9. Official references

The following are primary references for the key platform/technical claims. They should be re-checked at implementation time because terms and APIs can change.

### Telegram
- [Telegram Bot Developer Terms](https://telegram.org/tos/bot-developers) — TPA purveyor responsibilities, Stars ownership/use, digital goods and disputes.
- [Telegram Bot API — Payments](https://core.telegram.org/bots/api#payments) — payment flow, pre-checkout and successful payment updates.
- [Telegram Bot API — refundStarPayment](https://core.telegram.org/bots/api#refundstarpayment) — refund arguments and original-charge linkage.
- [Telegram Bot API — setWebhook](https://core.telegram.org/bots/api#setwebhook) and [getUpdates](https://core.telegram.org/bots/api#getupdates) — webhook/polling mutual exclusion and webhook secret token.
- [Telegram Stars for Digital Goods and Services](https://core.telegram.org/bots/payments-stars) — Stars-specific payment requirements and operational rules.

### TON / NFT
- [TON NFT standard (TEP-62)](https://github.com/ton-blockchain/TEPs/blob/master/text/0062-nft-standard.md) — NFT item transfer and ownership-assigned notification semantics.
- [TON smart contracts overview](https://docs.ton.org/v3/documentation/smart-contracts/overview) — message-driven asynchronous contract execution.
- [TON Center API v3 documentation](https://docs.ton.org/v3/guidelines/dapps/apis-sdks/api-toncenter) — indexed API model; distinguish indexed reads from cryptographic proof verification.
- [TON Connect proof](https://docs.ton.org/develop/dapps/ton-connect/sign) — wallet proof semantics; not proof of NFT delivery.

### PSP / payout
- [Adyen Transfers documentation](https://docs.adyen.com/platforms/online-payments/transfer-funds/) — platform transfers and lifecycle.
- [Adyen transfer webhooks](https://docs.adyen.com/platforms/online-payments/transfer-funds/transfer-webhooks/) — asynchronous transfer status updates.
- [Adyen balance accounts and negative balances](https://docs.adyen.com/platforms/manage-users/manage-account-holders/) — account-holder/platform exposure depends on configured model and contract.

**Evidence discipline:** provider documentation establishes API mechanics, not that a provider will underwrite this specific NFT marketplace or that the proposed legal structure is permitted. Obtain written product approval and legal advice; do not infer them from API availability.
