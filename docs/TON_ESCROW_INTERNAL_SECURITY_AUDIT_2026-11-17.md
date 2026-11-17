# VILTARA TON Escrow — internal adversarial security audit

**Date:** 2026-11-17  
**Scope:** static source review of DealEscrow v1, its Acton emulator suite and the TON backend proof/observer integration.  
**Reviewed main baseline:** `4e1308426591f1f023d6827d8744827efe4ce9f9`  
**Reviewed PR #257 frontend head:** `13c94bc06b994806b5f65bfdcf0e500082eb8bd7` (frontend-only changes; audited contract/backend sources below are unchanged from main).  
**Classification:** internal engineering audit; not an independent third-party audit, legal opinion or live-network acceptance.

## Executive decision

**Release status: BLOCKED.** I found two high-priority issues that should be fixed before any public/paid deal flow:

1. A post-delivery buyer can open a dispute, retain or transfer away the NFT, and leave the seller's principal locked indefinitely. The resolver cannot decide while the NFT is not back in escrow.
2. The backend proof observer does not recognize `RetryFailedOutboundAction` opcode `0x56450009`. The discovery cursor advances past unknown opcodes, so an on-chain retry transaction can be permanently skipped and the durable wallet action will not be finalized by the observer.

One medium-priority terminal-state integrity issue is also described below.

This review was performed against source and repository evidence through GitHub. I did not execute a new local compiler/emulator run in this session, deploy to TON testnet, or independently reproduce proof verification. CI evidence is useful but does not replace those steps.

## Exact source identity

| Component | Path | Git blob SHA |
|---|---|---|
| Contract | `contracts/ton-escrow-poc/contracts/DealEscrow.tolk` | `a18506283417bad02e562a69080f4b1b177708f5` |
| Protocol types | `contracts/ton-escrow-poc/contracts/types.tolk` | `d410ec5cca348cffab1c766cd38fb7a3174deb9d` |
| Signature helpers | `contracts/ton-escrow-poc/contracts/signatures.tolk` | `67453fc0789efa403e366b33998ee82323413465` |
| Contract tests | `contracts/ton-escrow-poc/tests/DealEscrow.test.tolk` | `98ed0fcda81b32eca5d4dad50d4990f9a44bd557` |
| Frozen manifest | `contracts/ton-escrow-poc/artifacts/frozen/manifest.json` | `ff006c4450c53534a8610666ea72fdd393a2a4c2` |
| Backend finality provider | `backend/app/escrow/finality_provider.py` | `cc6ca26f7e0db9a7f2413b4f1a7c16c54d707d8d` |
| Backend observer | `backend/app/escrow/observer.py` | `efb6faf1ff7f080105703b579f307b30a6ed9af9` |
| Backend event types | `backend/app/escrow/domain.py` | `c11f9e148378f094897765712542e6e78cbcb906` |

The frozen manifest identifies DealEscrow v1, TON testnet, Acton 1.2.1 / Tolk 1.5.0, code hash `498A82F9B2DE206BE42108B6413D517CE63D4BCB1C20704D0BD89FCCC9509C46`, BOC SHA-256 `86ed08596d0595c711aa2cf7659ee396ff443d7b01c65659b8e7543dd23c6173`, ABI SHA-256 `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028`, fixed-vector StateInit hash `4e3845e9d0b4df2f603b0ba7cceca4592276d25d8f43d2c611376344db393f75`. The fixed StateInit vector is a fixture, not a universal per-deal address.

## Findings

### VLT-001 — HIGH: Post-delivery dispute can permanently lock seller principal if buyer does not return NFT

**Affected code**
- `DealEscrow.tolk:1156-1180` — buyer can open post-delivery dispute while NFT remains with buyer; contract starts a return window.
- `DealEscrow.tolk:855-893` — resolver path requires `progress.nftInEscrow && progress.principalLocked`, for both resolver outcomes.
- `DealEscrow.tolk:1247-1255` — if the post-delivery dispute times out with NFT outside escrow, `TimeoutDeal` moves to `MANUAL_REVIEW`.
- `DealEscrow.tolk:528-538` — the only late recovery into the resolver path requires the exact configured NFT to return from the snapshotted buyer with the fixed return query ID.

