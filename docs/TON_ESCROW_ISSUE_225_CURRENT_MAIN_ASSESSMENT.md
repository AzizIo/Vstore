# Issue #225 — current contract security and release-gate assessment

**Assessment baseline:** `main` at `525215b9a51a34be811e73a1cc26995cd3cb25a1`  
**Contract:** `contracts/ton-escrow-poc/contracts/DealEscrow.tolk`  
**Tests:** `contracts/ton-escrow-poc/tests/DealEscrow.test.tolk`  
**Toolchain:** Acton 1.2.1 / Tolk 1.5.0  
**Assessment class:** internal source and CI follow-up; not an independent audit.

## Verified implementation on current main

The current contract includes the merged PR #235 lifecycle, RichBounce, signed-oracle and finality work, plus the following:

- Two persisted outbound-action descriptors bind action kind, route/recipient, query/attempt, deal salt, amount/value, expected state and original message body hash.
- Only exact RichBounce envelopes matching the recorded outbound action are correlated. Unknown, malformed, stale or mismatched bounce messages do not advance custody or principal state.
- A correlated critical bounce preserves conservative NFT/principal custody flags and can only be retried by the snapshotted recipient with a fresh monotonic attempt/query ID.
- Positive oracle/resolver lifecycle fixtures use deterministic test-only Ed25519 signatures; positive end-to-end tests do not disable signature checks.
- A still-PENDING action can be reconciled by a valid signed oracle attestation after timeout/manual review. A BOUNCED action cannot use a late-success shortcut and must be retried.
- Timeout/late-finality coverage includes NFT delivery, seller payout, NFT return and buyer refund. Emulator tests also exercise actual mock NFT transfer bounce, seller payout bounce, seller allowance bounce, carry-all reserve refund bounce/retry, stale retry rejection and terminal-state protection.
- **Merged PR #242** fixes terminal storage-floor loss when retrying a bounced `OUTBOUND_KIND_EXECUTION_RESERVE_REFUND`: the retry transaction re-applies `reserveGramsOnBalance(TERMINAL_STORAGE_RESERVE, ...)` before `SEND_MODE_CARRY_ALL_BALANCE`. Its regression checks the escrow balance remains above 0.009 TON before and after retry. It was merged as `e003dc5ae82f2beb55fb2277361588267a70f21e`.
- **Follow-up PR #244** fixes the analogous gap for a bounced `OUTBOUND_KIND_SELLER_DEPLOYMENT_REFUND`, whose fixed-value retry is also a new transaction. It re-reserves the terminal storage floor and adds balance assertions before/after retry. PR #244 is still Draft and unmerged; it changes compiled code hash/BOC but not storage, ABI or opcodes.

## Current-main artifact and exact CI evidence

Current main `525215b9a51a34be811e73a1cc26995cd3cb25a1` is one documentation-only commit ahead of the PR #242 merge commit. It does not change contract source, contract tests, ABI or frozen artifacts.

