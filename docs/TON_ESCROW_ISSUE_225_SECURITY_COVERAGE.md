# Issue #225 — TON escrow contract security and lifecycle follow-up

**Baseline:** `main` at `6dafdcf4c462718df14ea024f29fd277c90f6d39`  
**Scope:** contract-only review package. No ABI, storage, opcode, frozen BOC, backend payment/provider or deployment changes are made here.

## Executive status

The contract is a testnet-only immutable single-deal PoC. The repository has a reproducible Acton/Tolk build and 25 emulator tests, but the present evidence is insufficient to call it a defensible testnet release candidate. This report distinguishes implemented guards from behavior that is not yet proven.

## Implementation update — PR #234 (2026-11-15)

The initial findings below describe the pre-implementation baseline. The implementation branch has since added:

- A persisted two-slot outbound-action descriptor. Each action includes kind, exact destination/recipient and item/response addresses, query ID and monotonic attempt ID, deal salt, amount/value, expected state/pending action, retry window and original outbound body hash.
- RichBounce-only correlation: match the bounce sender/destination, exact original body hash and original message value. Classic/short bounces, unknown descriptors, stale envelopes and mismatches do not mutate state.
- A correlated critical bounce records phase and exit code, preserves NFT/principal custody flags, and moves to manual review. It does not infer finality from a bounce.
- `RetryFailedOutboundAction` opcode `0x56450009`: only the descriptor's snapshotted recipient may retry; the failed descriptor is consumed, a fresh monotonic attempt/query ID is used, and old-query replay is rejected.
- Positive lifecycle oracle/resolver fixtures now sign each exact typed-cell hash using deterministic Acton `crypto.rawSign` test seeds; the test file contains no `testing.setChecksigIgnore` calls. Deliberately invalid zero-signature fixtures remain only in negative tests.
- Actual failing TEP-62 item transfer and seller payout destination emulator scenarios. NFT retry succeeds and is attested with a signed oracle message; payout bounce preserves `principalLocked=true`. Unauthorized retry and replay tests are included.
- The `DealProgress` storage extension changes StateInit and every derived deal address. The new frozen ABI/manifest and StateInit/message vectors are regenerated from Acton 1.2.1 / Tolk 1.5.0.

### Exact-head validation