**Reproduction from code**
1. Seller deposits NFT; buyer funds and accepts; oracle confirms delivery. NFT is now owned by buyer, principal remains locked pending seller settlement.
2. Before the dispute window closes, buyer submits `OpenDispute`. This is permitted in `STATE_DELIVERED_DISPUTE_WINDOW`; `nftInEscrow` is false.
3. Buyer does not return the NFT. They may simply withhold it or transfer it to another wallet, making the fixed `oldOwnerAddress == roles.buyer` return condition impossible.
4. After the return deadline anyone may call `TimeoutDeal`; the contract falls back to `STATE_MANUAL_REVIEW` and clears the deadline.
5. `ResolveDispute` still fails because the NFT is not in escrow. The only route back to `STATE_DISPUTED` is the buyer's exact NFT return. There is no seller-default, resolver seller-win, or other terminal settlement path while the item remains with buyer.

**Impact**

A buyer can use the post-delivery dispute window to block seller proceeds without returning the NFT. If the buyer transfers the NFT away, the return precondition may become permanently unsatisfiable. Principal stays locked and the deal cannot reach seller payout or buyer refund. This is a high-severity availability/economic-griefing risk, even though the buyer does not directly withdraw the locked principal.

**Recommended correction**

Define and implement an explicit post-delivery arbitration outcome that does not require taking custody back when the buyer already owns the delivered NFT:
- For a resolver decision of **seller wins**, require proof-backed confirmation that the snapshotted buyer still owns the exact snapshotted NFT (or another clearly specified delivery/ownership predicate), then initiate seller payout directly. Do not require an NFT round-trip through escrow.
- For **buyer wins**, continue to require return of the exact NFT to escrow before principal refund.
- Define a permissionless terminal default after the return window if buyer does not return the NFT; do not leave funds in an unbounded manual-review state.
- Update contract, backend `_decode_resolver_decision` state expectations, observer projection and emulator tests together. Add an adversarial test where the buyer transfers the NFT to a third party after opening a post-delivery dispute and prove the seller-win path can still settle safely (or prove a documented alternate resolution).

Do not simply remove the `nftInEscrow` assertion for both outcomes; buyer-win refund must never be paid while buyer retains the NFT.

### VLT-002 — HIGH: Backend observer silently skips retry opcode 0x56450009

**Affected code**
- Contract declares `RetryFailedOutboundAction` as opcode `0x56450009` in `contracts/ton-escrow-poc/contracts/types.tolk`.
- `backend/app/escrow/finality_provider.py:75-78` defines action opcodes only through `_OP_RECOVER = 0x56450008`; no retry opcode is defined.
- `finality_provider.py:107-115` omits retry from `_DIRECT_OPCODES`.
- `finality_provider.py:244-270` `_candidate_type` has no retry mapping.
- `finality_provider.py:525-544` advances the per-account logical-time discovery cursor for each selected transaction, then skips a transaction when its opcode has no candidate event.
- `backend/app/escrow/domain.py` has no verified retry event.
- `backend/app/escrow/observer.py:704-713` has no mapping from a verified retry event to the durable `retry_failed_outbound_action` wallet action type.

**Impact**

The contract can successfully execute a recipient-authorized retry, but the backend observer does not discover that inbound wallet transaction as a candidate. Because the discovery cursor has already advanced, the transaction is not naturally re-scanned later. The associated durable wallet action can remain prepared/submitted/ambiguous rather than finalized; the backend projection and UI can stay stale even though the contract created a fresh pending outbound action.

This breaks the operational recovery path for failed payouts/refunds/NFT transfers and makes the backend unable to reliably reconcile retry completion.

**Recommended correction**

- Add `_OP_RETRY = 0x56450009` and a dedicated candidate/event type.
- Decode the retry body strictly as query ID + deal salt; bind sender to the prior descriptor's exact recipient using the prior proof-read state / persisted prepared action.
- Verify the resulting post-transaction getter has the expected fresh PENDING descriptor with a new monotonic attempt/query ID and exact action kind/recipient/body semantics. Do not trust indexer query IDs or a client reference.
- Add observer action mapping for `retry_failed_outbound_action`, with collision/manual-review handling consistent with existing durable wallet actions.
- Add provider discovery, proof verification, observer reconciliation, cursor-resume and negative tests. Include a same-SHA CI run.

The existing generic `_decode_direct_body` can decode the query ID and deal salt, but retry needs an explicit state-transition verifier: the input references the old bounced descriptor, while the post-state contains its replacement descriptor.

