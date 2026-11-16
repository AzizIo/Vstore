# VILTARA TON Escrow — external audit and live acceptance handoff

**Prepared against current main:** `b592a4b889221aeb314e521a357b1746091a5976`  
**Network scope:** TON testnet only (`global_id = -3`)  
**Contract:** `contracts/ton-escrow-poc/contracts/DealEscrow.tolk`  
**Toolchain:** Acton 1.2.1 / Tolk 1.5.0  
**Status:** audit/acceptance handoff only; no independent audit or live testnet acceptance has occurred.

## 1. Release posture and exact revisions to review

Do not treat current main as a release candidate. Current `main` is `b592a4b889221aeb314e521a357b1746091a5976`, which is the merge commit for PR #244; it includes the carry-all reserve retry fix from #242 and seller deployment allowance retry storage-floor fix from #244.

The active remediation tracks are:

- [PR #241 — proof-anchored TEP-62 NFT identity](https://github.com/AzizIo/Vstore/pull/241), Issue #213. Exact head `605612436df49db2a4414de28b9c5e8beb49d7b9` is Ready for Review (not merged). Backend CI #43823958161 and Frontend CI #43823958345 (including API-backed E2E) both passed; PostgreSQL 16 migration upgrade/downgrade/re-upgrade passed. Branch is 93 commits ahead and 0 behind main. No independent review submission is currently recorded. Two regression tests now reject a missing per-deal collection address and an item-address mismatch in terminal-owner reconciliation; the method also validates each persisted deal address against its own immutable identity snapshot. Its collection allowlist defaults to empty and must stay empty until an operator approves exact collection/item code hashes and derivation policy.
- [PR #247 — backend DealEscrow artifact pin and cross-track guard](https://github.com/AzizIo/Vstore/pull/247), Issue #206. Exact head `2c83cd3f2af3faba902d5d809ffe83f889fd6086` remains Draft. Backend CI #43815732686 passed (866 tests), Frontend/API E2E #43815732770 passed, and Contract CI #43815732694 passed. It pins the backend adapter to the **current-main** frozen artifact (`9011F274...`) and adds the cross-track manifest/physical-BOC integrity checks. It has not yet been refreshed to the new PR #248 candidate (`498A82F9...` / StateInit `4e3845e9...`) and is not compatible with that candidate.
- [PR #248 — TON escrow contract lifecycle/refund follow-up](https://github.com/AzizIo/Vstore/pull/248), Issue #225. Current #248 head is `170dafb2180ec37ada903f3d17518c8d50d25c8c`, Draft. Exact-head Contract CI #43824843864 passed 35/35 Sandbox tests, formatting/static checks, frozen ABI/raw BOC checks, generated-wrapper + `@ton/core` StateInit/address/data cross-check and message vectors. Code hash `498A82F9...`; StateInit/address `4e3845e9...`. The compressed-BOC verifier gap was addressed in a separate stacked follow-up, [PR #250](https://github.com/AzizIo/Vstore/pull/250), based on that exact #248 SHA. PR #250 uses a portable canonical RFC 1950/DEFLATE stored-block stream (fixed header, 65,535-byte blocks and Adler-32), pins digest `8dce117db9f0ca883b0438c2f600b10c4caf18d7febd3db26a02d78c0191cbd7`, and changes Contract CI to verify the compressed representation itself. Exact PR #250 head `7b8775b628e9df9d22cbb18549bb9a51cf51828d` passed Contract CI #43829081437; artifact #14208215967. PR #250 is still stacked and not yet integrated into #248: the final #248 head must include it and pass Contract CI again before backend pinning.
- [PR #249 — consolidated release gate and audit handoff](https://github.com/AzizIo/Vstore/pull/249) is Draft and documentation-only. This handoff and the current-main assessment are being carried forward there to replace the stale #246 baseline.

PR #246's earlier documentation baseline was based on `525215b9a51a34be811e73a1cc26995cd3cb25a1` and is now stale relative to main. Keep its audit scope/procedure, but do not use its historical hashes, branch statuses or artifact claims as current evidence.

**Audit recommendation:** final sign-off is allowed only against one immutable integrated commit after #241 has independent review, #248's final compiler/StateInit/ABI artifacts are frozen, #247 pins those exact artifacts, and Backend, Contract, Frontend and API-backed E2E CI all pass on the same candidate SHA. A moving branch, isolated green PR, or emulator-only result is not sufficient.

## 2. Current main and candidate frozen artifacts

Source of truth: `contracts/ton-escrow-poc/artifacts/frozen/manifest.json`. The backend runtime pin is separately stored in `backend/app/escrow/abi_artifacts/manifest.json`; both must describe the same build.

### Current main contract artifact

Current main `b592a4b889221aeb314e521a357b1746091a5976` has the PR #244 frozen artifact:

| Artifact | Current-main frozen value |
|---|---|
| Source commit | `2160aa6780efff2e44e5f8ae99b2d21cb8764740` |
| Contract workflow / artifact | `#43767830764` / `14182942567` |
| Archive SHA-256 | `f68f1401c3123ccaab179a007cc5f805a73135532d165e785d3586be4a54c0cd` |
| Acton / Tolk | `1.2.1` / `1.5.0` |
| Compiled code hash | `9011F274BC3D7E32B76A17F13FCBA17AC49429BB4EECBC4AB97FA202BDAC2940` |
| BOC base64 SHA-256 | `f8da91f71e363585823060fcfb75d9fe579e449f3e74551bbba6b142a7e98149` |
| Decoded BOC SHA-256 | `f9ae570bf2808556a1be9dee8e804d95f6c9f427ecfcfd3edb06b029490c8607` |
| Compressed BOC SHA-256 | `58a888105143cf27c02e5beae8d724fca92fb7b89f00c77fbfc54ad5828cf365` |
| Compact ABI SHA-256 | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| StateInit hash test vector | `674227296eff6ac5ee02c8e2eaa12857ac339d10a9ed7f4f7ea0591e7b4adfca` |
| Raw address test vector | `0:674227296eff6ac5ee02c8e2eaa12857ac339d10a9ed7f4f7ea0591e7b4adfca` |
| Initial data hash | `faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b` |

The address is a deterministic StateInit test vector, not evidence of a deployed contract.

### Current-main backend pin mismatch

At the same main SHA, the backend adapter manifest still carries the earlier artifact:
- code hash `D822B8AFBB37027611A9A9DDC8E67C52F17BBBC45B4352C7F360693BD685CA54`;
- StateInit hash `29a40423c7e8fa1390782bce7e94e32f2a0e14ceef6cf05bd0f1641d0ba3f423`;
- backend manifest source commit `01963603df7fb4ad819ab4a8f4a68315cec47c5d`, workflow `#43766860437`, artifact `14181479725`.

This does not match the current frozen contract artifact above. PR #247 updates the backend pin to the `9011F274...` / `67422729...` artifact and enforces cross-track equality plus physical BOC digest verification. Until #247 is merged, do not activate the adapter against current main.

### PR #248 candidate artifact — not yet accepted

The generated compiler output for source candidate `d87e4a81e07ec0c1e95619f6e5188c5be5433d62` gave:

| Artifact | Candidate value |
|---|---|
| Compiled code hash | `498A82F9B2DE206BE42108B6413D517CE63D4BCB1C20704D0BD89FCCC9509C46` |
| BOC base64 SHA-256 | `0e7bc7b35eee4ae7003fba0a0e5368df3428b7e32ad0f4fc5ddf0f3230d5daf3` |
| Decoded BOC SHA-256 | `86ed08596d0595c711aa2cf7659ee396ff443d7b01c65659b8e7543dd23c6173` |
| Compressed BOC SHA-256 (Python `zlib.compress(raw_boc)` candidate) | `1766fd8f3542eb0f9aec9cd8ddd80cdd69297c97d58efbef91cdaf11fdb75407` |
| StateInit hash | `4e3845e9d0b4df2f603b0ba7cceca4592276d25d8f43d2c611376344db393f75` |
| Raw address | `0:4e3845e9d0b4df2f603b0ba7cceca4592276d25d8f43d2c611376344db393f75` |
| Initial data hash | `faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b` |

The exact BOC base64/raw digests and code hash were reproduced from compiler artifact #14206172246, and exact-head Contract CI #43824843864 independently rebuilt them successfully. StateInit/address/data were printed by the generated Acton wrapper + `@ton/core` in that same CI run. However, the compressed-zlib field is outside the current contract build verifier: manifest `dbca9581...` is not the digest produced by `zlib.compress(raw_boc)` (`1766fd8f...`) on the exact artifact. This is a remaining artifact-integrity verification item, not a failure of the 35 Sandbox tests or StateInit vector. Agent 2 has been notified; adapter integration must wait for a single agreed compressed file/digest and a test that checks it.

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
- [Cecuro — TON security audits](https://cecuro.ai/ecosystems/ton). Its public TON page explicitly lists Tolk, FunC and Tact among languages it reviews and mentions TON-specific asynchronous-message, bounced-message and gas/storage risks. It is the closest advertised language fit for this Tolk codebase; still require written confirmation that the team can audit Acton 1.2.1 / Tolk 1.5.0 and our exact RichBounce/provider proof scope.
- [Hacken — TON smart contract audit](https://hacken.io/services/blockchain-security/ton-smart-contract-audit/). Its page describes TVM-focused TON audits, fuzzing, static/dynamic testing and remediation review; confirm Tolk 1.5.0 experience in the proposal.
- [CertiK — TON ecosystem audits](https://www.certik.com/ecosystems/ton). Its page offers TON contract audits; confirm Tolk-specific reviewer availability and async TVM/bounce expertise.
- [Trail of Bits — TON blockchain/TVM assessment reference](https://docs.ton.org/audits/TON_Blockchain_ToB.pdf). This is a prior TON core/TVM assessment, not a VILTARA contract audit or confirmation of current engagement availability.
- [TON Audit Studio](https://ton.app/audit/ton-audit-studio?id=5315) advertises automated FunC/Tact/Tolk checks. Treat it only as a supplementary automated scan, never as the independent human audit or final sign-off.

The RFP must explicitly require Tolk 1.5.0, Acton 1.2.1, TVM async-message/bounce behavior, TEP-62, TON finality proofs and the escrow/finality scope above. Do not accept a generic EVM-only report as satisfying the gate. Obtain written confirmation of reviewer independence, qualifications, availability, cost and exact source/artifact scope before sharing source or commissioning work. No source has been submitted to an external auditor; no engagement has been initiated.

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

- **Independent TON/Tolk security audit:** none has been commissioned or accepted. Internal review and CI are not independent audit evidence.
- **Collection identity policy:** PR #241 is Ready for Review with green exact-head Backend/Frontend/API checks, but has no recorded independent review and its collection allowlist remains empty. No real collection policy/code hash has been approved.
- **Contract artifact and lifecycle:** PR #248 remains Draft with green Contract CI #43824843864 (35/35 Sandbox); [stacked PR #250](https://github.com/AzizIo/Vstore/pull/250) adds the missing compressed-BOC integrity verification and is green on exact head `7b8775b628e9df9d22cbb18549bb9a51cf51828d` (Contract CI #43829081437, artifact #14208215967). Canonical compressed digest is `8dce117db9f0ca883b0438c2f600b10c4caf18d7febd3db26a02d78c0191cbd7`. This fixes the provenance-check gap at the PR #250 stack, but is not yet part of #248's head. Require #250 integration into #248 and a fresh green Contract CI on the resulting exact #248 SHA before adapter changes. The 35-test suite includes buyer-reserve retry ordering, duplicate NFT callback idempotency, timeout dispute resolution, late buyer return, terminal replay and sub-minimum action-value tests.
- **Backend artifact/runtime synchronization:** current main's backend manifest is still pinned to code hash D822… while the contract frozen manifest is 9011… . PR #247's strict cross-track guard is green on its own head but has not been merged. An integrated candidate must contain the matching backend pin and final contract artifact, then run all four workflows on one SHA.
- **Valueless live TON testnet acceptance:** no live deployment address, signed transaction, trace, trusted masterchain inclusion proof, getter snapshot or NFT owner transition has been recorded. Disposable wallets, reviewed valueless NFT/collection and independent oracle/resolver operators are not provisioned.
- **Telegram Stars and Mini App resale policy:** the exact third-party wallet-to-wallet resale flow has no written Telegram ruling or legal approval. Bot Developer Terms §6.2/§6.2.1 and §7 operate together; use of TON for blockchain functionality does not itself exempt a purchase flow from the Stars rule. Production `/paysupport`, `/terms` and `/support` are not wired into the production bot; the existing payment support handler is isolated to the test bot.
- **Signing/custody:** no mainnet, production signing, transaction broadcast, real TON payments or real NFT transfers are authorized.


**Decision: BLOCKED.** This document enables an independent specialist and release operator to conduct the review and testnet exercise; it does not substitute for either. Mainnet, production signing/broadcast, real TON funds and real NFT transfers remain out of scope.
