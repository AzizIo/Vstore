# ADR-0002 — Marketplace revenue and settlement rails

- **Status:** Proposed commercial policy; mandatory technical safety constraints
- **Date:** 2026-11-16
- **Decision owner:** VILTARA maintainer
- **Scope:** TON NFT secondary marketplace, Telegram Mini App, Telegram Stars and TON
- **Related:** ADR-0001, Issues #155, #224, #225, #226, #237

## 1. Executive decision

VILTARA must keep two independent payment and settlement rails. They must not be represented as one balance or silently converted into one another.

1. **Telegram Stars (XTR)** are a possible in-Telegram payment rail only for a product flow Telegram permits. Stars accrue to the Telegram account that owns the bot/TPA. They do not automatically split into seller proceeds, do not create seller balances and are not TON held in escrow.
2. **TON** is the native on-chain settlement rail for a separately approved blockchain transaction. If the exact NFT resale flow is cleared for this context, the eventual escrow contract may split a successful settlement between the seller and a platform treasury. TON Connect lets users approve wallet transactions without the application receiving their private keys.
3. **No real-money rail is enabled by this ADR.** The current Stars integration is isolated to Telegram's test environment. The current DealEscrow PoC fixes fee_bps = 0. Production checkout, fee collection, seller payouts, custody and mainnet signing remain disabled.

This ADR does not interpret Telegram policy as legal advice. The exact P2P secondary-sale classification remains an explicit written-guidance blocker in Issue #155.

## 2. Commercial fee proposal

The current release-readiness proposal uses a **10% platform fee** on successfully settled deals. This ADR carries that rate forward as the planning baseline, not as a deployed or owner-approved charge.

For a future approved TON contract version:
- Gross principal: 100%.
- Platform fee: 10% (1,000 basis points).
- Seller net: 90%.
- Network, storage, forwarding and contract execution reserves: disclosed and accounted for separately; they are not platform revenue.

For principal P represented as integer nanotons:

    fee = floor(P × 1000 / 10000)
    sellerNet = P − fee

The contract must conserve the principal exactly: fee + sellerNet == P. Integer arithmetic only; no floating-point calculations. Rounding is downward so the remainder stays with the seller. If a future contract needs a minimum fee or a minimum viable price, it must define and test that rule explicitly rather than silently changing rounding.

**Fee trigger:** a fee is earned only on a completed, non-refunded settlement after the contract's delivery/dispute conditions and exact payout finality are satisfied. A listing, reservation, payment intent, pending payout, timeout, disputed deal or emitted outbound message does not earn a fee. Cancelled, expired-before-funding and buyer-refunded deals have a zero platform fee.

The rate, fee recipient, protocol version and principal must be snapshotted per deal before any party signs. Neither an API request, admin panel nor mutable database row may alter the fee after deal creation.

## 3. Telegram Stars rail

### 3.1 What Stars can and cannot do

The Telegram Bot Developer Terms state that digital goods and services sold through a Telegram bot or Mini App use Telegram Stars (XTR), rather than an alternative third-party checkout. The same terms say that Stars credited to a TPA balance are not the developer's property in the ordinary sense; the owner may use the balance for the permitted in-platform purposes or accept rewards under Telegram's terms.

As checked on 2026-11-16, the published developer terms state:
- Telegram assigns a reward value equivalent to USD 0.013 per Star, at Telegram's discretion and subject to change.
- Stars may be unavailable for advertising credits or rewards for up to 21 days after receipt.
- Rewards are processed through Fragment, which may be unavailable to certain users or in certain countries.
- Telegram may withhold or debit Stars in response to refunds, suspected abuse or terms violations.
- Earned Stars expire after three years if they are not used for rewards or advertising.

These facts do **not** create a guaranteed cash-conversion rate, a guaranteed withdrawal date, a seller payout mechanism or an obligation by Telegram/Fragment to pay every operator in every jurisdiction. VILTARA must not market Stars as TON, cash, escrowed seller funds or a guaranteed payout.

### 3.2 NFT-sale policy gate

The exact VILTARA flow is a resale of an existing TEP-62 NFT between two users, coordinated by a Telegram Mini App. Issue #155 records that the public rules do not conclusively classify this exact P2P flow.

Telegram's §6.2.1 also expressly discourages real-time sales of digital products/virtual items with inherent value that cannot be reclaimed, frozen, rescinded, invalidated or suspended after a successful dispute or chargeback. This is directly relevant to irreversible NFT transfers.