### VLT-003 — MEDIUM: An unexpected NFT callback can overwrite a terminal financial state

**Affected code**
- `DealEscrow.tolk:565-585` accepts the configured NFT item's unexpected callback by setting `nftInEscrow = true`, recording a recovery owner/item and calling `asManualReview(progress)`.
- There is no guard here for `STATE_SETTLED`, `STATE_REFUNDED` or `STATE_EXPIRED`.

**Scenario and impact**

After a deal is settled/refunded/expired, the current NFT owner can transfer that exact item to the old escrow address (including accidentally). If the callback is not one of the narrowly expected deposit/return cases, the contract changes the deal's state from terminal to `MANUAL_REVIEW`. This conflates a new, unsolicited NFT recovery with the already completed financial lifecycle. The previous owner can initiate the recovery route, but the historical terminal state is lost from the single `state` field and backend projections may interpret a completed deal as reopened/manual review.

This is not evidence of principal theft; it is a state-integrity and operational-reconciliation defect.

**Recommended correction**

Separate financial terminal state from unsolicited-asset recovery status. Preserve the terminal settlement state and record an independent recoverable-NFT flag/record; permit the previous owner to recover the unsolicited item without reopening principal or seller/buyer settlement. Add tests for unsolicited configured-NFT transfer after each terminal state and verify financial terminal invariants remain unchanged.

## Positive controls observed

- Contract tests use deterministic `crypto.rawSign` fixtures for positive oracle/resolver paths. The current `DealEscrow.test.tolk` contains **zero** `testing.setChecksigIgnore` calls; zero signatures appear in negative-test fixtures only.
- Contract validates testnet network/global ID, protocol version, basechain workchain, non-zero distinct oracle/resolver keys and cross-set key separation.
- Funding is constrained to exact principal plus execution reserve; the NFT item address, expected seller/buyer, fixed query IDs and inline deal-salt payload are checked.
- Outbound descriptors bind action kind, destination/recipient, query/attempt, salt, amount/value and original message-body hash. RichBounce matching is stricter than a generic bounce flag.
- Backend provider deliberately uses trust-level-zero LiteServer proof paths and treats TON Center v3 as candidate discovery only; unsigned TON Connect is kept separate from signing/broadcast.
- NFT collection/item admission uses proof-read code/data cells, explicit allowlist policy and deterministic TEP-62 item address derivation. The allowlist being empty by default is a useful fail-closed control.

These controls reduce risk but do not neutralize VLT-001 or VLT-002.

## Coverage gaps / required adversarial tests

1. Post-delivery dispute where buyer never returns NFT, and where buyer transfers it to a third-party wallet before timeout.
2. Retry opcode discovery and finality reconciliation from wallet transaction through observer to `EscrowWalletActionRecord`; verify cursor advancement does not lose it.
3. Unsolicited NFT transfer to a terminal escrow; prove settled/refunded/expired financial state cannot be reopened.
4. Valid-signature full end-to-end combinations for both resolver outcomes, both dispute phases, payout/refund bounce, retry bounce, duplicate/stale attestations and exact deadline edges. The current suite has valid signed builders and broad cases, but the specific adversarial situations above are not covered.
5. Live testnet acceptance with disposable wallets and a valueless NFT, trusted masterchain anchors, transaction/message traces, getters, owner proofs, balances and reserve-floor calculations.

## Existing CI evidence (not a substitute for this audit)

PR #257 exact head `13c94bc06b994806b5f65bfdcf0e500082eb8bd7` passed:
- Backend CI: 970 tests.
- TON Contract CI: 35/35 Acton Sandbox tests and frozen-artifact checks.
- Frontend unit tests: 256/256.
- Standard Playwright: 31/31.
- Escrow retry E2E: 1/1.
- API-backed E2E: 4/4.

PR #257 changes frontend files only. These passing checks do not test the missing backend retry opcode (provider discovery/observer tests are separate from the frontend retry E2E), do not include the never-return post-delivery dispute scenario, and do not prove live testnet behavior.

## Release recommendation

**Do not enable paid checkout or real-value NFT/TON transactions.** Fix VLT-001 and VLT-002, address VLT-003, add adversarial regression tests, and obtain an independent TON/Tolk audit on the corrected exact source/artifact hashes. Then complete live, valueless TON testnet acceptance. The repository remains testnet-only; no signing, custody, automated broadcast or mainnet authorization is implied by these findings.
