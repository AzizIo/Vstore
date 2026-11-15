# Release readiness — 2026-11-16

**Evidence baseline:** `main` at `e003dc5ae82f2beb55fb2277361588267a70f21e`  
**Purpose:** current operator-facing gate report; historical 2026-11-14 snapshot remains unchanged.  
**Decision:** no real-money NFT checkout, seller payouts, non-zero escrow fee or mainnet escrow is approved.

## 1. Executive summary

VILTARA has a functioning marketplace/order foundation and several isolated payment/escrow development components. It is **not yet a real-money marketplace**.

The next release can progress in two separate steps:

1. A no-payment public beta after production hosting, wallet, direct NFT delivery, moderation, support and operational acceptance.
2. A paid marketplace only after the policy, legal, payment, payout, escrow, independent-security and operational gates in this report are closed.

A green CI run, a merged contract PoC, or a test Telegram Stars payment is not approval to accept real money or custody valuable NFTs.

## 2. Verified main baseline

Current `main`: `e003dc5ae82f2beb55fb2277361588267a70f21e`.

### Marketplace and order flow

- Catalogue/listings, moderation, reservations and non-custodial TEP-62 transfer observation are implemented.
- The existing order lifecycle is separate from payment state. A reservation is not a payment and a client claim cannot complete an order.
- The direct NFT delivery flow is not TON escrow and does not promise escrow-backed buyer protection.
- A no-payment beta still requires exact-host, live wallet, NFT ownership/delivery and operational acceptance.

### Telegram Stars

- Stars intent/transaction/event ledger and the dedicated test-bot integration are present.
- The HTTP payment surface is guarded to an isolated local/development/test runtime, separate test bot token and local PostgreSQL database with a test-named database.
- The Stars test bot uses Telegram's dedicated Test Bot API namespace; this is not production checkout or live collection.
- Durable refund workflow code/migrations are present on `main`, but the current worker is restricted to the isolated test environment. The implemented Bot API refund path is whole-charge; no partial Stars refund is offered.
- There is no approved production webhook/checkout path, seller Stars balance, automatic seller payout or accounting contract for paying marketplace sellers from Stars.
- Do not label test Stars, a provider callback, or an internal ledger row as seller funds.

### TON Escrow

- The DealEscrow source/ABI/BOC, backend observer/action primitives and testnet-only UI/API foundations are development/PoC components.
- The contract is testnet-scoped and has no arbitrary owner withdrawal or server-held user key capability.
- The current PoC pins `fee_bps = 0`; the backend/frontend action contract also rejects non-zero fee configuration.
- The carry-all execution-reserve retry now reapplies the terminal storage reserve before sending remaining balance. PR #242 is merged to this baseline after exact-head Contract CI passed (30/30 emulator tests); the post-merge Contract CI for this new main SHA is still running at report time.
- Escrow observer/router exposure is runtime-gated; production deployment does not mount testnet escrow routes. The isolated Preview observer requires an explicit opt-in and remains disabled by default.
- A backend database projection, a submitted wallet transaction hash, an emitted outbound message, or an indexer status does not prove finalized NFT delivery or payment.
- No public paid NFT purchase CTA, mainnet escrow, live custody, treasury collection or automatic seller payout is approved.

### Revenue architecture

- [ADR-0002 — Marketplace revenue and settlement rails](adr/0002-marketplace-revenue-and-settlement.md) is merged to `main`.
- It defines Stars and TON as separate settlement rails and currencies.
- 10% is a proposed planning take-rate, **not an owner-approved or deployed fee**. No production fee recipient/treasury is configured.
- Future TON fees must be implemented in a separately versioned/audited contract with immutable fee and treasury snapshots and exact seller-net/treasury reconciliation.
- Stars credited to the TPA do not create per-seller balances or automatic seller payouts. Any seller proceeds from a Stars-funded flow require a separate, legally approved and funded payout process.

## 3. Active workstreams and exact integration state