Therefore:
- Do not show a live Stars or TON purchase CTA for NFT resale inside the Mini App until written Telegram guidance addresses this exact flow and qualified legal/compliance review approves the product in the intended jurisdictions.
- Do not assume that routing the user to TON Connect, a wallet, an external URL or a separate screen bypasses the Stars rule or the irreversible-item warning.
- Do not assume that a Stars payment makes an irreversible NFT transfer safe or makes the seller's proceeds recoverable.
- Preserve the exact written response and its scope in Issue #155. A generic support reply is not sufficient if it does not answer the listed questions.

### 3.3 Stars accounting and seller settlement

For a permitted Stars product, the buyer pays the VILTARA TPA. The Stars balance belongs to the bot/TPA context, not to each listing seller.

This creates two separate liabilities/obligations:
1. The TPA's Stars balance and any reward that the owner later becomes eligible to claim through Telegram/Fragment.
2. Any contractual amount VILTARA owes a seller under a separately approved seller agreement and payout rail.

A fee_amount = 10% accounting row does not pay the seller. The product must not display a seller TON balance or "withdraw Stars" control unless a real, reviewed settlement provider and funded reconciliation process exist. A future Stars-funded marketplace model requires explicit merchant-of-record, seller contract, full-refund liability, seller payout, tax, sanctions/KYC and regional eligibility decisions.

The implemented Telegram refundStarPayment path is full-charge only; the Bot API method does not accept a partial-refund amount. Keep Stars refunds whole-charge and evidence-backed. Unknown outcomes remain pending/reconciliation/manual review; never blindly issue a second refund.

## 4. TON on-chain rail

TON settlement is the intended path for an eventual wallet-to-wallet crypto settlement only after Telegram policy, legal/compliance, contract and operational gates have cleared for the exact launch context.

### 4.1 Future settlement shape

For one immutable deal:
1. The seller signs the exact NFT deposit from their own wallet.
2. The buyer signs the exact principal plus a separately disclosed execution reserve.
3. Escrow holds the NFT and principal through the agreed buyer-review, delivery-finality and dispute conditions.
4. On the success branch, the contract sends the seller net directly to the snapshotted seller address and the fee directly to the snapshotted VILTARA treasury address.
5. On a valid buyer-refund branch, the contract returns the principal according to the reviewed outcome and charges no platform fee.
6. Backend reconciliation records the exact finalized chain transfers and terminal getter state. A transaction hash, client callback, indexer-only status, API status or emitted outbound message is not settlement proof.

### 4.2 Contract invariants before non-zero fees

A non-zero platform fee must be implemented only in a separately versioned and reviewed contract protocol. Do not retrofit it into the current zero-fee PoC by changing a UI label or backend calculation.

Required invariants:
- fee_bps is bounded and snapshotted in immutable deal terms.
- Treasury address is explicit, validated, fixed for that deal and controlled through an approved treasury-key policy (prefer a multisig with independent signers).
- The buyer sees gross principal, fee, seller net, every outgoing destination and every attached execution reserve before signing.
- Fee and seller net are emitted/represented in verifiable contract evidence and independently reconciled to finalized transactions.
- Exactly one successful settlement can pay the seller and treasury. Duplicate, stale, reordered, bounced or ambiguous messages cannot double-pay either recipient.
- No arbitrary owner withdrawal, mutable recipient, post-creation fee increase or server-held private key.
- Network costs never silently reduce the seller's fixed net or masquerade as platform commission.
- A bounced/failed payment remains pending/manual review until canonical chain evidence establishes the outcome. Never retry a transfer merely because an observer timed out.

### 4.3 Backend accounting

The backend ledger is an auditable projection of provider/chain facts, not the source of truth for funds.

Each settlement record should preserve at minimum:
- unique internal settlement ID and deal/order ID;
- rail/provider (telegram_stars or ton_escrow), network and protocol version;
- currency/asset and exact integer amount (XTR integer or nanotons; never float);
- gross principal, fee basis points, fee amount, seller net and execution-cost amounts;
- buyer, seller and treasury identifiers/addresses as immutable snapshots;
- provider charge/update IDs or chain transaction/message/trace identity;
- current reconciliation status, evidence hash, finality checkpoint and timestamps;
- append-only events for capture, refund, payout, fee, retry, reconciliation and manual review.

The ledger must enforce uniqueness/idempotency for every external payment or chain settlement identity, retain the evidence trail, and prohibit a seller from withdrawing an amount that is merely pending. Stars and TON must never be netted or summed as if they shared a currency.

## 5. Current implementation status on main

Verified against main at a08b3b7632e1e1d8c38ac7a896b519a595f32df8:

