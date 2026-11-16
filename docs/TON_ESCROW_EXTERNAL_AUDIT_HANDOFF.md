## Main integration completed — 2026-11-17

All implementation PRs in this escrow stack are now merged into `main`. The current main head is `842cf5562d4f13f6c9f1fef50fd4dd4e234c611d`.

| PR | Scope | Main merge commit |
|---|---|---|
| [#248](https://github.com/AzizIo/Vstore/pull/248) | Tolk escrow contract lifecycle, refund/retry ordering and deterministic frozen BOC verification | `011d71678b6e338ace2853812bbd4d26dd0aa0ad` |
| [#241](https://github.com/AzizIo/Vstore/pull/241) | Proof-backed TEP-62 NFT identity, immutable identity snapshots and finality checks | `01b7820e1b8461664fd55496a8d5f46642a1c6c0` |
| [#247](https://github.com/AzizIo/Vstore/pull/247) | Pinned backend artifact and proof-bound recipient-authorized retry API | `bdae33e0e360a2800e14832aeeda139e1cb139e9` |
| [#255](https://github.com/AzizIo/Vstore/pull/255) | Retry UI, browser E2E and cross-layer workflow triggers | `154070ad3774d5e62cecb64b220ee8a7200e2bf2` |
| [#251](https://github.com/AzizIo/Vstore/pull/251) | Production bot support/terms command surfaces; no checkout | `842cf5562d4f13f6c9f1fef50fd4dd4e234c611d` |

### Exact verification evidence

The integrated escrow candidate `168f4bbd43bc818474b6be82ef98babfe8835f3b` passed all three workflows on one SHA:
- Backend CI [#43950978214](https://github.com/AzizIo/Vstore/actions/runs/43950978214) — 961 tests, Ruff, migrations and Python dependency audit.
- TON Contract CI [#43950978302](https://github.com/AzizIo/Vstore/actions/runs/43950978302) — frozen artifact/ABI/BOC/StateInit checks and 35/35 Sandbox tests.
- Frontend CI [#43950978229](https://github.com/AzizIo/Vstore/actions/runs/43950978229) — 248 unit tests, 31 standard Playwright E2E, 1 dedicated escrow retry browser E2E, production build and manifest validation; API-backed E2E 4/4.

After all merges, the actual `main` head `842cf5562d4f13f6c9f1fef50fd4dd4e234c611d` also passed push-triggered checks:
- Backend CI [#43969649892](https://github.com/AzizIo/Vstore/actions/runs/43969649892) — success.
- Frontend CI [#43969649906](https://github.com/AzizIo/Vstore/actions/runs/43969649906) — frontend job and API-backed E2E job both success.
- The contract source/artifact did not change in the final bot-support merge; its exact integrated-candidate Contract CI remains #43950978302.

PR #251's own exact-head Backend CI [#43832280156](https://github.com/AzizIo/Vstore/actions/runs/43832280156) and Frontend CI [#43832280175](https://github.com/AzizIo/Vstore/actions/runs/43832280175) passed before merge. No signing, broadcast, deployment, live wallet transfer, real TON or real NFT transfer was performed.

### Release decision remains BLOCKED

Merging implementation into `main` is source integration, **not production acceptance or permission to enable paid escrow**. Before any real transaction or production checkout:
1. Obtain an independent TON/Tolk audit bound to the exact final source, ABI, BOC and StateInit hashes.
2. Complete owner-approved valueless live-testnet lifecycle acceptance with trusted masterchain evidence, actual recipient wallet ownership, bounce/retry traces and balance/storage-floor reconciliation.
3. Have an operator review and explicitly configure the exact testnet NFT collection policy. The allowlist remains empty by default.
4. Resolve the Telegram/legal classification of this exact P2P TON NFT resale and payment model. The current Stars/chargeback risk remains unresolved; paid checkout stays disabled.

The code remains testnet-oriented and fail-closed. Do not enable mainnet, real-fund checkout, custody, server-side signing or automatic broadcast based only on CI or the fact that PRs are merged.

---

# VILTARA TON Escrow — external audit and live acceptance handoff

**Pre-integration code baseline:** `b592a4b889221aeb314e521a357b1746091a5976`  
**Current main:** `842cf5562d4f13f6c9f1fef50fd4dd4e234c611d`; implementation PRs #248/#241/#247/#255/#251 are merged. This is an external audit/acceptance handoff, not authorization to deploy.  
**Network scope:** TON testnet only (`global_id = -3`)  
**Contract:** `contracts/ton-escrow-poc/contracts/DealEscrow.tolk`  
**Toolchain:** Acton 1.2.1 / Tolk 1.5.0  
**Status:** audit/acceptance handoff only; no independent audit or live testnet acceptance has occurred.

## Latest integrated candidate — 2026-11-16 20:25 UTC

> This block supersedes every earlier feature head and CI snapshot below. The pre-integration code baseline was `b592a4b889221aeb314e521a357b1746091a5976`; the escrow implementation stack is now merged to main at `842cf5562d4f13f6c9f1fef50fd4dd4e234c611d`.

Pre-merge integrated candidate: `168f4bbd43bc818474b6be82ef98babfe8835f3b`.

| Workflow | Exact evidence on the integrated SHA |
|---|---|
| Backend CI [#43950978214](https://github.com/AzizIo/Vstore/actions/runs/43950978214) | **Success** — 961 passed, Ruff, migration upgrade and Python dependency audit passed |
| TON Contract CI [#43950978302](https://github.com/AzizIo/Vstore/actions/runs/43950978302) | **Success** — frozen source/ABI/BOC, code hash, StateInit and message vectors passed; **35/35 Sandbox tests** |
| Frontend CI [#43950978229](https://github.com/AzizIo/Vstore/actions/runs/43950978229) | **Success** — 248 unit tests, production build, preview container, Nginx, TON Connect manifest; **31 standard Playwright + 1 dedicated escrow retry browser E2E** |
| API-backed E2E (within #43948984632) | **Success** — 4/4 marketplace journey tests and persisted order/event/outbox assertions. These are marketplace tests, not retry-path evidence. |

The dedicated escrow browser E2E runs in a separate Vite server with testnet UI visible, deterministic wallet/API fixtures, blank TON Connect manifest and signing disabled. It verifies the recipient-bound retry review, exact query ID/idempotency header and unsigned transaction display. It does not sign, broadcast or contact a live chain.

Additional branch evidence:
- PR #247 backend head `c28c8e0cc2037a7a82e48bee84dea3a350a8161a`: Backend CI [#43946958283](https://github.com/AzizIo/Vstore/actions/runs/43946958283) — 961 passed; Frontend CI #43946958233 passed.
- PR #248 contract source/artifact head `08daf5afe63c83f6f892fd469d90b3788e0f989c` is unchanged; it is included in the integrated build above.
- PR #241 NFT identity base remains `e1c891a99b5359585f2b7b2d391699a1a11737eb`; independent review and collection approval remain outstanding.

The browser retry E2E exposed a runtime defect hidden while the escrow feature flag was off: `@ton/core` required a global Buffer in the browser. The frontend now loads the existing `buffer` dependency before importing App/TON modules, and the escrow retry browser test passes with a no-pageerror assertion.

Cross-layer path filters now trigger Backend and Contract CI when frontend escrow API/UI/tests/browser-E2E change. This keeps future candidates verifiable on one exact SHA.

### Issue #252 implementation status

The proof-bound retry implementation is merged into main via PRs #247 and #255. Backend retry discovery and preparation both require provider/getter proof-anchor agreement. Retry idempotency replay revalidates the full deployment snapshot and currently verified recipient wallet; changed/revoked wallets or inconsistent snapshots fail closed. Deal, wallet and action row locks use a consistent order. The browser test verifies the positive recipient-authorized UI path; backend adversarial tests cover proof, wallet, snapshot and idempotency failures.

**Retry-window limitation:** the on-chain BOUNCED descriptor does not persist the bounce timestamp. The backend validates kind-specific contract window values (kinds 1–5: 1800 seconds; terminal kinds 6–7: zero) and the contract sets a follow-up confirmation deadline when a retry starts. The backend cannot prove elapsed time since the original bounce; no bounce-age cutoff is claimed.

### Remaining release gates

1. Independent TON/Tolk audit bound to the exact source, ABI, code BOC and StateInit hashes.
2. Owner-approved valueless live-testnet lifecycle acceptance with trusted masterchain inclusion, actual recipient wallet ownership, bounce/retry traces and balance/storage-floor reconciliation.
3. Explicit testnet NFT collection policy approval; the allowlist remains empty by default.
4. Written Telegram policy/legal decision for the exact P2P TON NFT resale/payment flow. Bot Developer Terms §6.2/§6.2.1 create unresolved Stars/chargeback risk; TON Connect permission does not clearly exempt P2P NFT resale. See Issue #155.
5. Reconcile the stale npm audit output for withdrawn GHSA-gcqx-w48m-w2h4 in Issue #256; do not apply an unverified dependency override.

**Decision remains BLOCKED — not a production release candidate.** No mainnet, real TON, production checkout, custody, server signing or broadcast is enabled.

## Superseding status update — 2026-11-16 19:49 UTC

> This update supersedes the historical PR heads and CI references below. The executable escrow code baseline remains b592a4b889221aeb314e521a357b1746091a5976; none of the escrow implementation stack has been merged to main.

The implementation stack is now: PR #248 (contract) → PR #241 (NFT identity) → PR #247 (backend artifact + proof-bound retry API) → PR #255 (frontend retry + cross-layer CI).

| PR | Exact head | Current evidence |
|---|---|---|
| #248 | 08daf5afe63c83f6f892fd469d90b3788e0f989c | Contract CI #43832141975 passed |
| #241 | e1c891a99b5359585f2b7b2d391699a1a11737eb | Backend #43931218291 and Frontend #43931217044 passed; independent review remains outstanding |
| #247 | e98e1b6873d65c0504d05c9d217b8c08e8fc4120 | Backend #43942177488 (961 passed); Frontend/API E2E #43942177624 passed |
| #255 | 1e1a12e9d79e936a5d0df28461012df562f6e8d0 | **Backend #43942937032, Contract #43942936983 and Frontend/API E2E #43942937000 all passed on this one exact SHA.** Results: 961 backend, 35/35 Sandbox, 248 frontend unit, 31 Playwright and 4 API-backed E2E tests |

The new backend retry preparation guard verifies the getter proof seqno, block hash, provider ID and 64-hex state-data hash against the provider tuple before committing a new getter snapshot or wallet action. Missing/mismatched proof metadata fails closed.

Issue #252's retry implementation and adversarial test matrix are now represented in the integrated stack. No signing or broadcast is enabled; this endpoint prepares unsigned testnet TON Connect payloads only.

### Remaining independent acceptance gates

- Independent TON/Tolk audit bound to the final source, ABI, BOC and StateInit hashes.
- Explicit approval of a testnet collection policy; the allowlist remains empty.
- Owner-approved valueless live-testnet lifecycle acceptance and evidence bundle.
- Written Telegram policy/legal review for the exact NFT resale/payment flow. First-party Bot Developer Terms §6.2 currently require Stars for digital goods/services transactions in a TPA, and §6.2.1 requires /paysupport while warning against irreversible high-value virtual-item sales after chargebacks. §7 / [Blockchain Guidelines](https://core.telegram.org/bots/blockchain-guidelines) allow TON assets and TON Connect, but do not expressly exempt P2P NFT sales from §6.2. The [Stars Payments API](https://core.telegram.org/bots/payments-stars) says Stars applies to digital goods inside Telegram even where external portals/providers exist. This exact user-to-user existing TON NFT resale remains unresolved; require written Telegram clarification and legal review before paid checkout. See Issue #155.
- npm audit still prints three low deepmerge findings even though GitHub withdrew GHSA-gcqx-w48m-w2h4 on 2026-11-16 as not describing a security vulnerability. Treat this as stale audit feed output pending reconciliation, not a confirmed vulnerability; see Issue #256.

**Release decision remains BLOCKED.** CI is not an independent audit or live-chain acceptance. No production checkout, server signing/broadcast, mainnet, real TON, custody or user funds are enabled.

## 1. Release posture and exact revisions to review

Do not treat the current main branch as a release candidate. At the original executable-code baseline `b592a4b889221aeb314e521a357b1746091a5976` (PR #244), main included the carry-all reserve retry fix from #242 and seller deployment allowance retry storage-floor fix from #244. Subsequent main changes in this handoff were documentation-only.

The active remediation tracks are:

- [PR #241 — proof-anchored TEP-62 NFT identity](https://github.com/AzizIo/Vstore/pull/241), Issue #213. Exact head `605612436df49db2a4414de28b9c5e8beb49d7b9` is Ready for Review (not merged). Backend CI #43823958161 and Frontend CI #43823958345 (including API-backed E2E) both passed; PostgreSQL 16 migration upgrade/downgrade/re-upgrade passed. Branch is 93 commits ahead and 0 behind main. No independent review submission is currently recorded. Two regression tests now reject a missing per-deal collection address and an item-address mismatch in terminal-owner reconciliation; the method also validates each persisted deal address against its own immutable identity snapshot. Its collection allowlist defaults to empty and must stay empty until an operator approves exact collection/item code hashes and derivation policy.
- [PR #247 — backend DealEscrow artifact pin and cross-track guard](https://github.com/AzizIo/Vstore/pull/247), Issue #206. Exact head `2c83cd3f2af3faba902d5d809ffe83f889fd6086` remains Draft. Backend CI #43815732686 passed (866 tests), Frontend/API E2E #43815732770 passed, and Contract CI #43815732694 passed. It pins the backend adapter to the **current-main** frozen artifact (`9011F274...`) and adds the cross-track manifest/physical-BOC integrity checks. It has not yet been refreshed to the new PR #248 candidate (`498A82F9...` / StateInit `4e3845e9...`) and is not compatible with that candidate.
- [PR #248 — TON escrow contract lifecycle/refund follow-up](https://github.com/AzizIo/Vstore/pull/248), Issue #225. PR #250 has now been squash-merged into the #248 feature branch (not main) as `08daf5afe63c83f6f892fd469d90b3788e0f989c`. The resulting exact #248 head is `08daf5afe63c83f6f892fd469d90b3788e0f989c`; Contract CI #43832141975 completed successfully on that exact SHA (verified after the snapshot). The original contract-only CI #43824843864 passed 35/35 Sandbox tests, formatting/static checks, frozen ABI/raw BOC checks, generated-wrapper + `@ton/core` StateInit/address/data cross-check and message vectors. Code hash `498A82F9...`; StateInit/address `4e3845e9...`. PR #250 added the deterministic RFC 1950/DEFLATE stored-block representation (fixed header, 65,535-byte blocks and Adler-32) and canonical digest `8dce117db9f0ca883b0438c2f600b10c4caf18d7febd3db26a02d78c0191cbd7`; its pre-merge exact head `7b8775b628e9df9d22cbb18549bb9a51cf51828d` passed Contract CI #43829081437 / artifact #14208215967. The new #248 exact-head Contract CI is green; backend pin refresh can proceed from this exact frozen artifact, subject to the integrated cross-track checks.
- [PR #249 — consolidated release gate and audit handoff](https://github.com/AzizIo/Vstore/pull/249) is Draft and documentation-only. This handoff and the current-main assessment are being carried forward there to replace the stale #246 baseline.

PR #246's earlier documentation baseline was based on `525215b9a51a34be811e73a1cc26995cd3cb25a1` and is now stale relative to main. Keep its audit scope/procedure, but do not use its historical hashes, branch statuses or artifact claims as current evidence.

**Audit recommendation:** final sign-off is allowed only against one immutable integrated commit after #241 has independent review, #248's final compiler/StateInit/ABI artifacts are frozen, #247 pins those exact artifacts, and Backend, Contract, Frontend and API-backed E2E CI all pass on the same candidate SHA. A moving branch, isolated green PR, or emulator-only result is not sufficient.

## 2. Current main and candidate frozen artifacts

Source of truth: `contracts/ton-escrow-poc/artifacts/frozen/manifest.json`. The backend runtime pin is separately stored in `backend/app/escrow/abi_artifacts/manifest.json`; both must describe the same build.

### Current main contract artifact

The original main code baseline `b592a4b889221aeb314e521a357b1746091a5976` has the PR #244 frozen artifact:

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
- **Contract artifact and lifecycle:** PR #248 contains PR #250's canonical compressed-BOC integrity verification as of exact head `08daf5afe63c83f6f892fd469d90b3788e0f989c` (squash merged into the feature branch, not main). Former #250 head passed Contract CI #43829081437 / artifact #14208215967, with canonical compressed digest `8dce117db9f0ca883b0438c2f600b10c4caf18d7febd3db26a02d78c0191cbd7`. Fresh Contract CI #43832141975 completed successfully on the updated #248 head. The contract candidate is now build-verified; #247 still needs to be refreshed to this exact artifact. The 35-test suite covers buyer-reserve retry ordering, duplicate NFT callback idempotency, timeout dispute resolution, late buyer return, terminal replay and sub-minimum action-value tests.
- **Backend artifact/runtime synchronization (resolved in code):** PR #247 aligned the backend BOC/manifest with the frozen contract artifact (code hash `498A82F9B2DE206BE42108B6413D517CE63D4BCB1C20704D0BD89FCCC9509C46`, StateInit hash `4e3845e9d0b4df2f603b0ba7cceca4592276d25d8f43d2c611376344db393f75`, canonical compressed BOC SHA-256 `8dce117db9f0ca883b0438c2f600b10c4caf18d7febd3db26a02d78c0191cbd7`). The alignment guard and integrated Backend/Contract/Frontend workflows passed before merge; PR #247 is now merged in main commit `bdae33e0e360a2800e14832aeeda139e1cb139e9`.
- **Valueless live TON testnet acceptance:** no live deployment address, signed transaction, trace, trusted masterchain inclusion proof, getter snapshot or NFT owner transition has been recorded. Disposable wallets, reviewed valueless NFT/collection and independent oracle/resolver operators are not provisioned.
- **Recipient-authorized outbound retry API:** [Issue #252](https://github.com/AzizIo/Vstore/issues/252) is open. Contract #248 implements `RetryFailedOutboundAction` but backend/API/frontend do not yet prepare this operation. The backend must use a fresh trusted masterchain storage read and require the verified wallet to equal the exact recipient of the matching BOUNCED descriptor. Observer/indexer hints, a stale getter snapshot or a caller-supplied query ID cannot authorize the retry. Positive and adversarial end-to-end tests on the same integrated SHA are required.
- **Production support surfaces:** [PR #251](https://github.com/AzizIo/Vstore/pull/251) adds information-only `/paysupport`, `/terms`, `/support` without importing the isolated test payment router. It remains Draft; exact-head Backend CI #1758 and Frontend CI #1958 both completed successfully on `f51400e24ea5da8db4dc47bd2e450626f753bacc`. Independent review, configured legal/support destinations and the actual payment-dispute/refund workflow remain open. It does not provide the actual payment-dispute/refund workflow or publish the operator's legal terms/support contact.
- **Telegram Stars and Mini App resale policy:** the exact third-party wallet-to-wallet resale flow has no written Telegram ruling or legal approval. Bot Developer Terms §6.2/§6.2.1 and §7 operate together; use of TON for blockchain functionality does not itself exempt a purchase flow from the Stars rule. Production `/paysupport`, `/terms` and `/support` are not wired into the production bot; the existing payment support handler is isolated to the test bot.
- **Signing/custody:** no mainnet, production signing, transaction broadcast, real TON payments or real NFT transfers are authorized.


**Decision: BLOCKED.** This document enables an independent specialist and release operator to conduct the review and testnet exercise; it does not substitute for either. Mainnet, production signing/broadcast, real TON funds and real NFT transfers remain out of scope.
