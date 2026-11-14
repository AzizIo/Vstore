# ADR-0001: Compliant payments and escrow architecture

- **Status:** Proposed — awaiting maintainer review
- **Date:** 2026-11-10
- **Review date for external references:** 2026-11-10
- **Issue:** https://github.com/AzizIo/Vstore/issues/30
- **Supersedes:** none
- **Companion design document:** [`docs/PAYMENTS_ESCROW_DESIGN.md`](../PAYMENTS_ESCROW_DESIGN.md)

## 1. Context

The original Issue #19 reservation design has since been superseded by
the current order/delivery lifecycle on `main`:
`reserved -> awaiting_transfer -> observing_transfer -> completed`, with
`cancelled` and `expired` terminal paths. The TON delivery observer is the
authority for NFT completion; the order table deliberately has no `paid` state.

As of 2026-11-14, main also contains migration `0012_telegram_stars_payments`
and a separate Stars intent/transaction/append-only event ledger, plus a strictly
test-only Telegram bot and synthetic-order seeder. The test bot uses Telegram's
dedicated test API namespace and a local test database. It is not a public checkout,
does not authorize live charges, and a successful test payment does not complete
NFT delivery. See `docs/TELEGRAM_STARS_TEST_RUNBOOK.md`.

The durable refund worker and migration 0013 are still proposed in Draft PR #173,
not merged. No live refund capability, seller payout, funds custody or escrow
contract is available on main. The order table's check constraint continues to
forbid payment states such as `paid` and `refunded`; payment status remains a
separate domain.

A real marketplace must eventually answer four separate questions:

1. How may payment be collected inside a Telegram bot / Mini App?
2. Who controls the funds between payment and delivery, and under which rules?
3. Which trusted server events — and only those — may advance an order to `paid`
   or `completed`?
4. How does the asset actually reach the buyer, and who bears the risk if it does
   not?

Telegram's platform rules constrain question 1. TON's asynchronous transfer model
constrains question 4. Neither Telegram nor TON provides escrow or seller payouts;
that is a business and legal construct (questions 2–3) that must be built and
reviewed explicitly. The previous audit
([`docs/ASSET_INTEGRATION_AUDIT.md`](../ASSET_INTEGRATION_AUDIT.md)) established
the asset and platform constraints; this ADR records the resulting architectural
decision before any real-value code is written.

### Implementation status (snapshot: 2026-11-14)

This ADR remains **Proposed — awaiting maintainer review**. The merged Stars
ledger and isolated test bot are technical test infrastructure, not approval of
the product/payment decision below. In particular:

- Telegram test-environment invoice and payment handling exists on `main`;
  manual live test-environment acceptance is still tracked by Issue #152.
- Public checkout remains disabled pending the written platform ruling in Issue
  #155 and qualified legal/compliance review.
- Refund worker/migration 0013 are not merged; see Draft PR #173.
- The order delivery lifecycle in Issue #46 is implemented on `main`, but live
  testnet/Tonkeeper acceptance remains outstanding.
- TON escrow remains design-only in PR #172; Issue #153 still requires accepted
  architecture, threat model and independent contract-review plan.

The implementation facts above do not change the ADR's approval status or grant
permission for live payments, refunds, custody, seller settlement or mainnet use.

## 2. Decision

**D1 — Checkout inside Telegram uses Telegram Stars (`XTR`) only.**
Sales of digital goods and services in bots and Mini Apps must be paid with
Telegram Stars. The Mini App checkout therefore creates a Stars invoice link on the
server for an existing order snapshot; TON Connect is never used to bypass this
requirement. Purchasable listings are priced in `XTR` at launch; the `TON` price
currency remains in the schema but such listings are not purchasable in-app until a
separately reviewed flow exists (see Alternative B/C).