| Area | Current state | Consequence |
|---|---|---|
| Stars API | Authenticated payment-intent and read-status API exists only in an explicitly isolated local/test runtime | Not production checkout |
| Stars transport | Dedicated Telegram test bot; long polling; no live payment webhook | No live capture |
| Stars refunds | Durable full-refund workflow is test-only | No production refund/payout approval |
| TON escrow | Isolated testnet PoC; action/provider paths remain fail-closed pending full immutable snapshot and proof reconciliation | No production custody or mainnet actions |
| TON fee | fee_bps = 0 in the PoC and shared interface | No contract commission |
| Seller balances | No real seller payout/withdrawal rail | Do not show claimable balance |
| Policy | Issue #155 open | NFT paid checkout remains blocked |

The current zero-fee PoC is intentional. A green emulator or CI suite is not an independent contract audit or live testnet acceptance.

## 6. Release gates

### Stage 0 — no-money marketplace
- Listings, moderation, wallet proof and direct NFT transfer are independently accepted on the real target host.
- Copy clearly states that a reservation is not payment and does not provide escrow/buyer protection.
- No paid CTA, commission, seller balance or payout promise.

### Stage 1 — isolated payment/contract test
- Stars test bot and test-named local PostgreSQL only.
- TON testnet only, valueless NFTs and disposable test wallets, after separate owner authorization of the exact plan.
- No production credentials, mainnet, real funds, automated signing or broadcast service.
- Full failure, replay, dispute, refund and balance-invariant suites pass on exact integrated commit.

### Stage 2 — policy and legal clearance
- Written Telegram answer for the precise P2P NFT flow and in-app payment surfaces.
- Qualified legal review in the operator's and target users' jurisdictions.
- Confirmed legal entity, merchant-of-record, seller terms, country eligibility, tax, sanctions/KYC, refund/dispute liability, accounting and treasury policy.
- If Stars is used, verify current Fragment eligibility/reward rules and design the seller payout rail separately.
- If TON is used, establish the permitted app context and custody/escrow regulatory treatment; do not treat TON Connect as a policy exemption.

### Stage 3 — independently reviewed money protocol
- Versioned non-zero-fee contract with frozen ABI/BOC/StateInit and golden vectors.
- Independent TON/Tolk security audit with no unresolved high/critical findings.
- Valueless testnet end-to-end acceptance, finalized event/getter reconciliation, payout/refund/bounce/retry matrix and operational incident drills.
- Treasury multisig and reviewed key recovery; no backend custody of user keys.
- Accounting ledger reconciles all gross/fee/net/reserve transfers from primary evidence.

### Stage 4 — controlled production launch
- Separate owner approval for exact production host, bot, provider, chain, treasury address, fee, jurisdictions and limits.
- Production database backup/restore, access roles, monitoring, alerts, incident response, support and rollback plan.
- Gradual rollout with transaction and per-seller limits, manual review thresholds and an emergency pause that cannot confiscate or redirect user assets.
- Daily reconciliation of provider/chain events, treasury receipts, seller payouts and refunds before increasing limits.

## 7. Owner decisions still required

1. Confirm or change the proposed 10% take rate before any non-zero fee protocol is designed.
2. Identify the operating legal entity and intended seller/buyer countries.
3. Decide whether VILTARA is the merchant of record for any Stars-paid product, and how sellers receive proceeds under a compliant separate rail.
4. Approve the treasury structure and multisig signers before any treasury address is frozen into a contract version.
5. Obtain and preserve Telegram's written classification for the exact NFT resale/escrow UX.

Until these decisions and release gates are complete, the only safe implementation state is: test-only Stars, zero-fee testnet escrow, and no public paid NFT checkout.

## 8. References

### Repository
- docs/RELEASE_READINESS_2026-11-14.md
- docs/ISSUE_224_PAYMENT_BACKEND_RELEASE_SNAPSHOT.md
- docs/TON_ESCROW_SHARED_INTERFACE.md
- docs/TON_ESCROW_SECURITY_REVIEW_PLAN.md
- Issue #155 — written Telegram policy ruling
- Issue #224 — Stars payment backend
- Issue #225 — contract lifecycle/security
- Issue #237 — release integration

### Official platform documentation checked 2026-11-16
- Telegram Bot Developer Terms, §6.2 and §6.2.1–6.2.7: https://telegram.org/tos/bot-developers#6-2-digital-goods-and-services
- Telegram Bot Payments for digital goods and services: https://core.telegram.org/bots/payments-stars
- Telegram Bot API: https://core.telegram.org/bots/api#refundstarpayment
- TON Connect overview: https://docs.ton.org/applications/ton-connect/overview

This document is an architecture decision record, not legal, tax, accounting or investment advice.
