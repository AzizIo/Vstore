# Issue #225 — current contract security and release-gate assessment

**Assessment baseline:** `main` at `2ecf38943216a773dc27fb1841f11edc3ee67b9f`  
**Contract source:** `contracts/ton-escrow-poc/contracts/DealEscrow.tolk`  
**Test source:** `contracts/ton-escrow-poc/tests/DealEscrow.test.tolk`  
**Toolchain:** Acton 1.2.1 / Tolk 1.5.0  
**Assessment type:** source-level follow-up to the merged remediation; not an independent audit.

## Verified implementation on current main

The source currently contains the action-aware contract changes merged through PR #235:

- Two persisted outbound-action slots with action kind, exact destination/recipient and response route, query/attempt ID, deal salt, amount/value, expected state/pending action, retry window, body-cell hash and bounce phase/exit code.
- RichBounce-only matching against the persisted message body hash, sender/destination and original message value. A matched critical bounce records failure and preserves principal/NFT custody projection; unknown or malformed envelopes are ignored.
- Recipient-authorized retry consumes the failed descriptor and uses a fresh monotonically increasing oracle attempt/query ID.
- Oracle/resolver positive fixtures use deterministic test-only Ed25519 signatures; source tests no longer use checksig bypass for positive end-to-end paths.
- Timeout-to-manual-review can be reconciled by a valid signed oracle attestation only for an exact still-PENDING action. A BOUNCED action cannot use late success and must be retried.
- Emulator tests cover late NFT delivery and seller payout after timeouts, late NFT return and buyer refund after timeouts, real NFT transfer bounce, seller payout bounce, seller deployment allowance bounce, carry-all reserve refund bounce/retry, stale retry rejection and terminal state protection.

## Exact-head build evidence

Post-merge Contract CI on main commit `2ecf38943216a773dc27fb1841f11edc3ee67b9f` completed successfully (workflow run `43762485072`). All 16 job steps completed, including:

1. Frozen artifact verifier unit tests and ABI snapshot verification.
2. Acton build and generated code/BOC comparison against the frozen manifest.
3. ABI wrapper generation.
4. Independent StateInit/address/data-hash comparison using Acton wrapper and `@ton/core`.
5. ABI message BOC golden vectors.
6. Tolk formatting, static checks and emulator suite (30 tests).

This confirms reproducibility for the current artifact baseline. It is emulator/CI evidence only.

## Remaining contract/release gates

### BLOCKED — independent TON/Tolk security review
No independent reviewer report is attached. Internal source inspection and emulator success do not satisfy the independent-review requirement. Reviewer must record qualifications, exact source SHA, ABI/code/StateInit/BOC hashes, findings with severity, exploit preconditions and reproducible tests.

### BLOCKED — valueless live testnet acceptance
No live deployment or transaction/trace evidence was presented for this assessment. Acceptance still requires explicit owner approval, disposable wallets and valueless assets; finalized transaction/message/trace hashes, masterchain inclusion proof, getter snapshots, balances/fees, NFT owner and authorized retry traces. Do not imply emulator tests demonstrate chain finality.

### BLOCKED — trusted collection membership before immutable terms
The contract pins an exact NFT item address, but collection membership is not proven by the contract. Before creating immutable terms, a trusted testnet provider/release process must verify the item’s collection getter against the intended collection and retain finalized evidence in the approval package. The current contract-only PoC does not independently establish that trust decision.

### Residual verification to include in independent review
- RichBounce envelope parser assumptions for Tolk 1.5.0, including phase layout, mandatory refs and original-info/value extraction.
- Two-slot descriptor capacity and every path that can create principal + secondary refunds.
- Carry-all reserve refund failure/retry behavior, including action ordering, fees and bounce-after-terminal scenarios.
- Retry authorization when the fixed recipient is a contract wallet, and the economic consequences of retrying a carry-all action after a bounce.
- Invariants under action-phase failures, malformed/out-of-order/duplicate bounces, and backend observer restart/replay.
- Whether source-level custody flags are intentionally conservative projections and how trusted getter/trace reconciliation verifies actual NFT ownership.

## Release posture

**BLOCKED — do not enable production transaction preparation, signing, broadcast, mainnet, real funds or real NFT transfers.** Keep testnet/valueless scope only. This report records source and CI evidence; it does not grant release approval or claim testnet acceptance.