| Work | Current status | Release implication |
|---|---|---|
| Preview runtime gate — PR #238 | Merged to main; post-merge Backend and Frontend/API E2E passed | Preview opt-in is wired; it does not authorize payments or mainnet |
| Revenue and settlement ADR — PR #240 | Merged to main | Commercial accounting and policy boundaries documented; no payment rail enabled |
| NFT identity / collection membership — PR #241 | Draft; exact-head Backend CI failed 2 API contract tests; Frontend/API E2E passed | Do not merge until fixtures are corrected and all checks pass |
| Contract reserve retry floor — PR #242 | Merged to main; exact-head Contract CI #43766977381 passed (30/30 emulator tests); post-merge Contract CI #43767167484 is running | Backend adapter code-hash pin still belongs to Issue #206; merge does not approve live escrow |
| Direct per-deal StateInit UI — PR #233 / Issue #226 | Draft, based on an older main SHA | Must be rebased/integrated with the new backend activation and proof contract before acceptance |
| Independent contract review — Issue #225 | Not completed | No production escrow |
| Telegram policy ruling — Issue #155 | Open | Paid P2P NFT flow inside the Telegram Mini App remains blocked |
| Stars test integration — Issue #224 | Test-only implementation | No production collection/refunds or seller settlements |

Do not merge stale branches wholesale. Review PR diffs against current `main`, preserve workstream ownership, and require all relevant checks to pass on one exact PR head SHA.

## 4. Required buyer/seller deal guarantees

Before any paid transaction may be enabled, all of the following must be demonstrated:

1. **Authentic asset:** exact NFT item and collection membership verified against an explicit collection/code-hash allowlist using trusted, same-block account-state evidence. Metadata/indexer claims alone are insufficient.
2. **Immutable terms:** buyer, seller, item, collection, price, network, deal salt, contract address, fee policy and treasury recipient are snapshotted before signing and cannot be changed after creation.
3. **Exclusive reservation:** one NFT cannot be reserved or sold in parallel by an ordinary order and an escrow deal or by two buyers.
4. **Safe wallet review:** the user sees the exact network, destination, item, amount, fees/reserves, recipient and action before approving the wallet request. The application never asks for seed phrases or private keys.
5. **Finality, not submission:** only validated finalized transaction/message/trace evidence and matching contract state/getter data may mark deposit, delivery, payout or refund as final.
6. **Explicit asynchronous failure paths:** bounces, action-phase failures, duplicate/replayed messages, provider outages, timeouts, reorgs, delayed finality and worker restarts preserve principal/NFT custody and enter a recoverable pending/manual-review state. A timeout is not proof of success or failure.
7. **Disputes with feasible custody:** buyer/seller authorization, deadlines, resolver quorum, replay protection and NFT-return prerequisites are tested. The contract cannot seize an NFT after it reaches a buyer-controlled wallet.
8. **Exactly-once accounting:** seller payout, platform fee and refunds reconcile to exact finalized on-chain transfers; no duplicate or ambiguous retry may double-pay.
9. **No false seller balance:** pending money is not withdrawable; Stars, TON and execution reserves are separate; every ledger entry has immutable provider/chain identity and evidence.

## 5. Money and revenue rules

### Stars

- Use Stars only for product flows permitted by the current Telegram terms and the written ruling for the exact VILTARA flow.
- Treat Stars as the TPA's provider balance, not escrowed seller proceeds.
- Recheck current Fragment reward availability, regional eligibility, timing, withholding and tax/accounting requirements before any operator revenue claim.
- Any Stars seller payout requires an independently approved merchant-of-record and seller-contract design, a funded/regulated payout mechanism appropriate to the jurisdictions, full-charge refund liability and reconciliation.

### TON