**D2 — The payment boundary is a server-side adapter with verified provider
notifications.** `app.orders.payment.PaymentAdapter` stays the trusted boundary and
is extended with: intent creation from the persisted order snapshot, notification
verification, refund submission and reconciliation lookup. The Telegram Stars
implementation verifies the Bot API `successful_payment` update (webhook
`secret_token` + payload match against a stored invoice) and the exact amount,
currency, payer and order identity. **No client request may mark an order paid,
refunded or completed**; only a verified server-side provider event (or an
authorized admin/dispute action, which is out of launch scope) may.

**D3 — No escrow or live seller settlement is approved by this ADR.** Stars accrue
to the account that owns the TPA; the Stars balance is not a seller sub-ledger and
must not be described as cash held in trust for each seller. Telegram's current
terms say Stars in the TPA balance remain Telegram's property, while the developer
may request rewards under Telegram's terms. The currently documented reward value
is USD 0.013 per Star, availability for rewards may be delayed up to 21 days, and
Fragment processes rewards but may not be available in some countries. If the
marketplace later pays individual sellers, those settlements are a separate
operator-managed obligation and may create custody, money-transmission, tax,
sanctions and consumer-protection questions. A ledger entry alone does not settle
those questions. **No real-value sale or seller payout may launch** until qualified
legal/compliance review, Fragment eligibility checks, payment-dispute procedures
and the irreversible-NFT-delivery risk are cleared. Manual payouts are a proposal
to review, not a claim of "no custody". On-chain escrow and automatic payouts remain
**NO-GO** for production.

**D4 — Payment state transitions are append-only and idempotent.** Every transition
is written to `order_events` with actor `buyer`, `system`, `provider` or `admin`;
provider references are unique; duplicate notifications are no-ops; the transition
function is the single place that validates allowed source and target states.

**D5 — Delivery is seller-operated, but irreversible delivery is a launch blocker
for paid virtual items.** The seller would transfer the NFT directly to the buyer's
verified wallet; the backend would re-check ownership through TEP-62 before and
after delivery, and only a verified transfer could complete the order. Telegram's
current Bot Developer Terms explicitly discourage real-time sales of digital
products or virtual items with inherent value that cannot be reclaimed, frozen,
rescinded, invalidated or suspended after a successful dispute or chargeback. A
TON NFT transfer may be irreversible. Therefore this ADR does **not** approve
live Stars sales of NFTs merely because checkout uses XTR: a documented, reviewed
dispute/compensation model and confirmation that the delivery model is acceptable
are required first. Until then the app must not imply guaranteed delivery or
enable paid completion.

**D6 — Compliance questions are deferred to qualified review, not answered
technically.** The classification of peer-to-peer NFT resale as a digital good,
the real-time sale warning, seller settlement/custody model, Fragment country
eligibility, KYC/AML, tax and consumer-protection obligations are production
blockers in §8 of the design document. This ADR is a technical decision, not legal
advice.

## 3. Considered alternatives

### A. Telegram Stars checkout + separately reviewed seller settlement (candidate)

| | |
|---|---|
| Pros | Stars is the required in-app currency for digital goods; the Bot API provides invoice, successful-payment and refund primitives; fits the existing `XTR` price enum. |
| Cons | Stars accrue to the TPA owner, not individual sellers; the balance is not developer-owned cash; rewards are subject to Telegram/Fragment eligibility, rates and delays; manual seller settlement remains a separately reviewed obligation; Telegram warns about irreversible high-value virtual-item delivery and chargebacks. |
| Verdict | Keep as the only candidate in-app checkout design, but **do not enable live sales** until the production blockers in §8 of the companion design are cleared. |

### B. TON Connect direct checkout in the Mini App (rejected for in-app digital goods)

| | |
|---|---|
| Pros | Natural to NFT buyers; funds arrive in a wallet the operator controls; no Stars conversion. |
| Cons | Using TON Connect as the in-app payment method for digital goods circumvents Telegram's Stars requirement; non-custodial by design, so "payment to the marketplace" means an operator wallet, which creates custody and payout obligations; on-chain confirmation lags and chain reorgs complicate UX and reconciliation. |
| Verdict | Rejected for in-app checkout. Remains viable only for blockchain interactions outside the purchase flow and for a future out-of-Telegram checkout explicitly permitted by policy. |

