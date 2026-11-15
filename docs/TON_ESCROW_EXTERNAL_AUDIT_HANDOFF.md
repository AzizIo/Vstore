# VILTARA TON Escrow — external audit and live acceptance handoff

**Prepared against current main:** `525215b9a51a34be811e73a1cc26995cd3cb25a1`  
**Network scope:** TON testnet only (`global_id = -3`)  
**Contract:** `contracts/ton-escrow-poc/contracts/DealEscrow.tolk`  
**Toolchain:** Acton 1.2.1 / Tolk 1.5.0  
**Status:** audit/acceptance handoff only; no independent audit or live testnet acceptance has occurred.

## 1. Release posture and exact revisions to review

Do not treat current main as a release candidate. Current `main` at `525215b9a51a34be811e73a1cc26995cd3cb25a1` includes merged PR #242 (merge commit `e003dc5ae82f2beb55fb2277361588267a70f21e`), which fixes the carry-all execution-reserve refund retry storage floor. Its post-merge Contract CI [#43767167484](https://github.com/AzizIo/Vstore/actions/runs/43767167484) passed all contract steps and 30 emulator tests.

Two separate remediation tracks are still Draft:
- [PR #241 — proof-anchored TEP-62 item/collection identity](https://github.com/AzizIo/Vstore/pull/241), owned by #213. It introduces same-masterchain-block item/collection proofs, allowlisted code hashes, and collection item-address reconstruction. Its allowlist intentionally defaults to empty. The latest head `063f130faf8fea22ff301f7317ddc4a38aaafb4f` has CI pending/in progress. A preceding backend run failed Ruff I001 import ordering; the #213 owner has been notified.
- [PR #244 — seller deployment allowance retry storage floor](https://github.com/AzizIo/Vstore/pull/244), a contract-only follow-up based on current main. It re-reserves the terminal storage floor before retrying the bounced fixed seller allowance. Exact-head Contract CI [#43767931853](https://github.com/AzizIo/Vstore/actions/runs/43767931853) passed on `69938cd0226f2079b8b8225f54d645770bffe897`, including strict frozen code/BOC, StateInit/address/data, message vectors, formatting/static checks and 30/30 emulator tests. Coverage is 85.2% lines / 64.5% branches. The PR is still Draft/unmerged.
- [PR #239](https://github.com/AzizIo/Vstore/pull/239) is the earlier documentation-only handoff against an older main base; this new handoff supersedes its stale baseline.

**Audit recommendation:** perform final sign-off only against one immutable post-remediation commit after #241 and #244 are resolved, #206 updates/reviews the backend code BOC/runtime hash pin, and all exact-head CI is green. A reviewer may inspect the Draft PRs as pre-audit material but must not sign off on moving or partial artifacts.

## 2. Current-main frozen artifact

Source of truth: `contracts/ton-escrow-poc/artifacts/frozen/manifest.json`.

Current main manifest values:

| Artifact | Current-main value |
|---|---|
| Acton / Tolk | `1.2.1` / `1.5.0` |
| Compiled code hash | `1BCCBF586878F8032F4E860707B0102EC554B4E1C0CFD7DEA362E1DD391D6666` |
| BOC base64 SHA-256 | `2ba55420e6b09c94986d51b045db92959df11f66b339cd77df4e919d30a0e50b` |
| Decoded BOC SHA-256 | `b4a46ef78089119fb10272e1edbd152f8b5e9c337b59d759ad5e1c661dd4fbb5` |
| Compressed BOC SHA-256 | `57eec30799e23fe30b3d54c4407949ae99c1af8ebe921e2ce053d1d4f17c80f3` |
| Compact ABI SHA-256 | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| StateInit hash test vector | `ffd464daa07d4fd3b99e2469520eb77624f3265de9784d103df3babc15c5199f` |
| Raw address test vector | `0:ffd464daa07d4fd3b99e2469520eb77624f3265de9784d103df3babc15c5199f` |
| Initial data hash | `faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b` |

The address above is a deterministic test vector, not evidence of deployment.

### PR #244 candidate artifact (not yet main)

Acton 1.2.1 / Tolk 1.5.0 candidate:

| Artifact | PR #244 value |
|---|---|
| Compiled code hash | `9011F274BC3D7E32B76A17F13FCBA17AC49429BB4EECBC4AB97FA202BDAC2940` |
| BOC base64 SHA-256 | `f8da91f71e363585823060fcfb75d9fe579e449f3e74551bbba6b142a7e98149` |
| Decoded BOC SHA-256 | `f9ae570bf2808556a1be9dee8e804d95f6c9f427ecfcfd3edb06b029490c8607` |
| Compressed BOC SHA-256 | `58a888105143cf27c02e5beae8d724fca92fb7b89f00c77fbfc54ad5828cf365` |
| Compact ABI SHA-256 (unchanged) | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| StateInit hash test vector | `674227296eff6ac5ee02c8e2eaa12857ac339d10a9ed7f4f7ea0591e7b4adfca` |
| Raw address test vector | `0:674227296eff6ac5ee02c8e2eaa12857ac339d10a9ed7f4f7ea0591e7b4adfca` |
| Initial data hash | `faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b` |

PR #244 exact-head Contract CI run [#43767931853](https://github.com/AzizIo/Vstore/actions/runs/43767931853) passed 30/30 tests. Artifact `14183122192`, archive SHA-256 `b5c7d011004098ccbeaef48aeaec230231c6531a5554d17972d7f3ec9edf0`. This candidate code hash and BOC must not be used by the backend until #206 updates and reviews its pinned artifact/runtime hash validation.

## 3. Independent reviewer scope

The reviewer must be independent of the implementation author, release operator, and oracle/resolver signers. Before engagement, obtain a written statement of hands-on TON/Tolk 1.5.0 / TVM async-message security experience.

### Contract and protocol
- Reconstruct TL-B layouts/opcodes from Tolk source and generated ABI.
- Rebuild StateInit independently from code and immutable constructor data; verify workchain, code/data hashes, deal salt, network separation and deterministic message vectors.
- Review ConfigParam 19/global-ID mainnet rejection.
- Review authorization, fixed roles/recipients, item sender checks, TEP-62 deposit payload and notification handling, query IDs, attempt IDs, oracle/resolver digest construction and 2-of-3 Ed25519 key-slot semantics.
- Identify all NFT-stranding paths and verify that exact item identity and collection membership are independently established before immutable deal terms.

### Message execution, bounce and accounting
- Independently derive the RichBounce TL-B envelope for pinned Tolk 1.5.0, including phase layout, mandatory refs and original message info/value.
- Review two outbound descriptor slots, matching and cleanup, primary + secondary refunds, and all out-of-order/duplicate/stale/malformed/forged-bounce cases.
- Cover compute failure, action-phase failure, destination bounce, no-funds bounce, missing/delayed bounce, contract-wallet recipient and restart/replay.
- Recompute principal, seller deployment allowance, NFT transfer value, forward fee, execution reserve, gas/forward fees and terminal storage floor.
- Review both retries independently: (a) carry-all execution-reserve refund (merged #242), (b) fixed seller allowance refund (Draft #244). Each new retry transaction must recreate the terminal storage reserve before send.
- Prove principal paid/refunded exactly once, NFT owner matches terminal result, reserve floor survives both retry branches and repeated bounces, and late/duplicate attestation cannot settle twice.

### Trusted provider and finality boundary
- Independently validate trust-level-0 LiteServer root/config anchors and masterchain validator/config updates.
- Prove shard-block inclusion in masterchain, exact contract transaction and inbound message inclusion, source/destination, message hash, trace relationships, action phase, code hash, account state and complete getter snapshot.
- Confirm TonCenter/indexer discovery is never itself accepted as proof/finality.
- Review exact original outbound transaction correlation for RichBounce and incomplete/stale history handling.
- Review PR #241 TEP-62 trust boundary: item and collection account state at the same trusted masterchain block; item/collection allowlisted code hashes; collection-stored item code; minted index bounds; independently reconstructed `get_nft_address_by_index(index)`; immutable identity snapshot; current owner and collection reconciliation. Empty allowlist must fail closed.

### Required audit deliverable
- Reviewer identity, qualifications, engagement date and independence declaration.
- Exact reviewed commit SHA and source file hashes; toolchain, ABI, code, BOC and StateInit hashes.
- Findings by severity with precise source references, exploit preconditions, impact and reproducible reproducers.
- Fix verification and final signed report bound to the exact remediated hashes.
- Explicit residual risks and statement that CI/emulator is not live testnet acceptance.

## 4. External audit leads

These are leads for a scoped proposal, not endorsement, booking or confirmation of availability:
- [Hacken — TON smart contract audit](https://hacken.io/services/blockchain-security/ton-smart-contract-audit/)
- [CertiK — TON ecosystem security](https://www.certik.com/ecosystems/ton)
- [Trail of Bits — TON blockchain assessment reference](https://docs.ton.org/audits/TON_Blockchain_ToB.pdf), a prior TON core/TVM assessment, not a VILTARA audit.

The RFP must explicitly require Tolk 1.5.0, Acton 1.2.1, TVM async-message/bounce behavior, TEP-62, TON finality proofs and the escrow/finality scope above. Do not accept a generic EVM-only report as satisfying the gate. No source has been submitted to an external auditor; no engagement has been initiated.

## 5. Valueless TON testnet acceptance procedure

### Preconditions
- Independent audit has no unresolved critical/high findings.
- Final source/ABI/code/BOC/StateInit hashes are frozen and independently reproduced.
- A trusted collection policy has been independently reviewed and explicitly allowlisted: collection address, collection code hash, item code hash and item-address derivation. PR #241 proposes this gate but no actual collection policy/hash is approved.
- Seller, buyer, oracle and resolver roles use separately controlled disposable testnet wallets. Private keys remain with their owners/offline and never enter GitHub, CI, backend, logs or this handoff.
- Oracle/resolver public keys are unique, disjoint and confirmed by independent operators.
- Explicit owner authorization records testnet terms, valueless NFT, tiny testnet TON amounts, operators, abort procedure and reimbursement/no-real-value confirmation.

### Required action trace
1. Deploy the exact frozen DealEscrow StateInit; record address, code hash and immutable getters at a trusted masterchain checkpoint.
2. Activate and record state/deadline.
3. Deposit the exact approved NFT item; verify TEP-62 sender, previous owner, query ID, salt, item index, collection and live owner.
4. Fund exact principal + execution reserve; reconcile attached value, balance, state and getters.
5. Accept/deliver; verify outbound NFT transfer transaction, message hash/trace, masterchain inclusion, item owner and signed oracle attestation.
6. Exercise pre-delivery and post-delivery disputes, both resolver outcomes, NFT return, seller payout and buyer refund.
7. Deliberately trigger each allowed outbound action failure/bounce against controlled test recipients; exercise unauthorized and authorized retry with new query/attempt IDs, stale/duplicate/out-of-order bounces, timeout-before-proof and late finality.
8. Reconcile every transition against trusted masterchain inclusion and compare complete contract getters/storage with the immutable deal snapshot and live NFT item owner/collection/index.
9. Reconcile principal, seller allowance, execution reserve, fees and terminal storage floor before/after every branch, including each retry transaction.
10. Restart the observer between discovery, proof verification and persistence; replay candidate transactions/events and prove idempotent monotonic reconciliation.

### Evidence record per transition
Capture network/global ID, source commit/code hash, contract/item/collection/wallet addresses, StateInit hash, transaction hash, inbound/outbound message hashes, trace identifier, shard block ID, masterchain seqno/root hash, inclusion proof digest, transaction compute/action/bounce phase and exit codes, query/attempt/deal salt, attached and delivered TON value, fee breakdown, complete relevant getters, item owner and item/collection code/data hashes. Preserve raw proof material and reproducible verification commands. An indexer `finalized=true` flag alone is not proof.

## 6. Current live-acceptance blockers

- No live DealEscrow deployment address or transaction/trace/getter/masterchain proof exists in this workstream. Both main and PR #244 StateInit addresses are deterministic test vectors only.
- No owner-approved disposable testnet wallets, approved valueless NFT item/collection, collection allowlist or independent oracle/resolver operator keys are provisioned.
- Oracle/resolver public key settings and finality observer remain unconfigured/disabled; PR #241 allowlist is empty by default.
- No testnet transaction has been signed or broadcast. The test procedure requires explicit owner authorization and operator-controlled wallets.

**Decision: BLOCKED.** This document enables an independent specialist and release operator to conduct the review and testnet exercise; it does not substitute for either. Mainnet, production signing/broadcast, real TON funds and real NFT transfers remain out of scope.
