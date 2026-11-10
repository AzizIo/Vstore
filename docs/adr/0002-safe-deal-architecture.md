> **Repository audit note (2026-11-10):** This candidate ADR contains authoring/source-access dates of 2026-11-11, which are in the future relative to the current repository audit date. Those references must be rechecked/corrected before the source ledger can be treated as current. The ADR remains **Proposed / NOT DECIDED**; ADR-0001 remains the operative guardrail until the owner approves a successor. This file is not authorization for payment or escrow implementation.

# ADR-0002: Unified safe-deal architecture

- **Status:** Proposed — awaiting owner decision. Does not supersede ADR-0001.
- **Version:** 2 — revised after independent audit (PR #38, `docs/discussions/reviews/adr-0002-independent-review.md`). Disposition of every finding in §12.
- **Date:** 2026-11-11 (v1), 2026-11-11 (v2 revisions)
- **Inputs:** [Discussion 0001](../discussions/0001-safe-deal-payment-and-escrow.md), proposal from Claude Fable 5.1 (PR #35), proposal from GPT-6 (PR #36), independent audit (PR #38), [ADR-0001](0001-compliant-payments-and-escrow.md), [payments design](../PAYMENTS_ESCROW_DESIGN.md).
- **Input path note:** the two proposals and the audit live in unmerged PRs, so they are referenced by PR number and path. Once merged, the links can be made relative without changing content.
- **Non-goal:** no payment implementation, no custody, no escrow contract, no production approval.

> **Decision status: NOT DECIDED. Final status for real paid trades: NO-GO** until every critical condition in §9 is confirmed in writing. ADR-0001 remains the operative guardrail until the owner approves a successor.

---

## 0. Evidence standard

Every claim carries one of five marks. The audit (F-01…F-18) is treated as an input whose correctness I re-checked where a primary source was reachable; where it was not, I say so.

| Mark | Meaning |
|---|---|
| **[V]** Verified | Read from a primary source during this research, or directly from the repository. §11 lists locations. |
| **[A]** Assumption | Plausible, unverified, or verified only against a non-authoritative copy. Never justifies a launch decision. |
| **[R]** Recommendation | A design choice requiring owner approval. |
| **[OPEN]** | Requires a named human decision — owner, lawyer, platform, provider, or auditor. |
| **[AUDIT]** | A point raised by the independent audit, with my disposition in §12. |

**Research limitation.** `core.telegram.org` and `telegram.org` are unreachable from the authoring environment (DNS resolves; TLS/HTTP blocked). Telegram terms, the Stars page and the **Bot API reference** were read from Internet Archive snapshots (2026-10-26, 2026-11-06, and a 2026 Bot API snapshot) and are marked **[V]** as archived copies. EUR-Lex returned empty bodies, so **MiCA is [A] and is not used to justify anything**. German ZAG §1 and §2 were read live.

---

## 1. What each input contributed

### 1.1 Retained from PR #36 (GPT-6)

| Contribution | Status |
|---|---|
| NFT deposit **before** payment capture | Adopted as the production ordering rule (§4.2) |
| Separate records per trust boundary, not one overloaded status | Adopted (§6.1) |
| Durable webhook **inbox** in addition to an outbox | Adopted (§7.4) |
| Explicit reserve / chargeback liability | Adopted (§5.4) |
| Refusal to call a database ledger "escrow" | Adopted throughout |
| Asynchronous-saga framing instead of atomicity | Adopted (§4.3) |

### 1.2 Corrected in PR #36

| Claim | Correction |
|---|---|
| Adyen is "the most technically promising candidate" | **[A]** Adyen's platform docs describe capabilities, not NFT acceptance. It is an unverified candidate and nothing more (§2.3). |
| Stripe merely "restricts" NFT activity | **Understated.** "Secondary NFT sales" sits under Stripe's **Prohibited Businesses** heading **[V]** (§2.3). |
| Escrow materially improves post-delivery remedy | It does not. #36 scores its own model B at 2/5 on that criterion. Remedy is a money problem (§5.2). |
| Deposit-first is the launch recommendation | Kept as the production direction, but it depends on a contract that does not exist and cannot verify collections synchronously **[V]** (§8). |

### 1.3 Retained from PR #35

| Contribution | Status |
|---|---|
| The binding constraint is *who reimburses the buyer*, not who holds the NFT | Core of §5 |
| Buyer-wallet snapshot at payment time | Adopted (§6.2) |
| Chain evidence preferred over testimony | Adopted, with the correction in §8.4 |
| Dual-control dispute decisions | Adopted (§7.3) |

### 1.4 Corrected in PR #35

| Defect | Correction |
|---|---|
| **[AUDIT]** F-09: described the **buyer** sending the TEP-62 transfer | **Rejected as written.** **[V]** TEP-62 rejects a transfer "not from current owner"; the **seller's** wallet initiates it. Fixed in §8.1. |
| **[AUDIT]** F-10: treated a third-party current owner as seller fraud | **Accepted.** Current owner is a point-in-time fact, not a delivery history. Fixed in §8.4. |
| **[AUDIT]** F-02: implied a "Stars remedy fund" and Stars-based seller settlement | **Accepted.** **[V]** Stars are not the operator's property and there is no per-seller transfer API. Fixed in §5. |
| **[AUDIT]** F-01: called a DB reservation an "asset lock" | **Accepted.** Terminology discipline in §4.1. |
| Asserted the Telegram irreversibility warning without having read it | **[V]** Now quoted in §2.1; it is real and names this product category. |

### 1.5 Verdict from the audit that I do not contest

The audit's headline — **6/10 as an architecture discussion, 3/10 as an implementation specification, 0/10 for production launch today** — is fair. Version 1 of this ADR described a saga while using the vocabulary of atomicity. This version removes that vocabulary.

---

## 2. Verified platform facts

### 2.1 Telegram

**[V] Stars are mandatory for in-app digital goods.** Bot Platform Developer Terms §6.2: "transactions for digital goods and services cannot be processed through third-party payment providers … all transactions pertaining to digital goods and services must be executed exclusively through the exchange of Telegram Stars".

**[V] Telegram delegates the classification.** §6.2 requires adherence to **Apple's and Google's** definitions of digital goods. The "is an NFT resale a digital good?" question therefore cannot be closed from Telegram's text — **[OPEN]** (§9 B1).

**[V] The operator is the purveyor and carries delivery and disputes.** §6.2.1: "As the purveyor, it is your duty to ensure that the digital products and services in your TPA are delivered as advertised and in a timely manner". Every TPA must answer `/paysupport`. Telegram "has no obligation to mediate" and is "not responsible for refund claims initiated via third-parties".

**[V] The irreversibility warning names this product.** §6.2.1: "Telegram expressly discourages the real-time sale of digital products, virtual items and digital services which hold inherent value and cannot be reclaimed, frozen, rescinded, invalidated or suspended following a successful dispute or chargeback by the purchaser."

**[V] A dispute refund is deducted from the TPA balance.** §6.2.1.

**[V] Stars on the balance are not the operator's property.** §6.2.2: "Telegram Stars displayed in your balance do not constitute your property … Stars on your TPA's balance are owned by Telegram and have no inherent value beyond our good-faith commitment to advertisement credits and rewards".

**[V] No per-seller settlement exists.** §6.2.4: rewards of "0.013 USD worth of rewards for each Telegram Star", value set "in its sole discretion", availability delayed "up to 21 days", processed by Fragment, which "may be unable to issue rewards for certain users or in certain countries". Rewards are an operator-level conversion, not a transfer to a third party.

**[V] Stars are not escrow.** One pooled balance, owned by Telegram, no sub-accounts, single discretionary exit. **No part of this ADR treats Stars as escrow.**

**[V] `refundStarPayment` is narrow.** Bot API: "Refunds a successful payment in Telegram Stars. Returns True on success." Parameters are exactly `user_id` and `telegram_payment_charge_id`. **[AUDIT F-03 accepted]** There is **no amount parameter and no partial refund**; the call refunds the original payer's charge. It cannot pay a seller, top up a balance, or succeed from a fiat reserve.

**[V] Polling and webhook are mutually exclusive.** Bot API `getUpdates`: "this method will not work if an outgoing webhook is set up". **[AUDIT F-08 accepted]** The repository currently runs aiogram `start_polling` (`backend/app/bot.py`). One ingress must be chosen.

**[V] The webhook secret is a header, not a body HMAC.** `setWebhook` accepts `secret_token`; requests then carry `X-Telegram-Bot-Api-Secret-Token`. Updates also carry a unique `update_id` usable for deduplication.

**[V] A successful pre-checkout answer is not proof of payment.** It authorises the charge; only `successful_payment` (with `telegram_payment_charge_id`) evidences money.

### 2.2 TON

**[V] No safe transfer exists in TEP-62.** The standard's unresolved questions: "There is no standard methods to perform 'safe transfer', which will revert ownership transfer in case of contract execution failure." `NFTBounceable` is only a Draft extension.

**[V] Transfer is owner-only, one-way, and seller-initiated.** `transfer#5fcc3d14`; "should be rejected if: message is not from current owner"; then owner is replaced; optional `ownership_assigned#05138d91` when `forward_amount > 0`; excess returned.

**[V] Collection membership must be proven, not read.** TON docs: "Not every NFT that stores a collection address actually belongs to that collection."

**[V] TON `get` methods are off-chain.** They are executed by a node/RPC client on request; they are not synchronous calls a contract can make during its own transaction. Inter-contract communication is asynchronous messaging. **[AUDIT F-11 accepted]** — this invalidates any design where "the contract calls `get_nft_address_by_index()`".

**[V] TON Connect never touches keys.** It requests signatures and transactions; and restates the Stars rule for Mini Apps.

### 2.3 Payment providers

**[V] Stripe prohibits secondary NFT sales.** `stripe.com/legal/restricted-businesses` lists "Secondary NFT sales" under the **Prohibited Businesses** heading, while "First-party NFTs minting and sales, including marketplaces and SaaS platforms" is a separate restricted category. VILTARA resells assets it did not mint. **Consequence: Stripe is unavailable for this product**, not merely "not to be assumed".

**[A] Adyen and MANGOPAY remain unverified.** Adyen's platform documentation describes onboarding, split payments and payouts; no NFT acceptance was found in reachable pages. MANGOPAY advertises "Crypto Platforms" without publishing NFT underwriting. Neither is a finding of availability, and **[A]** neither has published a payout-status model I verified here.

### 2.4 Germany (research lens only)

**[V] ZAG §1(1)(6)** defines *Finanztransfergeschäft* as accepting a payer's money, **without establishing a payment account in the payer's or payee's name**, solely to transmit it to a payee or to another provider acting for the payee.

**[V] ZAG §2(1)(9)** exempts technical service providers who contribute to a payment service but **"at no time come into possession of the funds to be transferred"**.

**[V] ZAG §2(1)(2)** exempts transactions through a commercial agent authorised to negotiate or conclude the sale or purchase **only in the payer's or only in the payee's name**.

**[R]** These three provisions frame the central fork, and it is the most useful structural finding available without counsel: **the moment the operator can hold or release money at its own discretion, §2(1)(9) is unavailable by its own wording**, and §1(1)(6) becomes the natural classification. This is a structural observation about one jurisdiction, not legal advice. **[OPEN]**

---

## 3. Honest classification of operations

### 3.1 Permitted today, no legal opinion needed

| Operation | Basis |
|---|---|
| Catalog, search, listing detail, NFT verification | Ordinary TPA functionality |
| Wallet proof via TON Connect; storing a verified address | **[V]** keys never leave the user |
| Creating orders and database listing reservations (no money) | Existing behaviour |
| Order-state notifications | Existing outbox |
| Displaying a TON-priced listing as **view-only** | No transaction executed |

### 3.2 Requires an external, separately approved surface

| Operation | Why |
|---|---|
| Card or fiat checkout | **[V]** §6.2 forbids third-party processors for in-app digital goods |
| Bank payout to sellers | **[V]** Stars exit only via Fragment rewards (§2.1) |
| Chargeback handling | **[V]** Telegram disclaims third-party refund claims |

**[AUDIT F-13 accepted]** Whether a separate website may promote the same inventory, or whether a deep link from the Mini App to it is permitted, is **[OPEN]**. What the reviewed text supports is narrower than v1 of this ADR claimed: it prohibits routing a TPA digital-goods transaction through a third-party provider, which is a statement about *the transaction*, not a categorical ban on *any link to a website*. I have removed the categorical wording. The hard rule that survives unchanged:

> **Do not route a purchase that is part of the TPA's digital-goods flow through a third-party PSP, and do not use an external surface as a workaround for the Stars requirement.** Witnessed basis: §6.2 non-compliance puts the TPA at risk of removal from store versions and termination from Bot Platform.

### 3.3 Requires legal confirmation before launch

| Question | Blocker |
|---|---|
| Is P2P resale of an existing TON NFT a "digital good" under Apple/Google rules? | B1 |
| Does operator-controlled payout release make VILTARA a payment service (ZAG §2(1)(9) vs §1(1)(6))? | B2 |
| Is VILTARA the merchant of record, and for which obligations? | B3 |
| Is holding an NFT in a contract a regulated custody activity? | B6 |
| KYC/AML, sanctions, tax, consumer withdrawal | B5 |
| Can a financed reserve be described as "protection"? | B4 |

**[AUDIT F-14 accepted]** §6.2.1 imposes **contractual platform duties** on the TPA operator: deliver as advertised, answer `/paysupport`, absorb dispute debits. That is not the same as being the legal **merchant of record** for tax, consumer, acquiring or financial-services purposes. This ADR now keeps the two separate everywhere, and **v1's conflation is removed**. Merchant-of-record status is a jurisdiction- and contract-specific question for counsel and the provider — **[OPEN]**.

### 3.4 Not permitted or not defensible

- Describing Stars as escrow, held funds, or buyer protection. **[V]** §2.1.
- Calling the platform "non-custodial" while it controls buyer money and releases it to sellers.
- Using Stripe for this model. **[V]** §2.3.
- Labeling a database reservation an "asset lock" or "custody" **[AUDIT F-01 accepted]** (§4.1).
- Launching live paid trades before §9 blockers clear.

---

## 4. The unified architecture

### 4.1 Terminology discipline

**[AUDIT F-01 accepted — Critical]** v1 described an "asset lock" in the MVP that was only a database row. These are different things and the document now uses different words.

| Term | What it actually is | What it must never imply |
|---|---|---|
| **Database listing reservation** | a `listings.status = reserved` row preventing another **VILTARA order** | that the NFT cannot move |
| **Ownership observation** | a point-in-time read through an indexer | that ownership persists |
| **Verified ownership at reservation** | observation + identity binding, valid at that instant | a guarantee until payment |
| **On-chain asset lock / custody** | the NFT is held by a contract the seller no longer controls | anything in MVP |
| **Escrow** | the *on-chain asset lock* plus a defined release policy | a database table, a Stars balance, or an operator ledger |

**Consequence:** MVP has **no** asset lock. The seller can transfer the NFT away at any moment after any observation. That residual risk is stated in §4.2 and must be either funded (§5.2) or removed by declining to sell (§9).

### 4.2 Ordering rules per phase

```text
  Order  ──  Payment (provider)  ──  Asset (chain)  ──  Settlement (money out)
     \            \                     /                  /
      └── append-only event log ───────┴──────────────────┘
```

**[R]** One rule for the production phase, and an explicit statement that MVP does not satisfy it:

| Phase | Asset position at capture | Rule satisfied? | Stated honestly as |
|---|---|---|---|
| **MVP** | stays in seller wallet; observed immediately before capture | **No** | database listing reservation + ownership observation |
| **Next** | stays in seller wallet; delivery proven on chain before settlement | **No** (settlement-side instead) | delivery-verified settlement |
| **Production** | deposited **into an escrow contract** before capture | **Yes** | on-chain escrow with audit |
| **Prohibited** | — | — | any paid sale with neither an asset lock nor a funded remedy |

**[R]** MVP's residual risk — seller transfers after observation, buyer pays, nothing delivered — is **not** solved by the reservation. It is solved only by money (§5.2) or by not selling (§9, option A).

### 4.3 This is a saga, not an exchange

**[AUDIT F-05, F-17 accepted]** Three independent systems fail independently: Telegram payments, the TON chain, an operator or PSP settlement rail. PostgreSQL serialises **local** transitions only. It cannot undo a refund Telegram already accepted, a payout a PSP already booked, or a transfer already included on chain.

**[R]** Therefore every external effect is a **durable command with three outcomes**, never a boolean:

```text
  requested ──▶ confirmed        (provider/chain evidence of the effect)
      │
      ├──────▶ unknown          (timeout, lost response, outage)
      │             │
      │             └──▶ reconcile by querying provider/chain, then confirm or retry
      │
      └──────▶ rejected         (explicit failure)
```

**[R]** A command row is written **in the same DB transaction as the decision to perform it**, so a crash cannot lose the intent. `unknown` is a first-class state, never collapsed into success or failure. No relisting, no settlement, and no completion may proceed from `unknown`.

---

## 5. Money, remedy, and three separate rails

**[AUDIT F-02, F-03 accepted — Critical]** v1 used one word, "refund", for three economically different flows. They now have separate states, separate ledgers and separate failure handling.

### 5.1 Three rails

| Rail | Direction | Instrument | Can it be partial? | Ledger |
|---|---|---|---|---|
| **S — Stars refund** | operator → original buyer | `refundStarPayment(user_id, telegram_payment_charge_id)` | **No** **[V]** | `stars_refunds` |
| **C — Operator compensation** | operator → buyer or seller | operator fiat capital | Yes, capped | `compensation_entries` |
| **P — Seller payout** | operator or PSP → seller | operator fiat / PSP transfer | Yes (fees withheld) | `seller_payouts` |

**[R]** Rail S settles the *original charge* to the *original payer*. Rail C is the operator's own money and is the only instrument that can pay someone who is not the original payer, or pay more than the original charge. **Rail C must never be described as a Stars refund, and Rail S must never be assumed to work because a fiat reserve exists.**

### 5.2 The remedy fund, stated precisely

| Pot | Backing | What it can promise |
|---|---|---|
| Seller entitlement ledger | Database record of an operator obligation | A contractual debt; **not** money, **not** collateral, **not** escrow |
| Remedy fund | **Operator fiat capital, segregated and audited** | A disclosed per-order cap |

**[V] Correction to PR #35 carried forward:** because Stars are not the operator's property, a "Stars remedy fund" is a promise, not a reserved asset. **[R]** The fund must be denominated in operator fiat, sized to expected concurrently-pending exposure, disclosed as a number, and audited. Without it the honest claim is *"we refund Stars if the NFT is not delivered"* (Rail S), not *"your purchase is protected"*.

### 5.3 Where seller money comes from — the unresolved core

**[AUDIT F-02 accepted]** The audit is right that this was hand-waved. Three paths, and the owner must choose one before accepting paid orders:

| Path | Mechanism | Requires |
|---|---|---|
| **P0 — no payout** | MVP sells nothing, or sells with no seller settlement | no legal work; also no product |
| **P1 — operator fiat** | Named entity pays sellers from its own bank account on a schedule | entity, contract, funding, KYC, tax, FX, insolvency disclosure |
| **P2 — licensed PSP** | Provider withholds and pays out under its contract | written underwriting (§9 B7) |

**[R]** Telegram does **not** provide P1 or P2. Fragment converts *operator* Stars; it is not a seller settlement API **[V]**. A `seller_ledger` row is evidence of an obligation, never a balance the seller can spend.

### 5.4 Commission, reserve, and payout returns

**[R]** Fee is computed against **captured settlement amount**, not listing price, and the fee schedule version is snapshotted on the order. Never mutate a settlement row; post compensating entries.

**[R]** In any fiat phase a rolling reserve is mandatory: **[V]** Telegram disclaims third-party refund claims, and **[A]** card schemes can debit after on-chain delivery. Seller terms must state percentage, holding period, replenishment, and negative-balance allocation.

**[AUDIT F-15 accepted]** **[R]** "Booked" is not "received". Payout terminal states are `created → submitted → unknown → booked → settled_to_bank / returned / failed`, and a `returned` payout **reopens** the payable. Adyen's own documentation distinguishes transfer status from final receipt **[A]**, and no provider is assumed to support this model without written approval.

---

## 6. Full lifecycle and state machine

### 6.1 Records

**[R]** Separate records, never one overloaded status. `orders.status` keeps its existing three early states and gains only what §6.2 defines.

| Record | Owns | Trusted writer |
|---|---|---|
| `orders` | the deal's commercial terms and lifecycle state | order service |
| `payment_intents` / `payment_transactions` | money in; accepted charge per order | provider webhook + reconciliation |
| `stars_refunds` | Rail S progress per charge | payment worker |
| `compensation_entries` | Rail C obligations and payments | settlement service, dual control |
| `seller_payouts` | Rail P lifecycle including returns | settlement service, dual control |
| `asset_deposits` / `delivery_evidence` | chain observations and transaction history | chain observer |
| `disputes` | adjudication | opened by party, decided by admin |
| `command_outbox` | durable external effects with `unknown` state | any service, executed by workers |

### 6.2 Order state machine

**[AUDIT F-04 accepted — Critical]** v1's `completed` meant both "chain shows the buyer owns it" and "the seller has been paid", which made a post-delivery dispute either illegal or ad hoc. The states are now separated as the audit requires.

```text
  pending_payment
        │  verified provider event
        ▼
      paid ─────────────────────────┐
        │  seller declares          │
        ▼                           │
  delivery_pending                  │  dispute may open
        │  chain evidence: owner == snapshotted buyer wallet
        ▼                           │
  delivery_confirmed_unsettled ─────┤   ← delivered, NOT settled
        │  review window elapsed,   │
        │  no open hold             │
        ▼                           │
  settlement_eligible ──────────────┤   ← still reversible by a dispute
        │  dual approval            │
        ▼                           │
   payout_pending                   │
        │                           │
        ├──▶ payout_unknown ────────┤   ← timeout / lost response
        │        │ reconcile        │
        │        ▼                  │
        └──▶ payout_paid            │   ← provider confirms receipt
                                    │
      disputed ◀────────────────────┘   ← from paid / delivery_pending /
        │                                  delivery_confirmed_unsettled /
        │  admin decision                   settlement_eligible
        ├──▶ delivery_confirmed_unsettled (claim rejected, window resumes)
        └──▶ refund_due ──▶ stars_refund_pending ──▶ stars_refunded
                                              └──▶ stars_refund_unknown
```

### 6.3 Transition table

| # | From | To | Trusted source | Required evidence | Phase |
|---|---|---|---|---|---|
| 1 | listing `active` | order `pending_payment` | order service | authenticated buyer, snapshot, idempotency key, ownership observation | 1 |
| 2 | `pending_payment` | `paid` | payment adapter | verified `successful_payment`: payer, payload, XTR, exact total, order state, **first accepted charge for this order** | 1 |
| 3 | `paid` | `delivery_pending` | seller | seller declares; ownership re-observed at that moment | 1 |
| 4 | `delivery_pending` | `delivery_confirmed_unsettled` | system | chain evidence per §8.4 (owner **and** delivery transaction) | 2 |
| 5 | `delivery_pending` | `failed` | system | deadline exceeded, no delivery evidence | 1 |
| 6 | `paid` / `delivery_pending` / `delivery_confirmed_unsettled` / `settlement_eligible` | `disputed` | buyer | inside the review window, evidence attached | 2 |
| 7 | `delivery_confirmed_unsettled` | `settlement_eligible` | system | review window elapsed, no open dispute, no unknown command | 2 |
| 8 | `settlement_eligible` | `payout_pending` | settlement service | dual approval, no open dispute | 1 |
| 9 | `payout_pending` | `payout_unknown` | settlement service | provider timeout / lost response | 1 |
| 10 | `payout_pending` / `payout_unknown` | `payout_paid` | provider + reconciliation | provider confirms the transfer **and** its terminal status | 1 |
| 11 | `payout_paid` | `payout_pending` | reconciliation | provider reports `returned` | 2 |
| 12 | `disputed` | `delivery_confirmed_unsettled` | admin | claim rejected on evidence, window restarts | 2 |
| 13 | `disputed` / `failed` | `refund_due` | admin + policy | refund approved | 1 |
| 14 | `refund_due` | `stars_refund_pending` | payment worker | durable command row committed | 1 |
| 15 | `stars_refund_pending` | `stars_refunded` / `stars_refund_unknown` | provider | `refundStarPayment` returned True / timed out | 1 |
| 16 | `stars_refund_unknown` | `stars_refunded` / back to pending | reconciliation | provider state queried | 1 |
| 17 | any of 1–16 | `cancelled` / `expired` | buyer / worker | existing rules; never from `paid` or later | 1 |
| 18 | production: `paid` | asset `held` | chain observer | deposit to the order-bound contract, §8.3 | 3 |

**[R]** No client request writes `paid`, `delivery_confirmed_unsettled`, `settlement_eligible`, `payout_*`, or any refund state. An admin may decide a dispute but may never forge a provider event or a chain observation. `settlement_eligible` is deliberately **reversible** — that is the fix for F-04.

### 6.4 The nine operations

| Operation | Mechanism | Evidence | Failure handling |
|---|---|---|---|
| **Creation** | reservation + ownership observation | server-side snapshot only | conflicts are 409, mutate nothing |
| **Payment** | Stars invoice from the persisted snapshot | verified provider event | outage is 503, never "unpaid" |
| **NFT lock (MVP)** | **none** — reservation only | §4.1 | residual risk funded or not sold |
| **NFT lock (Production)** | TEP-62 transfer into an order-bound contract | deposit + independent read | no capture without confirmed deposit |
| **Delivery confirmation** | chain evidence per §8.4 | owner **and** delivery transaction | inconclusive ≠ failure |
| **Seller payout** | Rail P, dual control | delivery confirmed, window elapsed, no dispute | `unknown` and `returned` both handled |
| **Cancellation** | existing path | buyer authenticated | never re-exposes a stale asset |
| **Refund** | Rail S, then Rail C if S impossible | stored charge id | `unknown` is reconciled, not retried blindly |
| **Dispute** | admin on evidence packet | §8.4 evidence levels | unresolved evidence stays open, never auto-decides |
| **Compensation** | Rail C | approved claim, within cap | disclosed cap; beyond it, nothing |

---

## 7. Protections against the named failure classes

### 7.1 Duplicate and late payment

**[AUDIT F-06 accepted]** A unique charge id prevents processing *the same* charge twice. It does **not** prevent two distinct charges, a reused invoice, or a late payment after expiry.

| Control | Mechanism |
|---|---|
| One open intent per order | partial unique index on `payment_intents(order_id) WHERE status='open'` |
| Invoice bound to intent | payload = order id; expected payer recorded at intent creation |
| Invoice not reusable | intent closed on first accepted payment; new payment requires a new intent |
| **One accepted payment per order** | unique partial index on `payment_transactions(order_id) WHERE kind='payment' AND status='accepted'` |
| Exact match | payer, payload, currency `XTR`, total, order state, reservation still held |
| Pre-checkout | re-read and lock the order, answer inside Telegram's **10-second** deadline; a 200 answer is **not** payment |
| Late payment | order stays expired; **never** resurrect it, never displace another buyer; refund the original payer or open manual review |
| Excess / second charge | separate refund case via Rail S; never a second delivery |
| Update dedupe | unique `update_id` in the webhook inbox |

### 7.2 NFT substitution

Four checks, all partially implemented today:
1. canonical item address **from the order snapshot**, never from the client;
2. collection cross-check — `get_nft_address_by_index` resolves back to the same item **[V]**;
3. network equality between persisted asset and the verifier in use (PR #34);
4. metadata is display data, never identity.

### 7.3 Double payout

**[AUDIT F-07 accepted]** A unique `seller_payouts.order_id` prevents duplicate *rows*, not duplicate *transfers*.

| Control | Mechanism |
|---|---|
| Stable idempotency key | generated **before** submission and persisted; reused on every retry |
| Lifecycle | `created → submitted → unknown → booked → settled_to_bank / returned / failed` |
| Unknown handling | query the provider by reference **before** any retry |
| Returned payout | reopens the payable; seller balance may go negative |
| Dual control | preparer ≠ approver, both recorded; does not replace idempotency |

### 7.4 Ingress, webhook authenticity, replay

**[AUDIT F-08 accepted]** **[V]** `getUpdates` "will not work if an outgoing webhook is set up", and the repository currently polls. **[R]** Choose **one** ingress per deployment, enforce it in configuration, and document the switch: webhook is the recommendation because payment updates must not wait behind polling backlog. Validate `X-Telegram-Bot-Api-Secret-Token` in constant time over TLS; dedupe by `update_id`; keep acknowledgement fast and processing asynchronous through the inbox.

### 7.5 State races

**[R]** The pattern already in the codebase, to be extended: external calls happen **outside** any transaction; the transition then re-reads under `FOR UPDATE` and compares against the pre-call snapshot. Lock order is `listing → wallet → asset` in every path **[V]** (PR #34 found the deadlock the hard way).

**[AUDIT F-05 accepted]** **[R]** A row lock is **not** a cross-system mutex. Where a refund and a delivery can both be in flight, the resolution is the saga in §4.3 plus a compensation rule: if both external effects eventually land, the order goes to `disputed` with an explicit recovery policy, and the seller is not silently enriched.

### 7.6 Remedy failure

**[R]** Funded cap, disclosed, with an explicit default: **when evidence is unobtainable the claim stays open** — it is not auto-decided for either party **[AUDIT F-10 accepted]**. Auto-deciding against the seller on an indexer outage was wrong in v1 and is removed.

---

## 8. NFT verification, delivery evidence, and escrow validations

### 8.1 Who moves the NFT

**[AUDIT F-09 accepted]** **[V]** TEP-62 rejects a transfer "not from current owner". Therefore:
- the **seller's** wallet signs and sends `transfer#5fcc3d14`;
- the backend cannot force a seller's wallet to use a particular address;
- the buyer's TON Connect proof establishes the **expected destination**, not the seller's compliance;
- a transfer to a different recipient is **"delivery not confirmed"**, pending evidence — not automatic proof of fraud.

**[R]** The buyer's proven wallet address is snapshotted on the order at payment time (§6.1) and is the sole comparison target for delivery. If the buyer unbinds that wallet later, the snapshot still governs.

### 8.2 Evidence levels

**[AUDIT F-12 accepted]** TON Center API v3 is an **indexed observation** — useful evidence, not a cryptographic proof. The code today uses it (`backend/app/assets/ton_nft/verifier.py`), and the vocabulary must match.

| Level | Evidence | Strength | Use |
|---|---|---|---|
| **L0** | single indexer HTTP response | observation | discovery, MVP |
| **L1** | two independent indexers agree, timestamps recorded | corroborated observation | MVP settlement gate |
| **L2** | lite-server proof / Merkle-verified state | cryptographic | high-value production |
| **L3** | L2 + full transaction trace, tx hash, LT/block, inclusion and finality | strongest | disputes, audit |

**[R]** Persist **observation metadata** — item address, observed owner, source, transaction hash, LT/block, fetch time — not just a JSON blob. Define disagreement, lag and outage handling; disagreement at L1 escalates, never averages.

### 8.3 Concrete collection validation for a future escrow contract

**[AUDIT F-11 accepted — Critical for production]** A TON contract cannot synchronously call another contract's `get_nft_data()` or a collection's `get_nft_address_by_index()`. **[V]** Any design saying "the contract validates the collection" is unimplementable as written.

**[R]** Three-part validation, each part doing only what it can:

| Layer | Who | What it proves |
|---|---|---|
| **Off-chain admission** | backend, before an order is openable | item address is the address the collection returns for its index; item implements TEP-62; network matches; **the item address is written into the order record** |
| **In-contract binding** | escrow contract | the deposit message comes from **exactly the item address stored for this order nonce**, and the item's current owner is the contract. It does **not** attempt collection resolution |
| **Post-hoc attestation** | watcher, independent of the contract | after deposit and after release, re-reads owner **and** collection resolution; disagreement freezes settlement |

**[R]** Because the contract cannot re-derive collection membership, the trust model must be explicit and chosen by the owner:

| Option | Mechanism | Cost |
|---|---|---|
| **A — allowlist** | contract stores an immutable allowlisted collection registry; orders only openable for allowlisted collections | operational work per collection; no oracle |
| **B — signed attestation** | off-chain oracle signs `(item, collection, network, order nonce, seller, deposit tx)`; contract verifies signature and expiry | oracle key management, quorum, rotation, conflict policy |
| **C — hybrid** | allowlist for the store's own collections, attestation for others | both |

**[OPEN]** The owner must choose A, B or C, and define signer quorum, rotation, replay protection, expiry and outage policy for B. This is a **blocker for production**, not for MVP.

### 8.4 Delivery evidence and dispute facts

**[AUDIT F-10 accepted]** Current owner alone cannot distinguish "seller never delivered" from "buyer received it and moved it on".

**[R]** A dispute packet must contain, per §8.2:
1. the item address from the order snapshot;
2. the **delivery transaction**: sender, recipient, tx hash, LT/block, timestamp;
3. whether that recipient equals the snapshotted buyer wallet;
4. the current owner at dispute time;
5. collection resolution at both moments;
6. source(s) and observation times.

| Evidence shows | Outcome |
|---|---|
| recipient = buyer wallet, then buyer moved it | delivery stands; buyer's claim fails |
| recipient ≠ buyer wallet, never delivered | seller-side failure; refund path |
| no delivery transaction found, indexers unavailable | **evidence pending** — no automatic decision |
| item contract not found | evidence pending + manual review |

**[AUDIT F-16 accepted]** Chain evidence answers *whether the token moved*, not *whether it was as described*. The policy therefore separates five distinct claim types and does not let a 72-hour window waive statutory rights:

| Claim type | Adjudicated by |
|---|---|
| Non-delivery | chain evidence (§8.4) |
| Wrong contract / wrong collection | chain evidence + order snapshot |
| Misdescription, authenticity, rights | human review, order record, seller terms |
| Chargeback (fiat phases) | provider process + evidence pack |
| Statutory consumer remedy | **legal policy, set by counsel [OPEN]** |

---

## 9. Blockers — real paid trades are NO-GO until all critical ones clear

| # | Blocker | Critical? | Owner |
|---|---|---|---|
| **B1** | Is P2P TON NFT resale a "digital good" under Apple/Google rules, as Telegram defers to them? **[V]** §2.1 | **Yes** — determines whether Stars is mandatory and whether any external rail is usable | Owner + counsel |
| **B2** | Does operator-controlled payout release make VILTARA a payment service? **[V]** ZAG §2(1)(9) vs §1(1)(6) | **Yes** — determines whether the business needs a licence | Payments counsel |
| **B3** | Seller settlement rail: P0/P1/P2 chosen, funded, and documented (§5.3) | **Yes** | Owner |
| **B4** | Funded, segregated, disclosed remedy source (§5.2) | **Yes** — without it the launch claim is "refund only, no protection" | Owner |
| **B5** | Legal entity, jurisdictions, KYC/AML/sanctions, tax scope | **Yes** | Owner + counsel |
| **B6** | Escrow contract design, audit, key governance, **and** the §8.3 validation model | Production only | Engineering + auditor |
| **B7** | Written PSP underwriting for secondary NFT sales with delayed payout | Production only | Owner |
| **B8** | One Telegram ingress chosen and enforced (webhook vs polling) | Implementation | Engineering |
| **B9** | Merchant-of-record classification separated from Telegram's "purveyor" duty **[AUDIT F-14]** | Yes | Counsel |

**[R] Current status: NO-GO for real paid trades.** Catalog, verification, reservation, notifications, view-only TON-priced catalog, and the schema-only MVP may proceed.

---

## 10. Delivery plan

### 10.1 MVP — non-financial, shippable now

- Existing order lifecycle + PR #34's ownership observation.
- Schema only: `payment_intents`, `payment_transactions`, `stars_refunds`, `compensation_entries`, `seller_payouts`, `disputes`, `command_outbox`, `webhook_inbox`.
- Fake payment adapter and fake chain observer; the full §6.2 machine exercised by fixtures, **including** `unknown` and `returned`.
- Reconciliation and expiry workers with `SKIP LOCKED`.
- Product copy states exactly what §4.1 permits.
- **Exit:** every transition, including every forbidden one, has a test; no test requires a real provider.

### 10.2 Next — Stars, gated on B1–B5

- Live Stars invoice and Rail S refund for an offering counsel has classified.
- Buyer-wallet snapshot; §8.2 L1 evidence; delivery-confirmed-but-unsettled review window; dual-control payouts via the chosen B3 rail.
- **Exit:** one full deal on Telegram's Stars **test environment**, then a capped pilot with a disclosed cap.

### 10.3 Production — PSP + escrow, gated on B2, B3, B6, B7

- Separate web surface, licensed PSP, seller onboarding and KYC.
- Escrow contract with deposit-first ordering, §8.3 validation, bounded inspection, traced release, audited, multisig with timelock.
- L2 evidence for high-value orders.
- **Exit:** signed provider contract, independent audit, incident drill, reconciliation proven on a live pilot.

---

## 11. Source ledger

| Source | Access | Mark | Used for |
|---|---|---|---|
| `telegram.org/tos/bot-developers` §6.2–6.2.4.1 | Archive 2026-10-26 | **[V]** archival | Stars mandate, purveyor duty, irreversibility warning, balance ownership, rewards |
| `core.telegram.org/bots/payments-stars` | Archive 2026-11-06 | **[V]** archival | XTR, invoice flow, `telegram_payment_charge_id`, `refundStarPayment`, `/paysupport` |
| `core.telegram.org/bots/api` | Archive 2026 snapshot | **[V]** archival | `refundStarPayment` signature (no amount), `getUpdates`/webhook exclusivity, `secret_token` header, `pre_checkout_query` |
| TEP-62 | Live 2026-11-11 | **[V]** | no safe transfer, owner-only transfer, `ownership_assigned`, `get_nft_data` |
| `docs.ton.org/.../nft/how-it-works` | Live 2026-11-11 | **[V]** | collection cross-check requirement |
| `docs.ton.org/ecosystem/ton-connect/overview` | Live 2026-11-11 | **[V]** | keys never shared; Stars rule restated |
| `stripe.com/legal/restricted-businesses` | Live 2026-11-11 | **[V]** | "Secondary NFT sales" under **Prohibited Businesses** |
| `gesetze-im-internet.de/zag_2018/__1.html`, `__2.html` | Live 2026-11-11 | **[V]** | §1(1)(6), §2(1)(2), §2(1)(9) |
| `docs.adyen.com/platforms/` | Live 2026-11-11 | **[A]** | capabilities only; no NFT acceptance found |
| Adyen transfer lifecycle | **not reachable** | **[A]** | payout-status model taken from the audit, unverified here |
| EUR-Lex (MiCA, CRD) | Empty response | **[A]** | **not relied upon** |
| Repository at `8ab3501` + PR #34 | Local | **[V]** | lifecycle, constraints, polling bot, indexer-based verifier |

---

## 12. Disposition of all 18 audit findings

Verdicts: **Fixed** — changed in this document. **Rejected** — the finding is factually wrong, with reasoning. **Blocker** — accepted and deliberately left open as a gated condition.

| # | Severity | Finding (abridged) | Verdict | Where / why |
|---|---|---|---|---|
| **F-01** | Critical | MVP does not lock the NFT; "asset lock" is misleading | **Fixed** | §4.1 terminology table; §4.2 states MVP has no asset lock and does not satisfy the ordering rule; §6.4 row "NFT lock (MVP) = none" |
| **F-02** | Critical | Stars give no per-seller settlement; ledger ≠ collateral | **Fixed** | §5.1 three rails; §5.3 forces P0/P1/P2 choice; "seller_ledger is an obligation, never a balance" |
| **F-03** | Critical | Stars refund and fiat compensation are separate flows | **Fixed** | §5.1 Rail S vs Rail C; **[V]** `refundStarPayment` has no amount parameter; states `stars_refund_pending/_refunded/_unknown` |
| **F-04** | Critical | Delivery, dispute window, payout eligibility conflated | **Fixed** | §6.2 splits `delivery_confirmed_unsettled`, `disputed`, `settlement_eligible`, `payout_*`; `settlement_eligible` is reversible |
| **F-05** | Critical | A DB lock cannot serialise an external refund against a chain transfer | **Fixed** | §4.3 saga with `requested/unknown/confirmed`; §7.5 states a row lock is not a cross-system mutex; compensation rule if both land |
| **F-06** | High | Unique charge IDs don't prevent distinct or late charges | **Fixed** | §7.1: one accepted payment per order (partial unique index), payer/payload/XTR/total binding, 10s pre-checkout, late payment never resurrects the order |
| **F-07** | High | Unique payout rows don't guarantee one external payout | **Fixed** | §7.3 idempotency key persisted before submission, full lifecycle, unknown reconciled before retry |
| **F-08** | High | Telegram ingress conflicts with existing polling bot | **Fixed** | §7.4; **[V]** `getUpdates` blocked when a webhook is set; repo does poll (`bot.py`); one ingress enforced, `update_id` dedupe |
| **F-09** | Critical (for #35) | TEP-62 transfer direction described incorrectly in PR #35 | **Fixed** | §8.1 — seller initiates; **[V]** owner-only rejection rule. PR #35 itself is untouched, as instructed |
| **F-10** | High | Current owner ≠ historical delivery; third-party owner ≠ fraud | **Fixed** | §8.4 delivery transaction, recipient vs snapshot, "evidence pending" instead of auto-deciding |
| **F-11** | Critical (production) | A TON contract cannot call arbitrary NFT/collection get-methods | **Fixed** | §8.3 three-layer model; **[V]** get-methods are off-chain; owner must pick allowlist / attestation / hybrid |
| **F-12** | High | TON Center v3 is not a cryptographic proof | **Fixed** | §8.2 evidence levels L0–L3 with explicit vocabulary and metadata persistence |
| **F-13** | High | External-checkout rule over-categorical in one place, unresolved in another | **Fixed** | §3.2 — categorical claim removed; narrow transaction-level prohibition kept; link policy left **OPEN** |
| **F-14** | Medium | "Purveyor" ≠ merchant of record | **Fixed** | §3.3 separates contractual duty from MoR; B9 added; v1 conflation removed |
| **F-15** | High (production) | PSP "booked" payout may later be returned | **Fixed** | §5.4 terminal states; `returned` reopens the payable; `payout_paid → payout_pending` transition #11 |
| **F-16** | High | 72-hour chain observation is not a consumer policy | **Fixed** | §8.4 five separated claim types; statutory rights explicitly not waivable |
| **F-17** | High (production) | Deposit-first needs a full async failure model | **Blocker** | §8.3 validation model + §4.3 command model define the shape, but orphan deposits, bounce recovery, pause/rescue authority and key-loss drills require contract work and audit. Deliberately gated under B6 |
| **F-18** | High | Idempotency must cover commands and reconciliation, not just events | **Fixed** | §7.1/§7.3/§7.4 plus `command_outbox` in §6.1; per-effect unique keys listed |

**Summary: 16 fixed, 0 rejected, 1 left as a gated blocker (F-17), 1 (F-16's statutory part) fixed structurally with the legal policy itself still OPEN.**

**One finding I record but cannot fully adjudicate:** F-11's "Critical for production" severity depends on whether the contract must re-derive collection membership. My §8.3 answer is that it must not attempt it, and that the trust model moves to an allowlist or an attestation the owner must approve. If the owner requires the contract to be authoritative about collections, the finding becomes unimplementable rather than merely open, and production escrow must be dropped.

---

## 13. What this ADR does not decide

- It does not choose between Stars-only and an external PSP rail. That depends on B1.
- It does not approve any escrow contract, custody model, collection-validation option, or admin-key design.
- It does not approve a fee schedule, a remedy cap, or a reserve percentage.
- It does not assert the audit's provider specifics (Adyen transfer lifecycle) are verified — they are **[A]** here.
- It does not change PR #35, #36 or #38, and does not touch `main`.
- It does not supersede ADR-0001. If approved, it would.

---

## 14. Decisions required from the project owner

### 14.1 Product and risk

1. **Merchant of record:** is VILTARA willing to carry TPA delivery and dispute duties (§2.1)? (Distinct from legal MoR status, B9.)
2. **Maximum loss per order** the business will fund — sets the remedy cap and therefore the honest claim.
3. **Is the remedy fund real money** — segregated, audited, disclosed — or is the launch "refund only, no protection"?
4. **Type of first release:** (a) no-money coordination only, (b) Stars with sales disabled until B3/B4 are real, (c) independently underwritten PSP flow. *The audit recommends (a) or (b); I concur.*
5. **Seller settlement path:** P0, P1 or P2 (§5.3).

### 14.2 Legal and platform

6. Approve counsel for B1, B2, B5, B9, using §2.4 as the brief.
7. Fix the legal entity, jurisdiction, and buyer/seller countries.
8. Approve written outreach to Telegram on classification and on whether any external surface may be promoted or linked.
9. Approve written underwriting requests to at least two PSPs for **secondary NFT sales with delayed payout**.
10. Decide the seller policy (professional / consumer / both) and the consumer-claim policy behind §8.4.

### 14.3 Engineering

11. Approve the schema-only MVP as the next milestone.
12. Approve **one** ingress (webhook recommended) and the rollout from polling.
13. Approve the dispute default: **evidence pending, never auto-decide** (§7.6).
14. Choose the escrow collection-validation model **A, B or C** (§8.3), and if B, the signer quorum and rotation policy.
15. Approve the evidence level required by value threshold (L1 vs L2) and the second-source provider.

### 14.4 Still without an owner

16. Who adjudicates disputes, with what deadline, and is there an appeal?
17. What happens to pending deals if the Telegram account is frozen, the bot is limited, or Fragment becomes unavailable? **[V]** all three are enumerated risks.
18. Recovery plan if the escrow admin key is lost, or the contract must be paused while holding assets?
19. On provider insolvency, who owns a seller's booked-but-unpaid balance?
20. Does any VILTARA collection fall back into MiCA scope? **[A]** unverified here.
21. Which statutory consumer remedies apply after an irreversible transfer, and can any be waived lawfully?

---

## 15. Recommendation

**[R]** Accept this revision as ADR-0002 with status **Proposed**, and keep **NO-GO for real paid trades**.

Order of work:

1. Ship the schema-only MVP — honest, useful, and independent of every legal answer.
2. Resolve **B1** first; it is the only question that can invalidate both payment rails at once.
3. Answer **B4** and **B3** before a single line of payment code. Collecting money without a settlement rail and a funded remedy is exactly the model Telegram's own terms discourage.
4. Treat the escrow contract, and with it the collection-validation model of §8.3, as production work — never as MVP's safety net.

The sentence to keep in view: **we can bound the buyer's money risk, or we can lock the asset, but not both cheaply — and MVP buys only the first, which is why it must not claim the second.**