### C. External checkout (website / payment processor) (deferred)

| | |
|---|---|
| Pros | Full control over payment methods, receipts and payouts; can support non-Stars flows. |
| Cons | Pulling buyers out of the Mini App loses conversion; processor terms for NFT marketplaces require separate onboarding and may prohibit or restrict the category; the Mini App cannot deep-link into a compliant purchase without policy review. |
| Verdict | Deferred; revisit only with a reviewed payment processor contract and legal sign-off. |

### D. On-chain TON escrow contract (deferred; design-only)

| | |
|---|---|
| Pros | Real buyer protection; programmable release/refund/dispute; aligns with NFT-native users. |
| Cons | Security-critical code handling valuable assets; key custody and admin powers must be defined and audited; asynchronous TON messaging, bounced messages and timeouts complicate the state machine; on-chain escrow may itself be a regulated custody activity depending on jurisdiction. |
| Verdict | **NO-GO for production.** Permitted only as an isolated testnet PoC after the threat model is accepted and before any mainnet deployment.**

### E. Third-party marketplace/payment provider for NFT resale (not evaluated)

| | |
|---|---|
| Pros | Offloads compliance and payouts. |
| Cons | Provider terms, fees and category restrictions unknown; would change the product model. |
| Verdict | Out of scope; may be considered after legal review. |

### F. Hybrid: Stars for in-app checkout and TON pricing for view-only listings (chosen shape)

Chosen front end of decision D1: listings may exist in `TON`, but only `XTR`
listings are purchasable in-app at launch. This preserves the catalog for
TON-priced assets without implementing a non-compliant checkout.

## 4. Official Telegram policy references (reviewed 2026-11-10)

> Verification note: live official pages were checked on 2026-11-10. Telegram
> describes digital-goods transactions in bots and Mini Apps as Stars-only; its
> developer terms also specify the current reward value and delay, require
> payment-support handling, and warn against real-time sales of irreversible
> virtual items. These are platform facts, not legal advice or a determination
> that every NFT resale model is permitted. Re-check the source pages and
> applicable Apple/Google rules at implementation and launch because definitions
> and terms can change.

| Topic | Official source | Verified fact / design consequence |
|---|---|---|
| Stars-only digital-goods checkout | https://core.telegram.org/bots/payments-stars and https://telegram.org/tos/bot-developers#6-2-digital-goods-and-services | In-app digital goods/services use `XTR`; Telegram's FAQ says other currencies/crypto are not accepted for those purchases inside Telegram. Whether peer-to-peer NFT resale is classified this way remains a platform/legal interpretation to confirm. |
| Pre-checkout and successful payment | https://core.telegram.org/bots/payments-stars | Answer `pre_checkout_query` within 10 seconds; do not deliver on pre-checkout approval alone; wait for `successful_payment` and store `telegram_payment_charge_id`. |
| Refunds and customer support | https://core.telegram.org/bots/api#refundstarpayment and https://core.telegram.org/bots/payments-stars | Refunds use `refundStarPayment`; bots/Mini Apps must support `/paysupport`. The live checklist also asks for accessible terms (`/terms`) and support (`/support` or equivalent). |
| Stars balance and rewards | https://telegram.org/tos/bot-developers#6-2-digital-goods-and-services | The TPA balance is not the developer's property; current reward value is USD 0.013 per Star, but Telegram may change it. |
| Reward delay and eligibility | https://telegram.org/tos/bot-developers#6-2-digital-goods-and-services | Stars may take up to 21 days to become available for rewards; Fragment processes rewards and may not serve users in certain countries. |
| Irreversible virtual goods / chargebacks | https://telegram.org/tos/bot-developers#6-2-digital-goods-and-services | Telegram expressly discourages real-time sale of virtual items with inherent value that cannot be reclaimed, frozen or rescinded after successful disputes/chargebacks. This is a material NFT-delivery risk. |
| Webhook authenticity | https://core.telegram.org/bots/api#setwebhook | `setWebhook.secret_token` is delivered in `X-Telegram-Bot-Api-Secret-Token`; verify it with a constant-time comparison. |
| TON wallet integration | https://telegram.org/tos/bot-developers#7-blockchain-integration | Mini Apps with crypto functionality must use TON; wallet interaction uses TON Connect. This does not override the Stars-only rule for digital-goods checkout. |
| Mini App platform rules | https://core.telegram.org/bots/webapps | Additional Mini App integration requirements. |
| Telegram Business (gifts) | https://core.telegram.org/bots/api#gifts | Gift lookup/transfer methods and business-account permissions (separate from standard TON NFT transfers). |

