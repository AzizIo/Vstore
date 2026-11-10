# Discussion 0001: Safe Deal, Payments, Escrow and NFT Delivery

- **Status:** OPEN — architecture decision required
- **Created:** 2026-11-10
- **Repository:** `AzizIo/Vstore`
- **Related decision:** [ADR-0001: Compliant payments and escrow architecture](../adr/0001-compliant-payments-and-escrow.md)
- **Related design:** [Payments and escrow technical design](../PAYMENTS_ESCROW_DESIGN.md)
- **Related lifecycle:** [Buyer order lifecycle](../ORDER_LIFECYCLE.md)
- **Purpose:** collect independent proposals from the maintainer and collaborating coding/research agents before choosing the production transaction model.

> This document is an active discussion workspace, not an approved architecture or implementation spec. Do not implement live payment, custody, escrow, payout, or irreversible NFT delivery based only on a proposal written here. Record assumptions, sources, risks, and unresolved questions.

---

## 1. The decision we need to make

Design a marketplace transaction that is honest about the protection it provides and can be operated safely:

1. A buyer pays for a real TON NFT.
2. The seller delivers the exact NFT to the buyer's verified wallet.
3. The buyer has a credible remedy if delivery fails, the wrong asset is delivered, or a dispute occurs.
4. The seller receives the agreed proceeds, with a transparent marketplace fee.
5. Duplicate requests, forged payment notifications, chain delays, retries, worker crashes, and concurrent buyers cannot cause double payment, double delivery, or inconsistent order state.
6. The flow complies with Telegram, TON, payment-provider, app-store, and applicable legal requirements in the target jurisdictions.

**The main question is not merely “which payment API do we integrate?” It is: who controls the money and NFT at every point, what evidence permits each transition, and how can a buyer be made whole when an NFT transfer is irreversible?**

## 2. Current repository baseline — do not assume future features exist

As of this document's creation:

- Orders can be created from ACTIVE listings. Creation snapshots price/currency, reserves the listing atomically, and writes an append-only event.
- The implemented order statuses are only `pending_payment`, `cancelled`, and `expired`.
- Pending orders expire; a buyer can cancel them. The listing is released when the order is cancelled or expires, subject to listing expiry.
- Order creation uses an idempotency key and a unique open-order constraint per listing.
- Telegram order notifications use a durable outbox.
- `PaymentAdapter` is only an interface/protocol. It is not connected to a real payment provider.
- There is no real payment collection, payment ledger, refund flow, seller payout, production escrow, or automatic NFT transfer.
- Issue #28 tracks fresh NFT ownership verification before order reservation and is being handled separately. This discussion must not silently assume it is already merged.
- Existing NFT verification uses TON/TEP-62 concepts. Standard TON NFT ownership and Telegram Business Gifts are distinct asset paths; do not mix their transfer permissions or guarantees.

Read the linked ADR/design before proposing changes. If the code or official policy has changed, cite the exact current code path, commit, and source.

## 3. Existing constraints and known risks to validate

These are constraints recorded in ADR-0001, not a substitute for re-checking sources at implementation time:

1. **Telegram checkout:** Telegram's current developer guidance requires Telegram Stars (`XTR`) for digital goods/services sold inside bots and Mini Apps. Do not suggest TON Connect as a way to bypass the Stars requirement for an in-app digital-goods checkout. The classification and permissibility of peer-to-peer TON NFT resale must be specifically verified with platform/legal review.
2. **Stars are not a seller escrow ledger:** Stars accrue to the Telegram account that owns the Mini App/bot. This does not automatically create segregated balances or trust-held funds for each seller. Fragment rewards, availability, country eligibility, rates, and timing must not be promised as fixed seller payouts.
3. **Irreversible delivery:** TON NFT transfers can be irreversible. Telegram's developer terms include a warning about real-time sales of valuable virtual items that cannot be reclaimed/frozen/rescinded after successful disputes or chargebacks. This is a launch blocker to investigate, not a UX footnote.
4. **TON Connect:** the marketplace must not collect users' seed phrases or private keys. Wallet connections/signatures do not themselves provide escrow or prove that an asset has been delivered.
5. **Escrow is not automatically compliant:** a smart contract can hold assets, but custody, operator control, upgrades, dispute authority, payout obligations, and jurisdictional treatment still require review.
6. **Provider events are untrusted until verified:** never trust a client-side “paid” claim. Validate the provider secret/signature, stored invoice/order identity, exact amount/currency/payer, and unique charge reference. Make retries idempotent.
7. **Indexer data is not infallible:** TON Center/indexer ownership observations may lag or fail. Distinguish provider outage from a confirmed owner mismatch. Never mark an NFT transferred merely because a provider is unavailable.