- Keep PoC fee at zero.
- A future non-zero fee must be introduced in a new reviewed protocol version. Fee and treasury address must be immutable per deal.
- Illustrative commercial proposal in ADR-0002: 10% platform / 90% seller on a successful non-refunded deal only. This must be explicitly approved before implementation.
- Contract execution reserve/network costs are not platform revenue and must be shown separately.
- Fee collection must be proven by finalized chain evidence and reconciled to the treasury wallet; a UI calculation or DB row cannot credit the platform.

## 6. Release gates

### Gate A — no-payment public beta

- Production host, DNS/TLS, reverse proxy, CORS, firewall, rate limits and monitoring are verified.
- Production DB backup/restore and Alembic migration upgrade are rehearsed against a separate database.
- Production secrets and storage are isolated from Preview/test; no test bot token or testnet wallet is reused.
- Telegram Mini App manifest/host, mobile WebView, login, wallet proof, wallet/network switching and notifications pass manual acceptance.
- Real target-chain direct NFT transfer and backend post-transfer owner verification pass without a payment/escrow promise.
- Moderation, support/contact, terms/privacy and non-custodial/no-buyer-protection copy are accurate.
- Payment and escrow user-facing entry points remain disabled.

### Gate B — isolated testnet escrow acceptance

- PR #213 NFT identity policy/proof work is merged after exact-head CI, migration upgrade/downgrade and reviewer acceptance.
- PR #225 contract lifecycle/recovery work is merged with current frozen ABI/BOC/StateInit and golden vectors reproduced by pinned CI.
- Backend observer validates finalized proof and matching getters; outage/replay/restart/reorg cases are covered.
- Backend, Frontend/API E2E and Contract CI pass on the integrated commit.
- Only disposable test wallets and valueless test NFTs/TON are used, after a separately approved test plan.
- Tonkeeper/TON Connect acceptance captures exact transaction traces and final balances for every happy and failure branch.
- No real funds, valuable NFTs, server signing or automated broadcast service is used.

### Gate C — policy, legal and independent security

- Written Telegram guidance specifically classifies the VILTARA P2P resale of existing TON NFTs and the proposed Mini App purchase surfaces; do not infer a permission from generic support text.
- Qualified legal/compliance review covers the operator entity and intended seller/buyer countries, custody/escrow status, consumer rights, sanctions/KYC, tax, disputes, refunds and seller settlement.
- Independent TON/Tolk smart-contract audit is completed against one frozen SHA and exact artifact hashes, with no unresolved critical/high findings.
- Treasury structure, multisig signers, key recovery, access controls, incident response and reconciliation runbooks are accepted.
- Stars merchant-of-record and seller payout obligations are explicitly decided if a Stars product is used.

### Gate D — controlled real-money launch

- Separate maintainer approval records exact production bot, host, provider, chain, treasury address, fee, jurisdictions, user/transaction limits and rollback plan.
- Production payment/refund integration is independently tested with a provider-approved environment and signed off operationally.
- Seller payout, refunds, fee receipts and treasury balance reconcile daily from primary provider/chain evidence.
- Gradual rollout, per-seller caps, transaction limits, monitoring, manual review and emergency stop are tested before wider launch.

## 7. Explicit no-go conditions

Do not enable paid NFT checkout, real-value escrow or seller payouts while any of these is true:

- Issue #155 exact Telegram policy ruling is unresolved.
- The contract has not received independent review and valueless testnet acceptance.
- Collection membership or owner identity is based only on an indexer/metadata response.
- Backend cannot reconcile finalized chain evidence to exact immutable deal terms and getter state.
- Any CI/migration check is red on the proposed merge SHA.
- A seller balance is derived from Stars balance, a client callback, a pending event or an unverified DB row.
- Commission is displayed but not actually split and reconciled by the reviewed contract.
- Production/test secrets, databases, bots, networks or wallets are shared.
- Refund/dispute/ambiguous-outcome handling is not durable and operationally accepted.

**Current decision (2026-11-16):** no-payment beta may proceed only after Gate A. Paid NFT checkout, Stars-funded seller settlements, non-zero TON commission, production escrow and mainnet remain **NO-GO**.