Implementation must re-verify the current reward value, Fragment eligibility and
country restrictions. Do not present a fixed Stars-to-cash conversion rate or
payout schedule as a guaranteed user-facing promise.

## 5. Consequences

Positive:

- A first technical milestone can validate invoice and webhook handling in
  Telegram's test environment without handling live value, seed phrases, escrow
  contracts or mainnet deployments.
- The existing reservation lifecycle, idempotency key and append-only event log
  remain valid; the design adds states through a new migration rather than
  rewriting history.
- Every future payment capability (Stars, escrow, payouts) plugs into the same
  adapter protocol and the same state machine tests.

Negative / accepted:

- If a later launch is approved, seller settlement would still require a
  separately reviewed operator process, ledger reconciliation and legal/
  compliance clearance; a ledger is not itself custody approval.
- TON-priced listings are viewable but not purchasable in-app at launch.
- Without escrow there is no buyer protection; dispute handling must be manual
  (admin), and product copy must say so.

## 6. Go / No-Go recommendation

- **GO:** documentation and non-live adapter/state-machine prototypes with fake
  providers, no credentials and no payment transitions enabled.
- **CONDITIONAL GO:** a Stars integration against Telegram's dedicated test
  environment only, after maintainers accept this ADR and implement the required
  `/paysupport`, `/terms` and support flows. A production pilot additionally
  requires written platform/legal review of NFT resale classification, the
  irreversible-delivery warning, seller settlement, Fragment eligibility and
  refund/dispute exposure.
- **GO (isolated):** TON testnet-only escrow PoC after the threat model and
  external contract review plan are approved; no mainnet deployment.
- **NO-GO:** live NFT checkout or seller payouts before those reviews; on-chain
  or custodial escrow in production; storage of wallet secrets or seed phrases;
  automatic seller payouts; client-triggered paid/completed transitions; and any
  checkout that bypasses Stars for in-app digital goods.

## 7. Phased implementation plan

| Phase | Scope | Gate |
|---|---|---|
| 0 | This ADR + design document. No code. | Maintainer review of this ADR. |
| 1 | Stars adapter skeleton behind `PaymentAdapter`, invoice creation for `XTR` orders, webhook ingestion with secret-token check, `payment_transactions` ledger, `paid/refunded` states, manual payout ledger proposal, reconciliation job, and `/paysupport`/`/terms`/`/support` flows. | Test-environment matrix green; current policy re-verified; platform/legal review and operator payout procedure accepted before any live sale. |
| 2 | Delivery verification: TEP-62 re-check before delivery, post-transfer ownership check, `delivery_pending -> completed`, dispute flag and admin tooling (manual). | Escrow threat model accepted; manual dispute runbook. |
| 3 | Testnet escrow PoC: disposable contract + watcher + replay of failure matrix. | Independent contract/security review of PoC results. |
| 4 | Production escrow/payouts — only if Phase 3 review approves **and** legal/compliance review of the custody model clears. | External security audit + legal opinion. |