The final exact-head run [#43732705509](https://github.com/AzizIo/Vstore/actions/runs/43732705509) on `61755265e85f5f136d22f2414b350d65b55c9549` passed **all steps with no continue-on-error bypass**: frozen ABI verifier, fresh build/code/BOC comparison, generated wrappers, independent StateInit/address/data-hash cross-check, message BOC vectors, `acton fmt --check`, `acton check`, and the full emulator suite. This run also includes the unauthorized-retry and old-query replay assertions. The action uploaded reproducible artifact `14168644387` (archive SHA-256 `d39f01b327ba575c8d5558e1ef6eb3417fde97458de45b8727fff0f5c7157f7d`). The suite contains 26 emulator tests; the signed end-to-end test cases no longer disable checksig.

### Remaining gates

- Extend the emulator failure matrix to secondary seller allowance and carry-all reserve-refund bounces, plus out-of-order/mismatched RichBounce envelopes.
- Expand timeout/recovery state × custody × principal/reserve matrix beyond the current boundary tests.
- Independent TON/Tolk audit and actual valueless testnet transaction traces/getter reconciliation are not performed.
- Collection authenticity is not proven in contract; a trusted provider must verify exact item's collection getter before immutable deployment terms are accepted.

## Confirmed findings

### HIGH — bounced outbound actions are not correlated to their originating action

`contracts/DealEscrow.tolk:onBouncedMessage` currently ignores its `InMessageBounced` argument. It preserves already terminal states, but moves every non-terminal state to `STATE_MANUAL_REVIEW`. It does not validate or correlate the bounced message's original body, destination, query ID, deal salt, action type or attempt ID.

The current test named `test bounced internal action forces manual review` sends a bounced `TimeoutDeal` body into the handler. It does not produce a bounce from one of the contract's actual outbound messages (TEP-62 NFT transfer, seller payout or buyer refund). Therefore the test demonstrates a fail-closed state transition only; it does not prove outbound-action correlation or recovery.

**Impact/precondition:** any bounced message reaching the contract while it is non-terminal freezes the deal, including unrelated/stale bounces. The handler cannot distinguish a principal payout failure from NFT transfer failure or a secondary reserve-refund failure. This avoids automatic duplicate settlement but leaves no action-specific recovery path and can hide malformed/forged bounce-envelope scenarios behind the same generic state.

**Required remediation before enabling:** inspect the exact Tolk `InMessageBounced` envelope semantics for pinned Tolk 1.5.0 and the compiler-generated ABI; introduce an explicit persisted outbound-action descriptor (kind, destination, query ID, deal salt, attempt, amount and expected state) and clear it only on matching finalized reconciliation. A bounce must be accepted only when it is cryptographically/structurally a bounce from the recorded outbound message and matches that descriptor. An unknown or mismatched bounce must never mutate principal/NFT state. Do not implement this as a source-only patch: it changes storage semantics and likely requires ABI/BOC/StateInit vectors and a fresh independent review.

### HIGH — lifecycle tests bypass signature verification

`contracts/ton-escrow-poc/tests/DealEscrow.test.tolk` has a focused Ed25519 helper test with fixed public keys and signatures. However, multiple end-to-end oracle and resolver lifecycle scenarios call `testing.setChecksigIgnore(true)` around the state-changing message and then restore it. Test helpers `buildTestOracleAttestation` and `buildTestResolverDecision` populate zero signatures.

**Impact:** end-to-end scenarios prove state-machine branches given signature-check bypass, not that the full message-cell digest, domain-separated data and signatures work together across delivery, dispute, payout, refund and timeout paths. The helper unit test proves only the signature-counting function for one fixed digest/key combination.

**Required remediation before enabling:** build deterministic end-to-end fixtures that sign each exact `OracleAttestationData.hash()` / `ResolverDecisionData.hash()` with at least two independent test Ed25519 private keys (held only in test fixtures), verify the positive flows without `checksigIgnore`, and add mutation tests for altered domain/network/address/salt/action/attempt/route/amount/evidence, wrong key slot, duplicate signer, stale attempt and expired deadline. Retain bypass tests only for narrow state-machine fault injection and mark them explicitly as such.

### HIGH — actual outbound bounce and transaction action-phase failure matrix is absent

The source sends NFT transfers, principal payout/refund and secondary refunds with `SEND_MODE_PAY_FEES_SEPARATELY + SEND_MODE_BOUNCE_ON_ACTION_FAIL`. The reserve-refund path also uses `SEND_MODE_CARRY_ALL_BALANCE`. Current tests cover generic bounce-to-manual-review and terminal-state protection, but do not prove the full behavior for each actual outbound action, including action-phase failure vs a delivered bounce, nor assert principal balance, reserve balance and NFT owner for every failure branch.

**Required remediation:** add emulator scenarios that cause the real outbound TEP-62 item and TON recipient calls to fail/bounce, then assert transaction action-phase result, resulting escrow state, NFT owner, principal custody, reserve and all query/attempt identifiers. Cover late duplicate and out-of-order bounces, especially secondary reserve refunds after terminal reconciliation. The test should fail if an unsupported action is treated as confirmed settlement.

### MEDIUM — collection authenticity is not established by the contract

The immutable terms include both `itemAddress` and `collectionAddress`, but the contract's custody/notification trust decision is pinned to the exact item address. The collection value is retained as terms metadata and is not itself a proof that the item is a member of that collection.

**Impact/precondition:** an incorrectly configured deal can pin an arbitrary item contract while the UI/backend describes it as a member of the stated collection. The PoC's own README explicitly narrows trust to the exact configured item address and states that collection authenticity must be handled outside this contract.

**Required remediation:** before creating immutable terms, a trusted testnet provider must verify the item contract's collection getter against the intended collection and retain the finalized proof in the signed deployment approval package. Do not present a collection name or off-chain metadata as proof.

### MEDIUM — timeout/recovery coverage is not a complete state/action matrix

The timeout entry point implements separate branches for `STATE_AWAITING_NFT`, `STATE_AWAITING_BUYER_FUNDS`, `STATE_FUNDED_REVIEW` and `STATE_DELIVERED_DISPUTE_WINDOW`; other states go to manual review. The tests cover important timeout boundaries and a subset of transitions, but do not prove all outbound timeout continuations and failure paths together with exact balances, NFT owner, and replay resistance.

**Required remediation:** create a state × time-boundary × custody × principal-lock matrix. Include exact deadline and +1 second, zero/missing/incorrect salt, non-buyer caller, duplicate timeout, timeout during each pending reconciliation, NFT return failure, and payout/refund bounce. Assert no terminal transition while NFT/TON transfer is merely requested rather than finalized.

## Existing defenses observed

- Mainnet global ID is explicitly rejected (test/local global ID is -3).
- Per-deal terms snapshot seller, buyer, exact item, collection reference, deal salt, principal/reserve/refund parameters, query IDs and distinct oracle/resolver public-key sets.
- Funding requires exact principal + execution reserve and the exact configured item deposit before buyer funds are accepted.
- The contract does not expose arbitrary recipient withdrawal or an upgrade/owner-withdraw method.
- Oracle/resolver decisions are domain/version/network/escrow/deal/attempt bound and require a 2-of-3 Ed25519 quorum in contract logic.
- Delivery, payout and refund are held in pending states until oracle attestations are accepted.
- Terminal states are protected from late bounced-message mutation.
- Frozen ABI/BOC, deterministic StateInit/address and message-vector verification exist in CI.

These are source-level observations; they do not replace an independent audit or live testnet evidence.

## Frozen artifact baseline

The frozen source manifest pins Acton 1.2.1 and Tolk 1.5.0, code cell hash `359B02C177CE033C6FE1A673C4E04B59D6D43434AF09B1CBE4BDCD8BE4779450`, base64 BOC SHA-256 `9dcf1449971a1ba69e5bf59a3feac5f290eeeac011da84e279f4d93cb8be8041`, decoded BOC SHA-256 `df82a5603142e77344b3f201c13d6c77d3900893bf06cfe719bece784caf0422` and compact ABI SHA-256 `25fc5f338f45db7d7198961a75c1d5cfe04f996ae36013cca0d70f03870c3923`.

This PR does not alter frozen contract source, storage, ABI or compiled artifact.

## Testnet acceptance plan — not executed

1. Independent reviewer verifies source commit, toolchain, ABI, code BOC, StateInit and all deterministic address/message vectors.
2. Release operator approves a valueless testnet deal identity: network global ID -3, exact code hash, StateInit hash/address, seller, buyer, item and collection. Verify item-to-collection relationship from the finalized item getter.
3. Use independently generated test-only oracle and resolver keys. Keep private keys outside the backend and contract repository; publish only public key fingerprints in the evidence package.
4. Record finalized deploy/activation/deposit/funding/acceptance/delivery traces and all contract getters at an explicit masterchain checkpoint.
5. Exercise pre-delivery and post-delivery disputes, both resolver outcomes, deadline edges, NFT return, payout, refund, timeout and all outbound failure/bounce scenarios. Record transaction/message/trace hashes, getter snapshots, balances and item owner at each checkpoint.
6. Reconcile every accepted contract transition against the finalized trace, including retries/restarts and duplicate evidence.
7. Attach an independent security review with no unresolved critical/high findings and obtain release-lead approval.

**Not performed:** no testnet transaction was broadcast; no live testnet provider/finality integration was exercised; no NFT was transferred; no real funds, mainnet, private key, signing service or production deployment was used.

## Release decision

**BLOCKED — not a testnet release candidate yet.** The blocking gaps are operation-aware outbound bounce correlation/recovery, signed end-to-end lifecycle coverage, actual outbound action-failure invariants, complete timeout matrix and independent contract review. CI/emulator results and frozen artifact reproduction are necessary but not sufficient.