The post-merge Contract CI run [#43767167484](https://github.com/AzizIo/Vstore/actions/runs/43767167484) succeeded on merge commit `e003dc5ae82f2beb55fb2277361588267a70f21e`. All steps passed: frozen verifier, ABI snapshot, Acton build, code/BOC comparison, wrapper generation, independent StateInit/address/data-hash comparison using `@ton/core`, message BOC vectors, Tolk format/static checks and 30 emulator tests. Artifact: `14182617730`, archive SHA-256 `5551e8d8f4c025e58561c751eae75a515a67beabfeabdeabad08afef97b4453c`.

Current main frozen manifest (Acton 1.2.1 / Tolk 1.5.0):

| Artifact | Current-main frozen value |
|---|---|
| Compiled code hash | `1BCCBF586878F8032F4E860707B0102EC554B4E1C0CFD7DEA362E1DD391D6666` |
| BOC base64 SHA-256 | `2ba55420e6b09c94986d51b045db92959df11f66b339cd77df4e919d30a0e50b` |
| Decoded BOC SHA-256 | `b4a46ef78089119fb10272e1edbd152f8b5e9c337b59d759ad5e1c661dd4fbb5` |
| Compressed BOC SHA-256 | `57eec30799e23fe30b3d54c4407949ae99c1af8ebe921e2ce053d1d4f17c80f3` |
| Compact ABI SHA-256 | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| StateInit hash test vector | `ffd464daa07d4fd3b99e2469520eb77624f3265de9784d103df3babc15c5199f` |
| Raw address test vector | `0:ffd464daa07d4fd3b99e2469520eb77624f3265de9784d103df3babc15c5199f` |
| Initial data hash | `faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b` |

The raw address above is a deterministic test vector, not a deployed address.

### Follow-up PR #244 candidate artifact

PR #244 is based on current main and adds the seller allowance retry floor fix. Its exact-head Contract CI [#43767931853](https://github.com/AzizIo/Vstore/actions/runs/43767931853) passed at `69938cd0226f2079b8b8225f54d645770bffe897`: strict code/BOC manifest comparison, wrappers, StateInit/address/data hash, message vectors, format/static checks and 30/30 emulator tests. Coverage: 85.2% lines, 64.5% branches. Artifact `14183122192`, archive SHA-256 `b5c7d011004098ccbeaef48aeaec230231c6531a5554d17937972d7f3ec9edf0`.

| Artifact | PR #244 candidate value (not yet main) |
|---|---|
| Compiled code hash | `9011F274BC3D7E32B76A17F13FCBA17AC49429BB4EECBC4AB97FA202BDAC2940` |
| BOC base64 SHA-256 | `f8da91f71e363585823060fcfb75d9fe579e449f3e74551bbba6b142a7e98149` |
| Decoded BOC SHA-256 | `f9ae570bf2808556a1be9dee8e804d95f6c9f427ecfcfd3edb06b029490c8607` |
| Compressed BOC SHA-256 | `58a888105143cf27c02e5beae8d724fca92fb7b89f00c77fbfc54ad5828cf365` |
| Compact ABI SHA-256 (unchanged) | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| StateInit hash test vector | `674227296eff6ac5ee02c8e2eaa12857ac339d10a9ed7f4f7ea0591e7b4adfca` |
| Raw address test vector | `0:674227296eff6ac5ee02c8e2eaa12857ac339d10a9ed7f4f7ea0591e7b4adfca` |
| Initial data hash (unchanged) | `faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b` |

The PR #244 address is also only a deterministic test vector. Do not use it as a deployment identity. The new code hash and compressed BOC require the #206 backend artifact/runtime hash pin to be updated and reviewed before adapter activation.

## Remaining release gates

### BLOCKED — independent TON/Tolk security review

No independent reviewer report has been attached or commissioned. Internal review and CI are not independent audit evidence. The reviewer must be independent of the implementation author, release operator and oracle/resolver signers, and must bind a written report to the exact final source, ABI, code, BOC and StateInit hashes.

### BLOCKED — trusted NFT collection membership

Backend identity/membership work is isolated in Draft PR #241 under #213. It adds allowlisted item/collection code hashes, same-trusted-masterchain-block account proof reads, TEP-62 item state parsing and reconstruction of the item address from collection item code and index. Its allowlist is empty by default and no real collection policy/code hash is configured. The #213 owner is continuing to update PR #241; multiple backend/frontend CI runs have been cancelled and restarted as new commits land. The latest branch head changed again while this handoff was being refreshed, and no green exact-head backend/frontend/API acceptance result is available yet. A preceding backend attempt found Ruff `I001` import ordering in `tests/escrow/test_escrow_finality_provider.py`; migration 0020 upgrade/downgrade passed, but tests were skipped. The owner was notified. Do not describe collection verification as accepted until a stable exact-head CI run is green and an operator approves a concrete collection policy.

### BLOCKED — valueless live TON testnet acceptance

No actual DealEscrow deployment, transaction hash, trace, masterchain inclusion proof, getter snapshot or on-chain NFT owner transition has been recorded. The deterministic StateInit addresses above are test vectors only. No approved disposable wallets, valueless item/collection, or independent oracle/resolver operators are configured. No testnet transaction has been signed or broadcast.

### BLOCKED — backend artifact/runtime synchronization

#206 owns `backend/app/escrow/abi_artifacts/DealEscrow.code.boc.zlib.b64` and runtime code-hash validation. Current main uses the D822… artifact from merged #242. The PR #244 candidate uses code hash `9011F274…` and compressed BOC SHA-256 `58a888…`. Keep adapter/action preparation fail-closed until #206 explicitly updates and reviews that pin.

## Residual review scope

- RichBounce envelope parser assumptions for pinned Tolk 1.5.0: phase layout, mandatory refs, original-info/value extraction, malformed and truncated cases.
- Two-slot descriptor capacity and every primary + secondary refund path.
- Both retry actions: carry-all execution-reserve refund and fixed seller deployment allowance refund; fee mode, reserve ordering, bounce after terminal settlement, recipient contract wallet and repeated bounce.
- Principal exactly-once payout/refund, NFT owner at each terminal result, storage floor after every retry, stale/duplicate/out-of-order evidence, restart/replay behavior.
- Trusted LiteServer proof chain, masterchain validator/config updates, transaction/trace/message inclusion and complete getter/account/TEP-62 owner reconciliation.
- Collection identity proof and fail-closed allowlist lifecycle.

## Release posture

**BLOCKED.** Do not enable production transaction preparation, signing, broadcast, mainnet, real funds or real NFT transfers. Keep testnet/valueless scope only. CI/emulator success does not grant independent security approval or live testnet acceptance.
