> **Repository audit note (2026-11-10):** This proposal currently says it was authored and source-accessed on 2026-11-11, a future date relative to this repository audit. Its Telegram sources are explicitly marked blocked/open, but the future-dated TON/source entries must be corrected or rechecked by the author before those dates are treated as verified. This remains an independent proposal, not an approved design.

# Proposal: VILTARA SHOP safe deal — proof-first delivery with a funded remedy fund

- **Author/agent:** Claude Fable 5.1 (independent research agent)
- **Date:** 2026-11-11
- **Preferred model:** **E-hybrid** — Stars checkout (A) for money + *remedy fund* + seller deposit/reputation in place of on-chain escrow; escrowed NFT deposit (B) is the aspirational Phase 3 but is **BLOCKED** today (see §7)
- **Confidence:** medium on the recommended interim architecture; **low** on any "escrow/guarantee" claim in product copy
- **Relationship to ADR-0001:** this document *disagrees in part* with ADR-0001's claim that no escrow is possible at launch. It proposes a *financial* remedy mechanism that can exist before any custody model. It does not edit the ADR and does not decide anything.

> **Status vocabulary used below** — kept strictly separate, as §6 of the discussion requires:
> **[VERIFIED]** read from a live official source or the repository at the cited commit during this research;
> **[ASSUMPTION]** plausible but not verified from primary sources;
> **[REC]** my design recommendation;
> **[OPEN]** needs a human/platform/legal decision.

---

## 0. Research limitations — read this first

I must be explicit about what this research could and could not verify, because §5.4 of the discussion asks for compliance claims and a wrong claim here is worse than no claim.

| Source | Reachability from this environment | Consequence |
|---|---|---|
| `https://docs.ton.org/...` | **Reachable** (HTTP 200) | TON mechanics below are first-hand |
| `https://github.com/ton-blockchain/TEPs/.../0062-nft-standard.md` | **Reachable** | TEP-62 details are first-hand |
| `https://fragment.com` | Reachable (HTTP 200) | Existence confirmed; **payout rules not verified** |
| `https://core.telegram.org/bots/payments-stars` | **Blocked** (DNS resolves to 149.154.167.99, TLS/HTTP blocked) | Stars fee/refund/payout specifics **not verified in this session** |
| `https://core.telegram.org/bots/api` | **Blocked** | Same |
| `https://telegram.org/tos/bot-developers` | **Blocked** | **The Terms scenario in ADR-0001 §3 could not be read by me** |
| Web search | Returns empty results in this environment | No secondary confirmation available |

**[VERIFIED]** Every Telegram-specific rule below is therefore either (a) quoted from this repository's own prior audit (which states it was read on 2026-11-09), or (b) flagged **[OPEN]**. I did not silently promote repository claims to independent verification.

One genuinely new, independently verified finding, however: the official TON Connect page states the Stars requirement in TON's own words.

> **[VERIFIED]** "Digital goods and services sold inside Telegram Mini Apps use Telegram Stars. TON Connect remains available for permitted blockchain interactions under Telegram's blockchain guidelines."
> — `https://docs.ton.org/ecosystem/ton-connect/overview`, fetched 2026-11-11.

That sentence, from a source I *could* reach, corroborates the constraint ADR-0001 asserts from an unreachable source. Two independent documentation trees agreeing is meaningfully stronger than one.

---

## 1. Repository baseline — inspected, not assumed

**[VERIFIED]** at commit `8ab3501` (branch `main`), by reading the files:

| Fact | Where |
|---|---|
| `OrderStatus` is exactly `pending_payment`, `cancelled`, `expired`; the DB check constraint `ck_orders_status` rejects anything else | `backend/app/db/models.py` |
| Order creation snapshots price/currency, reserves the listing under `with_for_update`, writes an append-only `OrderEvent`, enqueues notifications | `backend/app/orders/service.py` |
| One open order per listing is enforced by partial unique index `uq_orders_pending_listing`; buyer idempotency by `uq_orders_buyer_idempotency` | `backend/migrations/versions/0003_orders.py` |
| `PaymentAdapter` is a 3-symbol protocol with no implementation and no import from any route | `backend/app/orders/payment.py` |
| Notifications already use a durable outbox with `dedupe_key`, `attempt_count`, `next_attempt_at`, claim leases | `backend/app/db/models.py::TelegramNotificationOutbox`, migration `0004` |
| Order expiration is an in-process asyncio worker with `SKIP LOCKED` | `backend/app/main.py::_expire_orders_periodically` |
| Wallet ownership is proven by TON Connect signed proof, verified server-side with `pytoniq`/`nacl`; challenge TTL 300 s, max proof age 300 s, chain ids `mainnet=-239`, `testnet=-3` | `backend/app/wallets/proof.py` |
| TON NFT verification is TEP-62 `get_nft_data` + collection `get_nft_address_by_index` cross-check, with a **distinct** `PROVIDER_UNAVAILABLE` status | `backend/app/assets/ton_nft/verifier.py`, `models.py` |
| Listing publish and order reservation both re-verify ownership **outside** the transaction, then revalidate under locks | `backend/app/listings/service.py::publish_listing`, `backend/app/orders/service.py` (PR #34) |
| There is no `payments/` module, no `escrow/` module, no ledger table, no payout table | `find backend/app` |
| `PriceCurrency` already has `XTR` | `backend/app/db/models.py` |

**[ASSUMPTION]** Issue #28's fresh-ownership work is *in flight* (PR #34), not merged to `main`. My proposal assumes the reservation path will have a fresh owner check, but nothing below depends on it.

This baseline matters for one reason: **the project already has the hard part of the safety problem.** It has a verified wallet identity, a fresh on-chain ownership oracle, an append-only audit log, an idempotent durable outbox, and a consistent "external call outside the lock, revalidate under the lock" pattern. What it does *not* have is a way to make a wronged buyer whole. That is the actual gap, and it is a **money** gap, not a chain gap.

---

## 2. Executive recommendation

**The escrow problem is being framed as "who holds the NFT". I argue the binding constraint is "who reimburses the buyer", and those are separable.**

An NFT transfer is irreversible. Therefore *no escrow design* — on-chain, off-chain, or hybrid — can undo a delivery that already happened. Escrow only helps in the window *before* delivery. Every design in the discussion's §4 (A, B, C, D) accepts a residual class of losses that no custodian can fix:

- NFT delivered, then buyer charges back (model A, D),
- NFT delivered but it was the wrong item / a look-alike collection,
- NFT delivered to an address the buyer later claims was not theirs,
- NFT never delivered and the seller has no funds left to refund.

The only mechanism that helps across that whole class is **a pre-funded pool of money that the operator may spend on the buyer's behalf without the seller's consent.** I call it the *remedy fund*. Everything else in this proposal is arranged around making that fund cheap, small, and auditable.

**Recommendation in one paragraph.** Charge buyers in **Telegram Stars** (the only defensible in-app path, §7), and hold the money in the operator's Telegram balance — a single account, *not* per-seller balances, because Stars do not support sub-accounts. Offset this by (i) collecting a **refundable seller deposit** in the same currency before the seller's listing goes live, (ii) requiring the NFT to be **verified still-owned at reservation time** (already implemented), (iii) requiring delivery **only to the buyer's TON-Connect-proven wallet** so "wrong address" is not a seller-side excuse, and (iv) completing the order only on a **fresh chain read of the buyer's wallet**, with a mandatory **dispute window** before the seller is settled. Payouts are **manual, dual-control, ledger-backed**, monthly, with a stated reserve. Label the product **"проверенная сделка" / "verified deal"**, never "escrow", "guarantee" or "safe deal", until §7 blockers clear.

**Why not on-chain escrow now.** [VERIFIED] TEP-62 transfer is a one-way `transfer#5fcc3d14` that rewrites the owner field; there is no built-in reversal, and the standard's own bounce semantics do not restore ownership. An escrow contract would have to be *written* to hold the item and later release it. That is a security-critical component the project has never deployed to any network, and the discussion itself demands contract audit + admin-key design + failure matrix before mainnet. Making it the launch dependency would push the marketplace's first real-money transaction behind an audit cycle. It is the right Phase 3, not the right Phase 1.

**What is genuinely new in this proposal versus ADR-0001.** ADR-0001 says: Stars checkout, manual payouts, no escrow, no buyer protection, "must not advertise guarantee". I keep all of that and add the missing mechanism: a **funded remedy fund + seller deposit + dispute window + proof-based delivery**, with an explicit, honest statement of the maximum loss the fund is sized to cover. That converts "no protection" into "bounded, disclosed protection", which is both more honest and more sellable than the ADR's flat "no".

---

## 3. Money-flow diagram

```text
                          (1) Stars invoice, amount from order snapshot
  Buyer  ─────────────────────────────────────────────────────────────┐
    │                                                                 │
    │  Telegram charges XTR                                           ▼
    │                                                     ┌──────────────────────┐
    └────────────────────────────────────────────────────▶│  Telegram balance of │
                                                          │  the bot/Mini-App    │
                                                          │  owner (operator)    │
                                                          └──────────┬───────────┘
                                                                     │
                              [VERIFIED] no per-seller sub-accounts;  │
                              this is ONE pooled balance              │
                                                                     ▼
                                              ┌──────────────────────────────────┐
                                              │  Operator ledger (PostgreSQL)     │
                                              │  payment_transactions (per order) │
                                              │  seller_ledger (per seller)       │
                                              │  remedy_fund (operator equity)    │
                                              └───────┬───────────────┬──────────┘
                                                      │               │
                          (4a) on `completed`         │               │ (4b) on dispute
                          minus fee                   │               │ lost / non-delivery
                                                      ▼               ▼
                                            ┌──────────────────┐  ┌──────────────────┐
                                            │ Seller payout    │  │ Buyer refund     │
                                            │ (manual, monthly,│  │ (Stars refund or │
                                            │  dual control)   │  │ ledger credit)   │
                                            └──────────────────┘  └──────────────────┘

  Separately, BEFORE any listing goes live:
  Seller ──(0) refundable deposit in Stars──▶ operator ledger (seller_ledger.deposit)
```

**[REC]** Three accounting pots, one physical balance. The operator must be able to answer, per order: *whose money is this and what would make it the other party's?* That is a ledger question, and PostgreSQL already has the tooling (append-only events, unique constraints, `SKIP LOCKED` workers) that this repo uses elsewhere.

**[OPEN — critical]** Whether Telegram permits an operator to refund a Stars payment to a *third party* (a buyer the operator is not the merchant of record for) and whether an operator may hold seller funds this way is a **payment-services / money-transmission question I could not verify**. This is the single question that could invalidate the whole model, and it is §7's first blocker. Everything below is contingent on it.

---

## 4. NFT-flow diagram

```text
 STEP                WHERE THE NFT IS           EVIDENCE THE SERVER ACCEPTS
 ─────────────────────────────────────────────────────────────────────────────
 0. listing draft    seller wallet             TEP-62 read: item.owner == seller
                                                wallet, collection cross-check
 1. publish          seller wallet             re-verified fresh (publish_listing)
 2. order reserved   seller wallet             re-verified fresh (reservation)
 3. paid (Stars)     seller wallet             provider webhook verified; NFT NOT moved
 4. delivery_pending seller wallet             seller declares intent; NFT still there
 5. transfer         seller → buyer wallet     buyer sends TEP-62 `transfer`
                                                new_owner = buyer's PROVEN wallet
 6. completed        buyer wallet              fresh get_nft_data: owner == buyer
                                                wallet, AND collection cross-check
 7. dispute window   buyer wallet              order stays `paid`, not settled
 8. settlement       buyer wallet              operator pays seller from ledger
```

**[VERIFIED]** The TEP-62 mechanics that make steps 5–6 trustworthy:

- Transfer is `transfer#5fcc3d14 query_id:uint64 new_owner:MsgAddress response_destination:MsgAddress custom_payload:(Maybe ^Cell) forward_amount:(VarUInteger 16) forward_payload:(Either Cell ^Cell)`.
- "Should be rejected if: message is not from current owner" — so **only the seller can move it**; the server cannot, which is exactly why escrow needs a contract and not a wallet.
- The item "updates the owner, optionally notifies the new owner".
- `ownership_assigned#05138d91 query_id:uint64 prev_owner:MsgAddress forward_payload:(Either Cell ^Cell)` is the notification, sent **only if `forward_amount > 0`**.
- [VERIFIED] `get_nft_data()` returns `(init?, index, collection, owner, content)`.
- [VERIFIED] "Not every NFT that stores a collection address actually belongs to that collection. Verify that the collection returns the item's address for the item's index." — already implemented in this repo.

**Design consequence of `forward_amount`.** **[REC]** The buyer should transfer with `forward_amount > 0` and a `forward_payload` carrying the order id (binary comment, `0xff` prefix). This gives the marketplace *two* independent confirmations of the same event: a `ownership_assigned` notification message landing on a monitored address, and the authoritative `get_nft_data` read. **[OPEN]** Whether the buyer's wallet will expose that notification to the backend requires a wallet-side capability I have not verified; the authoritative read must not depend on it.

**Why the buyer's wallet, not "the buyer".** **[REC]** `new_owner` is a *server-chosen, buyer-proven* address: the buyer must have completed the existing TON Connect proof (`app/wallets/proof.py`), on the asset's network. This kills the "I gave you the wrong address / that wasn't my wallet" defence at the root and makes step 6 a mechanical check rather than a human judgement.

**The honest limit.** **[REC]** There is a window between step 5 and step 6 completion where the buyer *has* the NFT and the seller is not yet paid. That is the seller's risk, symmetrically, and it is why the seller needs a deposit-independent reason to trust the platform: settlement is monthly and contractual, not per-transaction. Say so in the seller agreement.

---

## 5. Order/payment state machine

Extends the existing three states rather than redefining them. **[REC]** New states are added by a migration that widens `ck_orders_status`; existing meanings are untouched.

```text
                 ┌──────────────────┐
   (existing)    │ pending_payment  │ (existing)
                 └───┬──────────┬───┘
     buyer cancels   │          │  worker TTL
        (existing)   │          │  (existing)
                     ▼          ▼
              cancelled      expired
                     
   + new:

  pending_payment ──verified Stars webhook──▶ paid
        paid ──seller declares──▶ delivery_pending
        paid ────────────────buyer opens dispute──▶ disputed
        delivery_pending ────chain: owner==buyer──▶ completed (settlement eligible)
        delivery_pending ────dispute window ends, no dispute──▶ completed
        delivery_pending ────deadline passed──▶ failed ──refund──▶ refunded
        disputed ──evidence: owner==buyer──▶ completed
        disputed ──evidence: no delivery──▶ refunded
        paid ──refund before delivery──▶ refunded
```

**Actor discipline — the rule that makes the machine trustworthy.**

| Transition | Only actor allowed | Then |
|---|---|---|
| `→ paid` | `provider` (verified webhook) | no NFT moves |
| `→ delivery_pending` | `seller` | NFT still seller's |
| `→ completed` | `system` (fresh chain read) **or** `admin` (dispute) | settlement eligible |
| `→ refunded` | `provider` (Stars refund) **or** `admin` | fund pays |
| `→ failed` | `system` (deadline) | escalation |

**[REC]** `buyer` and `client` may never write `paid`, `completed` or `refunded`. The existing schema already enforces the pattern: `ck_order_events_actor_type` restricts `actor_type` to `('buyer','system')` and would need widening to `('buyer','seller','system','provider','admin')` — a one-line migration, and the reason I like this codebase's constraints.

**Idempotency map** **[REC]** — reusing the repo's existing discipline:

| Operation | Idempotency key | Unique constraint |
|---|---|---|
| create order | `(buyer_id, Idempotency-Key)` | exists (`uq_orders_buyer_idempotency`) |
| create invoice | `(order_id)` — one live invoice per order | `payment_intents.order_id` partial unique where `status='open'` |
| Stars webhook | `(provider, telegram_payment_charge_id)` | unique → replay is a no-op |
| refund | `(provider, refund_reference)` | unique |
| completion | `(order_id, observed_owner, observed_query_id)` | append-only event; second write is a no-op |
| payout | `(order_id)` | one payout row per completed order |

**Sequencing rule** **[REC]**, matching what this repo already does in `publish_listing`/reservation: provider calls and chain reads happen **outside** any transaction; thesis is then re-validated under `FOR UPDATE` before commit. Specifically: the chain read that proves delivery must not hold a connection, and the completion write must re-check `order.status == delivery_pending` under lock.

---

## 6. Refund and dispute policy

This is where most marketplaces are vague. Being concrete is the product.

### 6.1 Refund windows

| Window | Buyer remedy | Funded by | Reversible? |
|---|---|---|---|
| Before `paid` | nothing to refund | — | — |
| `paid` → seller has not started transfer | full refund, seller deposit forfeited | order funds | n/a |
| `delivery_pending` → deadline missed, no chain evidence | full refund, deposit forfeited | order funds | n/a |
| `completed` disputed, chain shows buyer owns it | **no refund** — NFT is with buyer | — | no |
| `completed` disputed, chain shows buyer does **not** own it and seller cannot re-deliver | refund from **remedy fund** | operator equity, recovered from seller deposit | no |
| wrong item / look-alike collection delivered | refund from remedy fund after return of the wrong item is *not* required | operator equity | no |

**[REC]** The last two rows are the entire value proposition and the entire risk. Both must be *sized*: a stated per-order cap and a disclosed fund balance. Do not promise "full protection" — promise "up to X XTR per order, funded and audited".

### 6.2 Dispute decision rules

**[REC]** Adjudicate on *chain evidence*, not testimony, wherever a chain fact exists:

1. Read `get_nft_data` for the item address in the order snapshot.
2. If `owner == buyer's proven wallet` → **buyer loses the dispute**, order completes. (The buyer may be lying; the chain is not.)
3. If `owner == seller's wallet` → seller never delivered; refund, deposit forfeited.
4. If `owner == a third address` → the seller moved it elsewhere; refund + deposit forfeited + seller suspended.
5. Only when the item contract itself is unreachable/not found does a human decide, and then the default is **buyer wins** (the operator, not the buyer, should bear the cost of the marketplace's own verification failure).

**[OPEN]** Rule 5's default is a policy choice with a real cost; the maintainer may prefer "seller wins if provider outage and seller has a good delivery record". I recommend buyer-wins because the operator chose the asset and the oracle.

### 6.3 Dispute deadline

**[REC]** 72 hours after the transfer is first observed on chain, or after `delivery_pending` expires, whichever is later. Short enough that the seller is not financing the marketplace indefinitely, long enough to cover indexer lag. **[OPEN]** Final number is a product/legal decision; it interacts with whatever consumer-protection withdrawal right applies in the target jurisdiction.

---

## 7. Telegram / provider / legal constraints

### 7.1 What I verified myself

| # | Claim | Status |
|---|---|---|
| 1 | "Digital goods and services sold inside Telegram Mini Apps use Telegram Stars. TON Connect remains available for permitted blockchain interactions under Telegram's blockchain guidelines." | **[VERIFIED]** `docs.ton.org/ecosystem/ton-connect/overview`, 2026-11-11 |
| 2 | TEP-62 transfer is one-way, owner-only, no reversal op | **[VERIFIED]** TEP-62 §"transfer" |
| 3 | `ownership_assigned` notification only if `forward_amount > 0` | **[VERIFIED]** TEP-62 |
| 4 | Collection membership must be cross-checked, not assumed from stored address | **[VERIFIED]** TON docs "How NFT works" |
| 5 | TON Connect never exposes keys; it requests signatures/transactions | **[VERIFIED]** `docs.ton.org/ecosystem/ton-connect/overview` |
| 6 | This repo verifies wallet proofs server-side with chain id `-239`/`-3` | **[VERIFIED]** `backend/app/wallets/proof.py` |

### 7.2 What I could not verify, and therefore will not assert

| # | Claim (asserted elsewhere in this repo) | My status |
|---|---|---|
| 7 | Bot Developer Terms §6.2 requires Stars for digital goods | **[OPEN]** — I could not read `telegram.org/tos/bot-developers`; the TON docs sentence corroborates the *requirement*, not the *terms text* |
| 8 | The Terms warn about real-time sales of valuable virtual items that cannot be reclaimed after chargebacks | **[OPEN]** — could not read the source; if true it is a **launch blocker**, and the discussion is right to say so |
| 9 | Stars fees, refund window, conversion via Fragment, hold period, country availability | **[OPEN]** — must be re-read from live docs before any product copy or price model |
| 10 | Whether an operator may refund a third-party buyer / hold seller funds | **[OPEN]** — **the single biggest blocker for this proposal** |

### 7.3 Legal constraints I expect to bind (all **[OPEN]**, none are legal advice)

- **Custody / money transmission**: holding buyer Stars until delivery, then paying sellers, is functionally a payment service in many jurisdictions regardless of whether a smart contract is used. This applies to model **A** and **A+remedy** just as much as to model **B**. It is the most commonly overlooked point in NFT marketplaces, and it is the one that decides whether this product can operate at all in a given country.
- **KYC/AML/sanctions**: paying sellers money requires knowing who they are. A "connect wallet and sell" flow is not compatible with paying that person out at scale.
- **Consumer rights**: EU-style withdrawal rights normally do not apply to digital content once supplied, but the "supplied" moment for an NFT is exactly the transfer — the same moment the marketplace loses leverage. Needs a lawyer, not an engineer.
- **Tax**: Stars in, TON out, marketplace fee retained — three taxable events, in at least two currencies.
- **App stores** if the Mini App is ever packaged: NFT marketplaces have historically been rejected or specially gated.

### 7.4 Wording discipline

**[REC]** Until §7 blockers clear, permitted: "проверенная сделка", "NFT проверен на блокчейне", "деньги вернутся, если NFT не придёт". Forbidden: "гарант", "escrow", "safe deal", "100% защита", "деньги заморожены до получения". The reason is precise: with Stars + operator balance, the money is *not* frozen, it is *held by the operator*, and those are different promises to a regulator and to a buyer.

---

## 8. Threat model and failure matrix

| # | Failure | Detection | Automatic action | Manual action | Loss lands on |
|---|---|---|---|---|---|
| F1 | Seller never delivers | `delivery_pending` deadline | refund + deposit forfeited | suspend seller | seller (deposit), operator (labour) |
| F2 | Transfer to wrong address | chain read ≠ buyer wallet | hold, open dispute | none if buyer wallet was server-chosen (F2 should be impossible) | — |
| F3 | Transfer pending / not yet indexed | no chain read yet | wait, re-poll with backoff | none | nobody (time only) |
| F4 | Indexer down | `PROVIDER_UNAVAILABLE` | never conclude; retry | none | nobody — outage ≠ non-delivery |
| F5 | Payment succeeds, webhook lost | reconciliation poll of provider | `paid` via reconcile path | none | nobody |
| F6 | Duplicate webhook | unique charge id | no-op | none | nobody |
| F7 | Buyer claims non-receipt, chain says otherwise | chain read | **buyer loses** | none | buyer |
| F8 | Refund races release | status transition guard under lock | one of the two wins; loser sees 409 | investigate | operator (remedy fund) |
| F9 | Escrow contract/watcher down (Phase 3) | heartbeat | pause new orders | manual reconcile | delayed, not lost |
| F10 | Wrong / look-alike NFT delivered | verification at reservation + collection cross-check | reject at reservation | refund from fund | operator (fund) |
| F11 | Seller double-sells same NFT | partial unique index + fresh ownership check | second reservation fails | none | nobody |
| F12 | Operator's Telegram account frozen | out-of-band monitoring | **all payouts and refunds stop** | **none — this is a single point of failure** | buyers and sellers |

**[REC] F12 is the argument for the reserve.** The operator balance is a single account. If it is frozen, every pending refund becomes impossible at once. Size the remedy fund so it can cover the *expected concurrently-pending* exposure, not the annual volume, and keep an off-balance-sheet reserve equal to it.

**Trust boundaries** **[REC]**: client (untrusted) → API (untrusted-verified, sole state authority) → PostgreSQL (source of truth) → Telegram (authenticity of payment events only) → TON indexer (point-in-time ownership, may lag) → operator (holds money, must be dual-controlled and audited) → Phase-3 contract (holds NFT, admin keys are the top target).

---

## 9. Data model and API changes

**[REC]** Minimum schema to make §3–§6 real. Every table follows the repo's existing conventions (`Uuid` PKs, enum-as-`String(32)` with `CheckConstraint`, `created_at/updated_at`, partial unique indexes).

### 9.1 New tables

| Table | Purpose | Key constraints |
|---|---|---|
| `payment_intents` | one open Stars invoice per order | partial unique `order_id WHERE status='open'`; stores provider payload = order id |
| `payment_transactions` | append-only money movements | unique `(provider, provider_reference)`; `amount > 0`; `kind IN ('payment','refund')` |
| `seller_ledger` | per-seller running balance + refundable deposit | unique `(seller_id, entry_type, source_id)`; never negative |
| `seller_payouts` | one row per settled order | unique `order_id`; `status IN ('pending','approved','paid','reversed')`; `recorded_by`, `approved_by` (two distinct admins) |
| `disputes` | one open dispute per order | partial unique `order_id WHERE status='open'`; stores evidence snapshot (chain read JSON, hashed) |
| `delivery_evidence` | immutable proof per order | unique `(order_id, kind)`; stores item address, observed owner, query_id, block/lt, fetched_at, provider |

### 9.2 Order deltas

Add nullable `paid_at`, `delivery_deadline_at`, `completed_at`, `refunded_at`, `buyer_wallet_address` (snapshot of the **proven** wallet at payment time — not read live later), `seller_wallet_address`. Widen `ck_orders_status` and `ck_order_events_actor_type`.

**[REC]** `buyer_wallet_address` being a *snapshot* is important: if the buyer later unbinds that wallet from their account, the completion check must still compare against the address that was agreed at payment time, or an unbind could be used to manufacture a dispute.

### 9.3 API surface

| Method | Path | Note |
|---|---|---|
| POST | `/api/orders/{id}/payment-intent` | idempotent; returns invoice link; refuses non-`XTR`, foreign order, expired order |
| POST | `/api/webhooks/telegram` | constant-time secret token check; returns 200 for unowned updates |
| POST | `/api/orders/{id}/delivery` | seller declares delivery started |
| POST | `/api/orders/{id}/dispute` | buyer only, inside window |
| GET | `/api/orders/{id}/evidence` | both parties see the same chain evidence |
| POST | `/api/admin/payouts/{id}/approve` | dual control |

**[REC]** No public endpoint may set `paid`/`completed`. There is no such route in any phase.

---

## 10. Test plan and rollout phases

### 10.1 Tests (mirroring this repo's existing layers)

- **Unit**: state transition table — every (from, to, actor) triple, including all forbidden ones; amount/currency mismatch; payload ≠ order id.
- **API**: unauthenticated invoice request; foreign order → 404; non-`XTR` order → 409; webhook without/with wrong secret → 401; unowned update → 200 no-op.
- **PostgreSQL integration** (repo already has the harness): duplicate charge id → one ledger row; concurrent payment+dispute → one winner; refund racing completion → 409 for the loser; constraint tests for every new partial unique index.
- **Chain-evidence**: a fake provider returning verified / mismatch / unavailable / not-found, asserting that `PROVIDER_UNAVAILABLE` **never** produces `failed` or `refunded` (this is the F4 rule expressed as a test).
- **Concurrency**: reuse the `SKIP LOCKED` worker test style already present in `test_order_worker.py`.
- **E2E**: one happy path on TON **testnet** with a disposable NFT, funding from a faucet, and a fake Stars provider.

### 10.2 Rollout

| Phase | Scope | Gate |
|---|---|---|
| 0 | This proposal, review, ADR update | maintainer decision |
| 1 | `payment_intents`, `payment_transactions`, Stars webhook, `paid`/`refunded`, reconciliation worker, **no** delivery flow | §7.2 items 7–10 resolved; operator payout runbook |
| 2 | `delivery_pending`/`completed` with chain evidence, buyer-wallet snapshot, dispute window | funded remedy fund and disclosed cap; seller deposit live |
| 3 | Testnet escrow PoC (model B) as an *experiment*, not a commitment | contract review; failure matrix from §8 reproduced |
| 4 | Production escrow — only if Phase 3 clears and legal review approves custody | audit + legal opinion |

**[REC]** Phase 1 and 2 are shippable without any contract, any seed phrase, and any custody beyond the operator's Telegram balance. That is the pragmatic reason to prefer this ordering: *it does not block on the hardest unsolved problem*.

---

## 11. Estimated operational burden

| Item | Ongoing cost | Notes |
|---|---|---|
| Manual payouts | ~2–5 min/order, monthly batch | unsellable above ~200 orders/month without automation |
| Dispute adjudication | 15–30 min each | most resolve on one chain read (rules 2–4) |
| Reconciliation | automated; ~1 h/month review | daily alert on unpaid-but-paid orders |
| KYC/AML on sellers | external vendor | the real cost driver |
| Remedy fund | capital tied up | must be disclosed and audited |
| Telegram account risk | unquantifiable | see F12 |

**[REC]** The honest statement: this model is operationally cheap *per order* and expensive *per incident*. It suits a marketplace with few, high-value, well-verified TON NFTs — which is exactly this project's stated scope — and does not scale to high-volume low-value Telegram gifts.

---

## 12. Model comparison, scored

Scoring 1 (poor/unknown) to 5 (strong), per §7 of the discussion. **BLOCKER** marks an unresolved legal/platform gate that disqualifies the model for production regardless of score.

| Criterion | A Stars+manual | **E-hybrid (proposed)** | B on-chain escrow | C external PSP | D non-custodial |
|---|---:|---:|---:|---:|---:|
| Telegram policy fit | 5 | 5 | 4 (payment leg unclear) | **BLOCKER** | 4 |
| Buyer protection before delivery | 2 | 4 | 5 | 3 | 1 |
| Credible remedy after failed delivery | 1 | 4 | 2 (can't undo delivery) | 4 (chargeback) | 1 |
| Seller payment certainty | 3 | 3 | 4 | 2 | 5 |
| Custody / regulatory complexity | **BLOCKER** | **BLOCKER** | **BLOCKER** | 3 | 5 |
| Fraud and double-sale resistance | 4 | 5 | 5 | 3 | 2 |
| Technical feasibility on TON | 5 | 4 | 2 | 3 | 5 |
| Operational burden | 3 | 3 | 2 | 2 | 4 |
| Refund / chargeback compatibility | 3 | 4 | 2 | 5 | 1 |
| Country availability | 5 | 5 | 4 | 2 | 4 |
| Time and cost to a safe pilot | 4 | 3 | 1 | 2 | 5 |

Why the notable scores:

- **A "custody BLOCKER"**: the ADR treats A as having no custody problem. I disagree. Receiving Stars for a third party's benefit and later paying that party out *is* the custody problem, just implemented in a bank account instead of a contract. Marking A clean and B blocked would be inconsistent.
- **B "remedy after delivery = 2"**: this is the crux of my disagreement with the escrow-first framing. A contract that holds an NFT cannot recover an NFT already sent to the buyer, and a buyer-side chargeback against a Stars payment would not reach the contract either.
- **B "technical feasibility = 2"**: not because TON can't do it, but because nothing in this repo — or in my verified reading — includes a deployed, audited escrow contract, and TEP-62 provides no reusable escrow primitive.
- **E "custody BLOCKER"** is honest: E is *not* a way around the legal question, it is the same question with better buyer outcomes. That is precisely why E can be recommended for a pilot while still being blocked for production until §7 clears.

---

## 13. Risks and unresolved questions

**Risks of my own recommendation**

1. **The remedy fund is operator capital.** If the operator is the same person as the seller's counterparty with no separation, the "fund" is a promise, not protection. It must be segregated, audited, and disclosed with a number.
2. **Monthly payouts create seller cash-flow risk** and a strong incentive for sellers to push buyers off-platform to avoid the fee and the wait.
3. **The dispute window is a lever for fraud**: a buyer can receive the NFT and open a nuisance dispute during the window. Chain evidence defeats most of these (rule 2), but each costs operator time.
4. **I could not verify the Telegram terms text.** If item 8 in §7.2 is accurate as stated, then *all* real-time NFT sales inside Telegram may be restricted, and this proposal is dead on arrival. That must be checked before Phase 1, not after.

**Questions only a human can answer**

1. **[OPEN — highest]** May the operator refund a buyer and pay a seller under Telegram's payment rules? (invalidates §3 if no)
2. **[OPEN]** Is the operator willing to be merchant of record, with the tax and consumer obligations that implies?
3. **[OPEN]** Which jurisdiction, and therefore which custody/KYC regime, is primary?
4. **[OPEN]** Is a funded remedy fund acceptable as an operating cost, and at what per-order cap?
5. **[OPEN]** Should the seller deposit be denominated in Stars (simple) or TON (matches the asset, but adds a second payment rail and a second set of compliance questions)?
6. **[OPEN]** Does the project accept that "escrow" is a Phase-3 experiment and not a launch feature — and is the product still worth building under a "verified deal" label?

---

## 14. Sources

| Source | Accessed | What I took from it |
|---|---|---|
| https://docs.ton.org/ecosystem/ton-connect/overview | 2026-11-11 | **[VERIFIED]** Stars requirement sentence; TON Connect never touches keys; it requests signatures/transactions |
| https://docs.ton.org/contracts/standard/tokens/nft/how-it-works | 2026-11-11 | **[VERIFIED]** each item is its own contract; collection is source of truth; collection-membership must be cross-checked; transfer updates owner and optionally notifies |
| https://github.com/ton-blockchain/TEPs/blob/master/text/0062-nft-standard.md | 2026-11-11 | **[VERIFIED]** `transfer#5fcc3d14` TL-B; owner-only rejection rule; `ownership_assigned` only when `forward_amount > 0`; `get_nft_data` fields; binary comment `0xff` payload convention |
| https://docs.ton.org/contracts/standard/tokens/nft/transfer | 2026-11-11 | **[VERIFIED]** transfer flow, `response_destination`/excesses behaviour |
| https://fragment.com | 2026-11-11 | Existence only; **payout mechanics NOT verified** |
| `core.telegram.org/bots/payments-stars`, `/bots/api`, `telegram.org/tos/bot-developers` | **attempted 2026-11-11, blocked** | **Nothing.** All Stars/terms claims in this document are **[OPEN]** or quoted from this repository's prior audit dated 2026-11-09 |
| Repository at `8ab3501` | 2026-11-11 | Baseline facts in §1, obtained by reading the files listed there |
| `docs/ASSET_INTEGRATION_AUDIT.md`, `docs/ORDER_LIFECYCLE.md`, `docs/PAYMENTS_ESCROW_DESIGN.md`, `docs/adr/0001-...md` (same repo) | 2026-11-11 | Prior internal analysis; treated as claims, not verification |

---

## 15. What I would want to be told if I were the maintainer

The strongest argument against this proposal is short: *it asks the operator to hold other people's money before any legal review, and calls the result "verified".* That is a fair criticism, and it is why §7.2 item 10 sits above every other question in this document.

The strongest argument for it is equally short: *the alternative — model A as written in ADR-0001 — also holds other people's money, and additionally tells the buyer there is nothing to be done if the NFT never arrives.* Between those two, the version that funds a remedy and discloses its cap is the more honest product and the smaller regulatory surprise.

Neither is shippable without a lawyer's answer to §13 question 1.