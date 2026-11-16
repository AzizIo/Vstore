# VILTARA TON Escrow — release gate snapshot

**Snapshot date:** 2026-11-16  
**Executable code baseline:** `b592a4b889221aeb314e521a357b1746091a5976`  
**Mainline note:** release-gate and audit documentation has been updated on main; executable escrow code baseline remains `b592a4b889221aeb314e521a357b1746091a5976`.  
**Network:** TON testnet only (`global_id = -3`)  
**Decision:** **BLOCKED — not a production release candidate**

This document supersedes the older handoff material based on `525215b9a51a34be811e73a1cc26995cd3cb25a1`. It is a release-coordination snapshot, not an independent security audit, live testnet acceptance, or authorization to deploy.

## Latest integrated candidate — 2026-11-16 20:25 UTC

> This block supersedes every earlier feature head and CI snapshot below. The executable escrow code baseline remains `b592a4b889221aeb314e521a357b1746091a5976`; the current main branch also contains docs-only release-handoff updates. **No escrow implementation PR has been merged to main**.

Integrated candidate: `f2e61b0c049d64e90dd47025d0979ce295f1e426`.

| Workflow | Exact evidence on the integrated SHA |
|---|---|
| Backend CI [#43948985127](https://github.com/AzizIo/Vstore/actions/runs/43948985127) | **Success** — 961 passed, Ruff, migration upgrade and Python dependency audit passed |
| TON Contract CI [#43948984661](https://github.com/AzizIo/Vstore/actions/runs/43948984661) | **Success** — frozen source/ABI/BOC, code hash, StateInit and message vectors passed; **35/35 Sandbox tests** |
| Frontend CI [#43948984632](https://github.com/AzizIo/Vstore/actions/runs/43948984632) | **Success** — 248 unit tests, production build, preview container, Nginx, TON Connect manifest; **31 standard Playwright + 1 dedicated escrow retry browser E2E** |
| API-backed E2E (within #43948984632) | **Success** — 4/4 marketplace journey tests and persisted order/event/outbox assertions. These are marketplace tests, not retry-path evidence. |

The dedicated escrow browser E2E runs in a separate Vite server with testnet UI visible, deterministic wallet/API fixtures, blank TON Connect manifest and signing disabled. It verifies the recipient-bound retry review, exact query ID/idempotency header and unsigned transaction display. It does not sign, broadcast or contact a live chain.

Additional branch evidence:
- PR #247 backend head `c28c8e0cc2037a7a82e48bee84dea3a350a8161a`: Backend CI [#43946958283](https://github.com/AzizIo/Vstore/actions/runs/43946958283) — 961 passed; Frontend CI #43946958233 passed.
- PR #248 contract source/artifact head `08daf5afe63c83f6f892fd469d90b3788e0f989c` is unchanged; it is included in the integrated build above.
- PR #241 NFT identity base remains `e1c891a99b5359585f2b7b2d391699a1a11737eb`; independent review and collection approval remain outstanding.

The browser retry E2E exposed a runtime defect hidden while the escrow feature flag was off: `@ton/core` required a global Buffer in the browser. The frontend now loads the existing `buffer` dependency before importing App/TON modules, and the escrow retry browser test passes with a no-pageerror assertion.

Cross-layer path filters now trigger Backend and Contract CI when frontend escrow API/UI/tests/browser-E2E change. This keeps future candidates verifiable on one exact SHA.

### Issue #252 implementation status

The proof-bound retry implementation is complete in the unmerged feature stack. Backend retry discovery and preparation both require provider/getter proof-anchor agreement. Retry idempotency replay revalidates the full deployment snapshot and currently verified recipient wallet; changed/revoked wallets or inconsistent snapshots fail closed. Deal, wallet and action row locks use a consistent order. The browser test verifies the positive recipient-authorized UI path; backend adversarial tests cover proof, wallet, snapshot and idempotency failures.

**Retry-window limitation:** the on-chain BOUNCED descriptor does not persist the bounce timestamp. The backend validates kind-specific contract window values (kinds 1–5: 1800 seconds; terminal kinds 6–7: zero) and the contract sets a follow-up confirmation deadline when a retry starts. The backend cannot prove elapsed time since the original bounce; no bounce-age cutoff is claimed.

### Remaining release gates

1. Independent TON/Tolk audit bound to the exact source, ABI, code BOC and StateInit hashes.
2. Owner-approved valueless live-testnet lifecycle acceptance with trusted masterchain inclusion, actual recipient wallet ownership, bounce/retry traces and balance/storage-floor reconciliation.
3. Explicit testnet NFT collection policy approval; the allowlist remains empty by default.
4. Written Telegram policy/legal decision for the exact P2P TON NFT resale/payment flow. Bot Developer Terms §6.2/§6.2.1 create unresolved Stars/chargeback risk; TON Connect permission does not clearly exempt P2P NFT resale. See Issue #155.
5. Reconcile the stale npm audit output for withdrawn GHSA-gcqx-w48m-w2h4 in Issue #256; do not apply an unverified dependency override.

**Decision remains BLOCKED — not a production release candidate.** No mainnet, real TON, production checkout, custody, server signing or broadcast is enabled.

## Superseding implementation status — 2026-11-16 19:49 UTC

> This status block supersedes the older branch heads and CI outcomes recorded in the historical snapshot sections below. The executable escrow code baseline remains b592a4b889221aeb314e521a357b1746091a5976; no escrow implementation change from this stack has been merged to main.

| Track | Current head | Exact evidence |
|---|---|---|
| Contract lifecycle / [PR #248](https://github.com/AzizIo/Vstore/pull/248) | 08daf5afe63c83f6f892fd469d90b3788e0f989c | TON Contract CI #43832141975 passed on the exact source/artifact head; 35/35 Sandbox tests, frozen manifest, code/BOC/ABI, StateInit and message-vector checks passed |
| NFT identity / [PR #241](https://github.com/AzizIo/Vstore/pull/241) | e1c891a99b5359585f2b7b2d391699a1a11737eb | Backend CI #43931218291 and Frontend CI #43931217044 passed; still unmerged and awaiting independent review |
| Backend artifact + retry API / [PR #247](https://github.com/AzizIo/Vstore/pull/247) | e98e1b6873d65c0504d05c9d217b8c08e8fc4120 | Backend CI #43942177488 passed (961 tests); Frontend/API-backed E2E #43942177624 passed (31 + 4); proof-anchor hardening is included |
| Integrated retry stack / [PR #255](https://github.com/AzizIo/Vstore/pull/255) | 1e1a12e9d79e936a5d0df28461012df562f6e8d0 | **All three workflows green on this exact SHA:** Backend #43942937032 (961 passed), TON Contract #43942936983 (35/35 Sandbox), Frontend + API-backed E2E #43942937000 (248 unit, 31 Playwright, 4 API-backed) |

Cross-layer path filters now cause Backend CI to run for frontend escrow API/UI/test changes and TON Contract CI to run for backend/frontend escrow changes. This allows the integrated stack to receive the three required workflows on one immutable commit instead of assembling evidence from unrelated heads.

### Issue #252 implementation status

The proof-bound recipient-authorized retry path is implemented across the provider, backend API/adapter and frontend. Both discovery and preparation require proof-anchor fields to match the trust-level-0 provider tuple. Preparation rejects missing/malformed state-data hash before updating the persisted snapshot or creating a wallet action. Route-level regression covers this fail-closed condition. The retry is unsigned and testnet-only.

### Remaining release gates

1. Independent TON/Tolk audit bound to final source, ABI, code BOC and StateInit hashes. Internal review and green CI are not an independent audit.
2. Explicit operator approval of a reviewed testnet NFT collection policy. The default allowlist remains empty.
3. Owner-approved valueless live-testnet acceptance with trusted masterchain inclusion, NFT owner transitions, retry/bounce traces and balance/storage-floor reconciliation.
4. Written Telegram policy/legal review for the exact TON NFT resale/payment flow. Current first-party terms (checked 2026-11-16) create a material unresolved policy risk:
   - [Bot Developer Terms §6.2](https://telegram.org/tos/bot-developers#6-2-digital-goods-and-services) says transactions pertaining to digital goods/services in a TPA must use Telegram Stars exclusively.
   - [§6.2.1](https://telegram.org/tos/bot-developers#6-2-1-payment-disputes-for-digital-goods-and-services) requires a /paysupport path and expressly discourages real-time sales of valuable digital/virtual items that cannot be reclaimed, frozen or rescinded after chargeback.
   - [§7](https://telegram.org/tos/bot-developers#7-blockchain-integration) and the [Blockchain Guidelines](https://core.telegram.org/bots/blockchain-guidelines) permit TON assets and TON Connect wallet flows, but do not provide an explicit exemption from the Stars rule for P2P NFT resale.
   - [Stars Payments API](https://core.telegram.org/bots/payments-stars) says the Stars requirement applies to digital goods sold inside Telegram even when external web portals or providers exist.
   Written Telegram clarification is required for the exact user-to-user resale flow; do not infer permission from TON Connect compatibility. Issue #155 tracks the ruling.
5. Reconcile npm audit's deepmerge notice: GitHub Advisory Database withdrew GHSA-gcqx-w48m-w2h4 on 2026-11-16 because it does not describe a security vulnerability, but the npm audit feed still prints three low findings. See [the withdrawn advisory](https://github.com/advisories/GHSA-gcqx-w48m-w2h4) and Issue #256. No forced dependency override was applied.

**Decision remains BLOCKED — not a production release candidate.** No server signing/broadcast, mainnet, real TON, checkout, custody or user funds are enabled.

## 1. Current candidate tracks

| Track | Exact head at snapshot | Status | Release condition |
|---|---|---|---|
| NFT identity / Issue #213 / [PR #241](https://github.com/AzizIo/Vstore/pull/241) | `605612436df49db2a4414de28b9c5e8beb49d7b9` | Ready for Review (not merged); Backend #43823958161 and Frontend/API + API E2E #43823958345 passed; PG16 migration passed; 93 ahead / 0 behind main; no independent review submission recorded | Exact-head Backend, Frontend and API-backed E2E green; PostgreSQL 16 migration upgrade/downgrade and immutable-evidence tests pass; collection policy remains empty until explicitly approved |
| Backend artifact pin / Issue #206 / [PR #247](https://github.com/AzizIo/Vstore/pull/247) | `2c83cd3f2af3faba902d5d809ffe83f889fd6086` | Draft; strict compressed/decoded/base64 BOC guard passed Backend #43815732686 (866 tests), Frontend/API #43815732770 and Contract #43815732694 | Pin must be refreshed to the final contract artifact from the #248 track before integration |
| Contract lifecycle and refund ordering / Issue #225 / [PR #248](https://github.com/AzizIo/Vstore/pull/248) | `08daf5afe63c83f6f892fd469d90b3788e0f989c` | Draft; PR #250 canonical compressed-BOC verifier merged into this feature branch as squash `08daf5a`; exact-head Contract CI #43832141975 completed successfully | Require #43832141975 to pass on `08daf5a` before backend pin refresh |
| Earlier audit handoff / [PR #246](https://github.com/AzizIo/Vstore/pull/246) | `d0b19d2bd948edacbaf336285f9fff6afef0a748` | Draft; stale base | Based on older main and must not be used as current release evidence; this document is the current coordination snapshot |

PR heads and CI status can move. Always re-query the exact head SHA before treating a check as evidence.

## 2. Integration invariant: one contract build, one backend pin

The backend adapter must use the exact same DealEscrow build that the contract source and frozen manifest describe. The following values must agree across the backend manifest and `contracts/ton-escrow-poc/artifacts/frozen/manifest.json`:

- source commit and compiler provenance (workflow run, artifact ID, archive digest);
- compact ABI digest and Acton/Tolk versions;
- compiled code hash and base64, decoded and compressed BOC SHA-256 digests;
- StateInit hash, raw address and initial data hash.

PR #247 adds `backend/tests/escrow/test_escrow_artifact_alignment.py` to enforce this invariant and changes Backend CI path filters so contract-source/artifact changes also run the backend checks. The test validates the actual backend BOC file in all three representations: outer base64-encoded zlib bytes, decompressed BOC bytes, and canonical base64 of the decoded BOC. The earlier PR #247 head `c93867f2e3469807135bffd2f5a7701c4b1fbabe` passed Backend #43813770054, Frontend/API E2E #43813770080 and Contract #43813770065. After the stricter BOC assertions were added, new head `2c83cd3f2af3faba902d5d809ffe83f889fd6086` passed all three exact-head workflows: Backend #43815732686 (866 passed), Frontend/API E2E #43815732770, and Contract #43815732694.

- Backend CI: [#43813770054](https://github.com/AzizIo/Vstore/actions/runs/43813770054) — success;
- Frontend CI, including API-backed E2E: [#43813770080](https://github.com/AzizIo/Vstore/actions/runs/43813770080) — success;
- TON Escrow Contract CI: [#43813770065](https://github.com/AzizIo/Vstore/actions/runs/43813770065) — success.

Those results validate PR #247 against the frozen contract artifact present in that PR's merge tree. They do **not** validate it against the later contract candidate in PR #248. The gate is intentionally fail-closed: do not merge the contract update and backend pin as separate, incompatible revisions. Build one integrated candidate and rerun Backend, Contract, Frontend and API-backed E2E CI on the same resulting SHA.

## 3. Artifact state and why backend integration is still blocked

PR #248 now has a green exact-head Contract CI on `170dafb2180ec37ada903f3d17518c8d50d25c8c`: [run #43824843864](https://github.com/AzizIo/Vstore/actions/runs/43824843864). The run is tied to PR #248's exact head and reports:

- 35/35 Sandbox tests passed;
- Tolk formatting and static checks passed;
- source-controlled frozen ABI matches its manifest;
- fresh Acton build matches the frozen code hash and raw/base64 BOC digests;
- generated Acton wrapper + `@ton/core` StateInit/address/data cross-check passed;
- message BOC golden vectors passed;
- coverage: 85.9% lines / 68.7% branches for the contract tree.

The frozen candidate values are:

| Artifact | Exact candidate value |
|---|---|
| Source/provenance commit | `9d80a65a974b54f115fc697158974bdcee2c6be8` |
| Contract source change commit | `d87e4a81e07ec0c1e95619f6e5188c5be5433d62` |
| Green contract workflow / artifact | `#43824551943` / `14205079269` |
| Compiled code hash | `498A82F9B2DE206BE42108B6413D517CE63D4BCB1C20704D0BD89FCCC9509C46` |
| BOC base64 SHA-256 | `0e7bc7b35eee4ae7003fba0a0e5368df3428b7e32ad0f4fc5ddf0f3230d5daf3` |
| Decoded BOC SHA-256 | `86ed08596d0595c711aa2cf7659ee396ff443d7b01c65659b8e7543dd23c6173` |
| Compact ABI SHA-256 | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| StateInit hash / raw address hash | `4e3845e9d0b4df2f603b0ba7cceca4592276d25d8f43d2c611376344db393f75` |
| Raw address | `0:4e3845e9d0b4df2f603b0ba7cceca4592276d25d8f43d2c611376344db393f75` |
| Initial data hash | `faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b` |
| Acton / Tolk | `1.2.1` / `1.5.0` |

**Compressed-BOC packaging follow-up:** [PR #250](https://github.com/AzizIo/Vstore/pull/250) adds a canonical RFC 1950/DEFLATE stored-block encoder (fixed `78 01` header, 65,535-byte blocks, fixed LEN/NLEN framing and Adler-32 trailer) so the compressed bytes no longer depend on the host zlib compressor version/settings. The trade-off is a larger payload (raw BOC plus framing overhead), explicitly accepted for reproducibility. On exact PR #250 head `7b8775b628e9df9d22cbb18549bb9a51cf51828d`, Contract CI [#43829081437](https://github.com/AzizIo/Vstore/actions/runs/43829081437) passed the verifier tests, frozen artifact check, Acton compile, canonical compressed digest validation, wrapper/StateInit/message-vector checks, formatting, static checks and emulator suite. The new canonical compressed BOC SHA-256 is `8dce117db9f0ca883b0438c2f600b10c4caf18d7febd3db26a02d78c0191cbd7`; artifact #14208215967. PR #250 was merged into the #248 feature branch (not main) by squash commit `08daf5afe63c83f6f892fd469d90b3788e0f989c`. Fresh Contract CI [#43832141975](https://github.com/AzizIo/Vstore/actions/runs/43832141975) completed successfully on that exact new #248 head. The final contract candidate is build-verified; refresh #247 from this exact artifact and rerun integrated cross-track checks.

PR #247 is still pinned to the previous current-main artifact (code hash `9011F274...`, StateInit `67422729...`). It is not compatible with #248's candidate (`498A82F9...` / `4e3845e9...`) or the canonical packaging follow-up. Now that #250 is integrated into #248 and exact-head Contract CI passes, refresh #247's physical BOC file, backend manifest, `_CODE_HASH`, StateInit golden tests and adapter docs from that exact artifact. Run the cross-track guard and require Backend, Contract, Frontend and API-backed E2E checks on the same integrated SHA.

## 4. Security and acceptance gates still open

### NFT identity and collection policy

PR #241 implements proof-backed standard TEP-62 item/collection identity and an explicit collection policy. Its default allowlist is empty by design. Do not approve a collection based on a marketplace/indexer response or guessed code hash. An operator must review and approve the exact testnet collection address, collection code hash, item code hash and derivation policy. Existing deals without proof snapshots must remain blocked from unsafe terminal release.

### Independent TON/Tolk audit

No independent report has been accepted for the final combined source, ABI, code BOC and StateInit hashes. Internal review, green CI and emulator coverage are not an external audit. The reviewer must be independent of implementation authors, release operators and oracle/resolver signers, and the report must bind findings to immutable final hashes.

### Valueless live TON testnet acceptance

No evidence bundle currently demonstrates an owner-approved valueless live testnet lifecycle. Required evidence includes deployment transaction, trusted masterchain inclusion, account/getter snapshots, exact TEP-62 item owner transitions, oracle/resolver attestations, payout/refund traces, both bounce/retry paths and balance/storage-floor reconciliation. Disposable wallets and a reviewed valueless NFT/collection must be owner-approved; keys stay with their owners and never enter CI or backend services.

### Telegram Stars and NFT resale policy

Issue #155 remains a separate policy gate. Current official wording is stricter than a generic TON integration permission:

- [Bot Developer Terms §6.2](https://telegram.org/tos/bot-developers#6-2-digital-goods-and-services) requires transactions pertaining to digital goods/services in a TPA to be executed exclusively through Telegram Stars. §6.2.1 expressly discourages real-time sales of digital products/virtual items with inherent value that cannot be reclaimed, frozen, rescinded or suspended following a successful dispute/chargeback.
- [Bot Developer Terms §7](https://telegram.org/tos/bot-developers#7-blockchain-integration) and the [official Blockchain Guidelines](https://core.telegram.org/bots/blockchain-guidelines) require TON for Mini App blockchain assets and TON Connect for wallet interaction; the guidelines list TON collectible NFTs as permitted.

The public documents do not expressly classify this exact wallet-to-wallet resale of an already-existing TEP-62 NFT between two users, where the Mini App coordinates the sale, under §6.2, nor explicitly approve an external TON payment/escrow UX. The permission to use TON for blockchain functionality is not an exemption from §6.2.

Production support command surfaces are being added separately in [PR #251](https://github.com/AzizIo/Vstore/pull/251): production `/paysupport`, `/terms` and `/support` are information-only, fail closed and do not import the isolated Stars test router. Exact head `f51400e24ea5da8db4dc47bd2e450626f753bacc` has Frontend CI #1958 and Backend CI #1758 completed successfully; PR #251 remains Draft pending review and policy/operations gates. The PR does not implement an actual payment dispute case-management/refund workflow and full legal terms/support contact still require operator-provided URLs/username and legal review. Do not expose the isolated test bot in production.

Keep paid checkout, escrow deposits, platform resale fees and external payment CTAs disabled until Telegram answers the exact model in writing, production support flows are implemented, and legal review accepts the resulting UX. Do not treat Telegram Stars as interchangeable with TON escrow funds.

### Backend recipient-authorized outbound retry

Issue [#252](https://github.com/AzizIo/Vstore/issues/252) tracks a functional backend/frontend gap discovered during integration review: contract #248 adds `RetryFailedOutboundAction` (`0x56450009`), but the adapter/API/client do not expose a user retry action. The contract authorizes only the exact recipient stored in the matching BOUNCED descriptor. The provider can decode outbound descriptors for observer correlation, but they are not included in the runtime getter snapshot used by action preparation. Do not add a shortcut that accepts a client-supplied query ID or recipient. Required implementation: fresh trust-level-0 getter read of current deployed storage, code/snapshot verification, unique BOUNCED descriptor + salt + retry-window validation, exact verified recipient-wallet matching, durable idempotency, positive and adversarial tests including unsupported third-party recipients failing closed. This must be integrated after the #248/#247 artifact pins are aligned and included in same-SHA backend/frontend/contract validation.

## 5. Release controls

Until every gate above is closed:

- testnet-only protocol scope; no mainnet configuration or production checkout;
- no server-side signing, transaction broadcast, automated custody, real TON charges/refunds, seller payouts or real NFT transfer;
- Preview observer remains explicitly opt-in and disabled by default; production runtime must not mount testnet escrow paths except the isolated Preview stack;
- no collection allowlist entry without human approval;
- keep remediation PRs Draft until exact-head checks, source/artifact alignment and review are complete.

## 6. Merge and release sequence

1. PR #241 code/CI work is green on `605612436df49db2a4414de28b9c5e8beb49d7b9` (Backend + Frontend/API E2E + PG16 migration); obtain an independent code review and approve the collection policy/runbook before merging. Keep the collection allowlist empty by default.
2. PR #250 is already squash-integrated into the PR #248 feature branch. Exact-head Contract CI #43832141975 passed on `08daf5afe63c83f6f892fd469d90b3788e0f989c`; retain its canonical compressed BOC digest verification and frozen StateInit/address/data vectors.
3. Release integration refreshes PR #247's physical backend code BOC, manifest, expected code hash and message/StateInit vectors from the final post-#250 #248 artifact.
4. Implement [Issue #252](https://github.com/AzizIo/Vstore/issues/252): proof-bound recipient-authorized retry action across provider, backend adapter/API and frontend, with adversarial tests. Do not infer recipient from the caller's chosen query ID.
5. Create an integrated candidate tree containing #241, final #248 + #250, matching #247 backend pin and the #252 retry path. Run Backend, Contract, Frontend, API-backed E2E and migration checks on the **same exact SHA**; verify the cross-track artifact test passes.
6. Obtain independent TON/Tolk audit and remediate all Critical/High findings. Then complete owner-approved valueless testnet acceptance and record the evidence bundle.
7. Resolve Telegram/legal policy for the exact NFT resale flow before enabling paid checkout or any platform fee.

**Release decision at this snapshot: BLOCKED.** A green PR in isolation is not enough. The only acceptable candidate is a single immutable revision with matching contract/backend artifacts, all required CI green, independent review and approved live-testnet evidence.
