# Issue #225 — current contract security and release-gate assessment

**Assessment baseline:** `main` at `a08b3b7632e1e1d8c38ac7a896b519a595f32df8`  
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
- **New internal finding on current main:** the authorized retry path for `OUTBOUND_KIND_EXECUTION_RESERVE_REFUND` reuses `SEND_MODE_CARRY_ALL_BALANCE` but does not reapply `reserveGramsOnBalance(TERMINAL_STORAGE_RESERVE, ...)`. Since reserve actions apply to the current transaction, a successful retry may consume the terminal storage floor. Remediation and a balance regression assertion are isolated in Draft PR #242; until its frozen artifact is regenerated and exact-head CI passes, treat this as an unresolved financial invariant.

## Exact-head build evidence

Latest contract-specific CI completed successfully on contract commit `2ecf38943216a773dc27fb1841f11edc3ee67b9f` (workflow run `43762485072`). Current `main` is `a08b3b7632e1e1d8c38ac7a896b519a595f32df8`, one commit ahead. The only later commit changes `.env.example`, `backend/app/main.py`, `backend/tests/test_escrow_runtime_gates.py`, and `docker-compose.preview.yml`; it does not change contract source, tests, ABI, frozen artifacts, or the contract workflow. Therefore the cited green contract run still verifies the unchanged contract tree on current `main`; it is not a workflow run on the later preview-only commit. All contract workflow tasks completed successfully, including:

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
The contract pins an exact NFT item address, but collection membership is not proven by the contract. Backend remediation is being developed separately in Draft PR #241: allowlisted item/collection code hashes, same-masterchain-block proof reads, and reconstruction of the standard TEP-62 item address from collection item code and index. The PR has not been merged or CI-accepted, and the allowlist intentionally defaults to empty. No real collection policy or code hashes are configured. Until an operator has reviewed and allowlisted a specific collection, new escrow NFT intents must remain blocked.

### Residual verification to include in independent review
- RichBounce envelope parser assumptions for Tolk 1.5.0, including phase layout, mandatory refs and original-info/value extraction.
- Two-slot descriptor capacity and every path that can create principal + secondary refunds.
- Carry-all reserve refund failure/retry behavior, including action ordering, fees and bounce-after-terminal scenarios.
- Retry authorization when the fixed recipient is a contract wallet, and the economic consequences of retrying a carry-all action after a bounce.
- Invariants under action-phase failures, malformed/out-of-order/duplicate bounces, and backend observer restart/replay.
- Whether source-level custody flags are intentionally conservative projections and how trusted getter/trace reconciliation verifies actual NFT ownership.

### BLOCKED — contract balance floor after carry-all retry
The current `main` retry helper reissues the carry-all execution-reserve refund without a new storage reserve action. Draft PR #242 adds the reserve action to the retry transaction and checks the escrow balance after bounce and retry. The code fix is not yet merged, and the frozen code hash/BOC manifest must be regenerated with pinned CI before merge.

## Release posture

**BLOCKED — do not enable production transaction preparation, signing, broadcast, mainnet, real funds or real NFT transfers.** Keep testnet/valueless scope only. This report records source and CI evidence; it does not grant release approval or claim testnet acceptance.