Official references to re-check and cite in proposals:
- Telegram Stars: https://core.telegram.org/bots/payments-stars
- Telegram Bot Developer Terms, digital goods and services: https://telegram.org/tos/bot-developers#6-2-digital-goods-and-services
- Telegram Bot API: https://core.telegram.org/bots/api
- Telegram webhook secret token: https://core.telegram.org/bots/api#setwebhook
- Telegram Stars refunds: https://core.telegram.org/bots/api#refundstarpayment
- TON Connect: https://docs.ton.org/applications/ton-connect
- TON NFT standard TEP-62: https://github.com/ton-blockchain/TEPs/blob/master/text/0062-nft-standard.md
- TON NFT transfer mechanics: https://docs.ton.org/contracts/standard/tokens/nft/how-it-works

## 4. Models to compare (agents may add alternatives)

Do not assume one of these is acceptable. Evaluate each against the same criteria.

### A. Stars checkout + operator-managed seller settlement (no on-chain escrow)

- Buyer pays Stars through an invoice created by the backend.
- Seller transfers the NFT directly to the buyer's verified wallet.
- Backend verifies ownership after transfer.
- Any seller settlement is a separate operator-managed process, not an automatic consequence of Stars being received.
- Examine: seller non-delivery risk, refunds after irreversible transfer, operator obligations, payout accounting, Fragment availability, Telegram policy, and whether this can honestly be called a “safe deal”.

### B. TON NFT escrow contract + a separately compliant payment path

- Seller deposits the exact NFT into an escrow contract.
- Contract/watcher verifies deposit before the order can proceed.
- Release/refund/dispute paths are explicit and enforceable.
- Evaluate how buyer payment can lawfully and practically coexist with the escrow, without using TON Connect to circumvent Telegram's in-app Stars requirement.
- Examine admin powers, multisig/timelock, upgrades, bounce handling, timeouts, replay protection, contract audit, and what happens when Stars are refunded but NFT release already occurred (and vice versa).

### C. External payment processor / external web checkout

- Evaluate providers that explicitly accept NFT/virtual-asset marketplaces and the exact target business model.
- Determine whether and how a Telegram Mini App can direct users to such a flow without violating Telegram or app-store rules.
- Examine chargebacks, provider reserves, seller onboarding, KYC/AML, supported countries, fees, payout timing, and dispute evidence.
- Do not assume a generic payment processor accepts NFT resale.

### D. Non-custodial peer-to-peer exchange (no guaranteed escrow)

- Buyer and seller interact directly; the app provides listing, verification, order coordination, and transaction monitoring.
- State clearly what the platform does and does not guarantee.
- Examine whether this is a viable interim product, how to reduce fraud, and whether the product may call itself a marketplace but must avoid “guarantor/safe deal” claims.

### E. Other model

Propose any alternative, including a hybrid, only with a clear trust/custody diagram and platform-policy analysis.

## 5. Required questions for every proposal

Every agent must answer these questions. “Use blockchain” or “use Stars” is not a sufficient answer.

### 5.1 Money flow
- Who receives the buyer's payment first: Telegram/TPA owner, licensed PSP, seller, escrow contract, or another party?
- Who legally/operationally controls it between payment and delivery?
- Is money segregated per order or seller, or merely represented by a database balance?
- How is marketplace commission calculated and recorded?
- How and when does the seller receive proceeds? Who initiates and signs the payout?
- What is the exact refund path before and after NFT delivery?
- What happens if the payment provider account, bot owner, PSP, or payout route is frozen/terminated?

### 5.2 NFT flow
- Where is the NFT at each step: seller wallet, escrow contract, buyer wallet?
- What exact on-chain evidence proves deposit, release, refund, or final ownership?
- Which wallet address is verified for the buyer and seller, and how is wallet replacement/revocation handled?
- Can the seller transfer the NFT away after listing or after reservation?
- What prevents a wrong NFT, fake collection, stale owner, or double sale?
- Which actions are manual, signed by the user, executed by a contract, or performed by a worker?

