# Release readiness — 2026-11-14

This checklist separates a public marketplace release from a real-money release.
A successful CI run or a deployed Mini App does not close Telegram policy,
wallet, blockchain, payment, payout, security or legal acceptance.

## 1. Current facts from `main`

- Marketplace catalogue, listing moderation, reservation and direct non-custodial
  TEP-62 delivery code are implemented.
- Reservation is not payment. No money is collected by the current order flow.
- Telegram Stars intent/transaction/event tables and a dedicated test-bot
  harness exist. The Stars test path is deliberately restricted to a test
  environment; it is not production checkout.
- Durable Stars refunds are still a draft migration/workflow (PR #173), not
  production-ready functionality on `main`.
- There is no implemented marketplace commission, seller balance, payout or
  automatic settlement.
- TON escrow integration is still a testnet-only development track. PR #194
  is Draft and explicitly keeps wallet signing disabled.
- The current product/technical decisions do not approve real-value custody,
  checkout, commissions or seller payouts. ADR-0001 remains a proposal and
  Telegram's classification of the exact peer-to-peer NFT resale flow is open
  in Issue #155.

Do not change production flags or bot tokens to make a test harness appear live.

## 2. Three parallel workstreams

| Workstream | Owner | Required output | Must not do |
|---|---|---|---|
| Telegram Stars production readiness | Payment agent | Verified current Telegram policy, accepted production/test separation, support/terms surfaces, secure live webhook, durable refunds, reconciliation and manual operational procedure | Treat platform Stars as seller balances or promise automatic conversion/payout |
| TON escrow testnet readiness | Escrow agent | ABI-backed adapter, provider/observer, idempotent actions, testnet deployment evidence, failure-matrix tests and independent review | Enable mainnet signing or use valuable assets before security/legal gates |
| Production release and revenue model | Release owner | Hardened production Compose checks, operational cutover checklist, explicit fee/payout accounting decision and launch gate report | Deploy secrets, migrate the live database, or activate money flows without owner approval |

## 3. Revenue model decision to validate

The proposed commercial target is a **10% platform fee** on successfully settled
deals. This is a product proposal, not a deployed fee.

### Telegram Stars

- Stars paid through a bot/mini app accrue to the Telegram account that owns
  the bot/TPA. They do not create per-seller balances or automatically split
  between seller and platform.
- Therefore, a 10% accounting entry does not make a seller payout real.
- Any seller settlement from a Stars-funded sale needs a separately approved,
  legally reviewed payout rail and an operational reconciliation process.
- Fragment reward conversion, availability, eligibility and timing are not a
  guaranteed seller payout schedule. Never advertise a fixed conversion rate
  or date as if Vstore controls it.

### TON escrow

If the reviewed escrow contract is approved for production, the intended
settlement is:

- gross deal principal: 100%;
- platform fee: 10% of principal;
- seller net: 90% of principal;
- network/contract execution costs: disclosed and accounted for separately.

The eventual contract must calculate integer nanotons, define deterministic
rounding, bind the fee recipient to reviewed configuration, prevent fee changes
after deal creation, and emit verifiable events for both seller net and platform
fee. Backend accounting must reconcile those exact finalized on-chain amounts.
Do not create an off-chain "seller balance" that can diverge from contract state.

## 4. Launch stages

### Stage A — public marketplace beta (no money)

May be considered only after the normal production cutover and live wallet /
NFT delivery acceptance are complete.

- Listings and moderation work on the production host.
- Wallet proof is verified against the exact public host.
- Live mainnet NFT ownership and transfer flow is manually accepted.
- Clear user copy says reservations do not collect payment and Vstore does not
  provide escrow or buyer protection.
- No Stars checkout, commissions, seller balances or payout claims are exposed.

This stage can validate marketplace demand, but it does not generate transaction
commission revenue.

### Stage B — real Stars checkout

Blocked until all of the following are true:

- Issue #155 has a written platform-policy decision for this exact NFT resale UX.
- Current Telegram Bot Platform Developer Terms and Stars payment/reward rules
  have been rechecked and captured with date/source.
- Live invoice → pre-checkout → successful-payment is manually accepted on the
  correct production bot, with charge reconciliation and duplicate-update tests.
- Refund worker/migration is approved, deployed and manually verified.
- `/paysupport`, `/terms` and support contact are accessible in the product.
- Legal/compliance review and operator procedure explicitly approve who receives
  Stars, who owes the seller, how disputes/refunds are handled, and how payout
  is reconciled.
- Product UI does not imply that Stars are held for the seller or automatically
  paid out to them.

### Stage C — TON escrow and 10% commission

Blocked until:

- Testnet contract deployment and complete failure matrix are independently
  verified with valueless assets and test wallets.
- Contract audit has no unresolved high/critical findings.
- Mainnet custody, dispute, refund, upgrade/admin-key and oracle/resolver
  controls receive independent security and legal approval.
- Fee recipient, 10% rate, rounding, gas treatment and immutable per-deal fee
  snapshot are approved.
- Backend reconciles finalized contract state and actual fee/seller transfers.
- Mainnet deployment, key custody, monitoring, incident response and recovery
  are reviewed and signed off.

## 5. Production cutover checklist

Use `docs/PRODUCTION_DEPLOYMENT.md` as the operational runbook. Before the
cutover, verify:

- [ ] Exact production HTTPS hostname, BotFather Mini App, manifest and icon.
- [ ] TON Connect domain allowlist and CORS use that exact hostname/origin.
- [ ] Production uses `ENVIRONMENT=production` and `TON_CONNECT_NETWORK=mainnet`.
- [ ] Production bot token, auth secret, DB password and provider key are
      separate from Preview/test credentials.
- [ ] Dedicated production PostgreSQL volume is identified and backed up.
- [ ] Backup restore has been tested against a separate database.
- [ ] Alembic migration head is reviewed and applied explicitly.
- [ ] PostgreSQL, Redis and API are not exposed as public host ports.
- [ ] HTTPS reverse proxy, firewall, rate limiting, log retention and monitoring
      are active.
- [ ] Admin allowlist contains only intended numeric Telegram IDs.
- [ ] Telegram mobile WebView, wallet proof, account/network switching and
      notifications are manually accepted.
- [ ] Mainnet NFT transfer and backend finality observer are manually accepted.
- [ ] Terms/support/dispute copy accurately describes the product's limitations.

## 6. Explicit no-go conditions

Do not call the product a real-money marketplace or enable paid purchase if any
of these remain true:

- Telegram's exact NFT resale policy classification is unresolved.
- Stars are described as a seller balance or automatic payout mechanism.
- Refund processing is not durable and manually accepted.
- Escrow signing is enabled without independent contract review.
- The backend cannot reconcile finalized chain evidence for the exact deal.
- The platform fee is only calculated in UI or an unverified database row.
- Production secrets, database or bot token are shared with test/Preview.
- A live deployment or migration has not been backed up and recovery-tested.

**Release status on 2026-11-14: not cleared for real-money launch.** The
marketplace code can proceed through a no-payment production beta after live
wallet/delivery and operations acceptance. Real checkout and fee collection
remain separate gated releases.