### 5.3 Disputes and failure recovery
- Define concrete outcomes for: seller never delivers; transfer to wrong address; transfer is pending; indexer is down; payment succeeds but webhook is lost; duplicate webhook; buyer claims non-receipt after confirmed transfer; seller disappears; refund races with release; escrow contract or watcher is unavailable.
- Who decides a dispute, based on what evidence, within what deadline?
- Can the decision be reversed? What happens if the NFT cannot be reclaimed?
- Is there a credible buyer-compensation source, and who funds it?

### 5.4 Platform/legal/commercial fit
- Does the flow comply with current Telegram rules for this exact NFT resale model?
- Does it require written platform confirmation or legal advice before launch?
- Which jurisdictions are in scope? Analyze money transmission/custody, KYC/AML/sanctions, consumer rights, taxes, data protection, and age restrictions as applicable.
- Are app-store rules or PSP acquiring restrictions relevant?
- What user-facing wording is accurate? When may the product use “safe deal”, “escrow”, “guarantee”, or similar claims?

### 5.5 Implementation and security
- Which backend modules, DB tables, state transitions, and workers are required?
- Which operations must happen outside database locks, and which must be committed atomically?
- What are the idempotency keys and unique constraints?
- What are the trust boundaries and principal attack vectors?
- What unit, integration, PostgreSQL concurrency, contract, and end-to-end tests are required?
- What is the smallest safe testnet/test-provider milestone, and what evidence is required before production?

## 6. Required deliverables from each agent

Each agent should add a separate proposal under:

`docs/discussions/proposals/<agent-or-team>-<short-name>.md`

Use this template:

```md
# Proposal: <name>

- Author/agent:
- Date:
- Preferred model: A / B / C / D / E
- Confidence: high / medium / low

## Executive recommendation
## Money-flow diagram
## NFT-flow diagram
## Order/payment state machine
## Refund and dispute policy
## Telegram / provider / legal constraints
## Threat model and failure matrix
## Data model and API changes
## Test plan and rollout phases
## Estimated operational burden
## Risks and unresolved questions
## Sources (official links, access date, relevant section)
```

Agents must distinguish:
- **Verified fact** — supported by current official documentation or code.
- **Assumption** — not yet verified.
- **Recommendation** — proposed design choice.
- **Open question** — requires maintainer, platform, provider, security auditor, or legal counsel decision.

Do not overwrite another agent's proposal. Do not edit the existing ADR as if a proposal has already been approved. Submit a PR for substantial changes and link it below.

## 7. Evaluation matrix

Score each model from 1 (poor/unknown) to 5 (strong), and explain every score. Mark “BLOCKER” where a legal or platform gate is unresolved; do not hide blockers inside an average.

| Criterion | A | B | C | D | E |
|---|---:|---:|---:|---:|---:|
| Telegram policy fit | | | | | |
| Buyer protection before delivery | | | | | |
| Credible remedy after failed/irreversible delivery | | | | | |
| Seller payment certainty | | | | | |
| Custody / regulatory complexity | | | | | |
| Fraud and double-sale resistance | | | | | |
| Technical feasibility on TON | | | | | |
| Operational burden | | | | | |
| Refund / chargeback compatibility | | | | | |
| Country availability | | | | | |
| Time and cost to a safe pilot | | | | | |

A model with an unresolved policy/legal BLOCKER cannot be recommended for production, regardless of its score.

## 8. Discussion log

Add dated entries here with a short summary and a link to the proposal/PR. Keep the raw debate in proposal files or PR discussions.

| Date | Agent / participant | Proposal or PR | Main finding | Status |
|---|---|---|---|---|
| 2026-11-10 | Maintainer | — | Discussion opened; no production model approved | OPEN |

## 9. Maintainer decision — leave unresolved until review

The final decision must state:

- Selected model and why alternatives were rejected/deferred.
- Whether the product can honestly offer a “safe deal” and under what exact conditions.
- What is explicitly not guaranteed.
- Platform/legal approvals and target jurisdictions still required.
- Custody and seller-settlement responsibility.
- Approved MVP scope versus testnet-only scope.
- Production launch gates, owners, and evidence required.
- Which ADR/design/lifecycle docs and issues must be updated.

**Current decision: NOT DECIDED.** ADR-0001 remains the current guardrail until a new reviewed ADR supersedes it.
