# Issue #225 — current contract security and release-gate assessment

**Assessment baseline:** `main` at `b592a4b889221aeb314e521a357b1746091a5976`  
**Network scope:** TON testnet only (`global_id = -3`)  
**Toolchain:** Acton 1.2.1 / Tolk 1.5.0  
**Assessment class:** internal source/CI review and integration check; not an independent audit.

## Latest integrated candidate — 2026-11-16 20:25 UTC

> This block supersedes every earlier feature head and CI snapshot below. Current main remains `b592a4b889221aeb314e521a357b1746091a5976`; **no escrow implementation PR has been merged to main**.

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

## Superseding feature-stack status — 2026-11-16 19:49 UTC

> Main's assessment baseline remains b592a4b889221aeb314e521a357b1746091a5976. The following active remediation status supersedes the earlier PR heads and CI outcomes further below; none of these feature PRs has been merged to main.

| Track | Current head | CI evidence |
|---|---|---|
| PR #248 — contract lifecycle | 08daf5afe63c83f6f892fd469d90b3788e0f989c | TON Contract CI #43832141975 passed; 35/35 Sandbox tests, frozen build/ABI/StateInit/message vectors |
| PR #241 — NFT identity | e1c891a99b5359585f2b7b2d391699a1a11737eb | Backend #43931218291 and Frontend #43931217044 passed; no independent review recorded |
| PR #247 — backend artifact pin + proof-bound retry | e98e1b6873d65c0504d05c9d217b8c08e8fc4120 | Backend #43942177488 passed (961); Frontend/API E2E #43942177624 passed (31 + 4) |
| PR #255 — integrated frontend retry stack | 1e1a12e9d79e936a5d0df28461012df562f6e8d0 | Backend #43942937032, Contract #43942936983 and Frontend/API E2E #43942937000 all passed on the exact same SHA: 961 backend, 35/35 Sandbox, 248 unit, 31 Playwright and 4 API-backed E2E |

The #255 candidate includes a proof-anchor hardening fix: retry preparation now requires getter seqno, block hash, provider ID and state-data hash to match the trust-level-0 provider tuple before persisting the getter snapshot or creating a wallet action. The regression proves a missing state-data hash fails closed without a DB commit.

Cross-layer path filters have been added so future escrow frontend changes trigger Backend CI and backend/frontend escrow changes trigger TON Contract CI. This makes the three workflow runs reproducible on a shared candidate SHA.

Issue #252 implementation is complete in the unmerged stack; its issue remains open for external audit and acceptance gates. All retry preparation remains unsigned and testnet-only.

### Remaining release gates

- Independent TON/Tolk audit against the exact frozen source, ABI, BOC and StateInit hashes.
- Operator approval of a testnet NFT collection policy; the allowlist remains empty by default.
- Owner-approved valueless live-testnet acceptance with transaction inclusion, NFT ownership, bounce/retry, refund/payout and storage-floor evidence.
- Written Telegram policy/legal review of the exact P2P TON NFT resale/payment flow. Current Bot Developer Terms §6.2 require Stars for digital goods/services transactions in a TPA; §6.2.1 requires /paysupport and expressly warns against real-time sale of valuable virtual items that cannot be reclaimed after chargeback. §7 and the [Blockchain Guidelines](https://core.telegram.org/bots/blockchain-guidelines) allow TON assets/TON Connect but do not expressly exempt P2P NFT sales from the Stars rule. The [Stars Payments API](https://core.telegram.org/bots/payments-stars) reiterates that the rule applies inside Telegram even if external portals/providers exist. The exact user-to-user resale classification remains unresolved; written Telegram clarification and legal review are required. See Issue #155.
- npm audit still prints three low deepmerge warnings although GHSA-gcqx-w48m-w2h4 was withdrawn by GitHub on 2026-11-16 as not describing a security vulnerability. Track stale feed output in Issue #256; do not force an unverified TON Connect upgrade.

**Decision: BLOCKED — not a production release candidate.** No server signing or broadcast, mainnet, real TON, checkout, custody or user funds are enabled. Green CI is not an independent audit or live testnet acceptance.

## 1. Mainline state and merged contract fixes

Current main includes the merged contract lifecycle and retry fixes:

- **PR #242** — terminal storage-floor preservation for a bounced carry-all execution-reserve refund. The retry re-reserves `TERMINAL_STORAGE_RESERVE` before `SEND_MODE_CARRY_ALL_BALANCE`.
- **PR #244** — analogous terminal storage-floor re-reservation before retrying a bounced fixed seller deployment allowance refund. PR #244 merged as `b592a4b889221aeb314e521a357b1746091a5976` on 2026-11-15.
- Main contract frozen artifact is based on source `2160aa6780efff2e44e5f8ae99b2d21cb8764740`, workflow #43767830764, artifact #14182942567.
- Current frozen DealEscrow code hash: `9011F274BC3D7E32B76A17F13FCBA17AC49429BB4EECBC4AB97FA202BDAC2940`.
- Current StateInit test vector: `674227296eff6ac5ee02c8e2eaa12857ac339d10a9ed7f4f7ea0591e7b4adfca`.
- These values are deterministic build/test vectors, not evidence of deployment.

The current main frozen contract manifest is not yet aligned with the backend adapter manifest. Main contract manifest pins code `9011F274...`; main backend manifest still pins `D822B8AFBB37027611A9A9DDC8E67C52F17BBBC45B4352C7F360693BD685CA54` and StateInit `29a40423...`. This is an integration blocker for adapter activation.

## 2. Current remediation PRs

### PR #241 — proof-anchored TEP-62 identity (Issue #213)

- Exact head: `605612436df49db2a4414de28b9c5e8beb49d7b9`.
- Ready for Review; not merged. Branch is 93 commits ahead and 0 behind main.
- Backend CI #43823958161 — success.
- Frontend CI #43823958345 — success, including API-backed E2E.
- PostgreSQL 16 migration upgrade, downgrade and re-upgrade — success.
- `verify_terminal_owner()` now fails closed if any associated deal has a missing/non-canonical collection address or if any deal's denormalized item/collection addresses differ from its own immutable identity snapshot. Added regression coverage for missing collection and item-address mismatch; there is no independent review submission yet.
- The allowlist defaults to empty; no concrete collection/item code hashes are approved.
- The implementation uses Pytoniq trust-level-0 LiteServer proof reads for item and collection account state at the same trusted masterchain block; checks standard TEP-62 item/collection storage, item and collection code hashes, collection-stored item code and minted index; reconstructs the item address from index + collection; and persists immutable identity evidence bound to a digest.
- The persisted validator rejects bool-as-int version values, missing/boolean/invalid chain timestamps, malformed hashes/addresses, mismatched policy digests and invalid index ranges.
- The final terminal-owner implementation rejects any missing/non-canonical per-deal collection address and checks every deal's item/collection columns against its own validated immutable identity snapshot; regression tests cover missing collection and mismatched item address.
- Independent security review is still required. No independent review submission is recorded.

### PR #250 — deterministic compressed BOC verifier follow-up

- PR #250 was merged into the #248 feature branch (not main) by squash commit `08daf5afe63c83f6f892fd469d90b3788e0f989c`.
- Former exact PR #250 head `7b8775b628e9df9d22cbb18549bb9a51cf51828d` passed Contract CI #43829081437; artifact #14208215967.
- Adds deterministic RFC 1950/DEFLATE stored-block encoding (fixed 65,535-byte blocks, fixed header and Adler-32), plus byte-exact, empty-input, multi-block and wrong-digest tests.
- Frozen contract manifest compressed BOC SHA-256: `8dce117db9f0ca883b0438c2f600b10c4caf18d7febd3db26a02d78c0191cbd7`.
- Updated #248 head is now `08daf5afe63c83f6f892fd469d90b3788e0f989c`; Contract CI #43832141975 completed successfully on this exact head; #247 can now refresh from this frozen artifact, followed by integrated cross-track CI.

### PR #247 — backend artifact pin and cross-track guard (Issue #206)

- Exact head: `2c83cd3f2af3faba902d5d809ffe83f889fd6086`; Draft, not merged.
- Backend CI #43815732686 — success (`866 passed`).
- Frontend/API E2E #43815732770 — success.
- Contract CI #43815732694 — success.
- Still pins the current-main artifact (`9011F274...` / StateInit `67422729...`), so it is incompatible with new #248 code `498A82F9...` / StateInit `4e3845e9...`; it must be refreshed after the compressed artifact digest is reconciled.
- Adds a cross-track test requiring backend and frozen Tolk manifests to match on source/provenance, ABI, code/BOC digests, StateInit/address and data hash.
- Validates the actual backend BOC file in compressed-zlib, decoded-BOC and canonical-base64 forms.
- Backend CI now runs when `contracts/ton-escrow-poc/**` changes.
- This is the required fix for the mainline contract/backend mismatch. Merge only together with the usual branch review/CI requirements and keep the strict cross-track test enabled.

### PR #248 — contract lifecycle/refund follow-up (Issue #225)

- Latest #248 head: `08daf5afe63c83f6f892fd469d90b3788e0f989c`; Draft; exact-head Contract CI #43832141975 passed.
- Exact Contract CI #43824843864 — success on that SHA; all 35 Sandbox tests passed, Tolk formatting/static checks, frozen ABI/raw BOC checks, StateInit/address cross-check and message vectors passed. Contract tree coverage is 85.9% lines / 68.7% branches.
- Compiled code hash: `498A82F9B2DE206BE42108B6413D517CE63D4BCB1C20704D0BD89FCCC9509C46`.
- StateInit hash/address: `4e3845e9d0b4df2f603b0ba7cceca4592276d25d8f43d2c611376344db393f75`.
- BOC base64/decoded digests: `0e7bc7b35eee4ae7003fba0a0e5368df3428b7e32ad0f4fc5ddf0f3230d5daf3` / `86ed08596d0595c711aa2cf7659ee396ff443d7b01c65659b8e7543dd23c6173`.
- **Canonical compressed-BOC verification is now integrated into #248's feature branch:** PR #250 was squash-merged into the #248 branch as `08daf5afe63c83f6f892fd469d90b3788e0f989c` (not main). The canonical stored-block zlib digest is `8dce117db9f0ca883b0438c2f600b10c4caf18d7febd3db26a02d78c0191cbd7`; exact #250 pre-merge head passed Contract CI #43829081437 / artifact #14208215967. Fresh Contract CI #43832141975 completed successfully on the new exact #248 head `08daf5afe63c83f6f892fd469d90b3788e0f989c`; refresh #247 from this artifact and require integrated cross-track checks.
- The 35-test suite covers seller-allowance-before-buyer-reserve retry, duplicate TEP-62 callback idempotency, timed-out escrowed-dispute resolver recovery, exact late buyer NFT return, replay rejection and sub-minimum action-value rejection.

### PR #251 — production bot support surfaces

- [PR #251](https://github.com/AzizIo/Vstore/pull/251) adds production command registration and information-only `/paysupport`, `/terms`, `/support` handlers without importing the isolated Stars test router.
- Exact head `f51400e24ea5da8db4dc47bd2e450626f753bacc`: Frontend CI #1958 and Backend CI #1758 completed successfully. PR remains Draft pending review and production-policy/operations gates.
- Contact/terms destinations appear only when operators configure validated `TELEGRAM_SUPPORT_USERNAME` and public HTTPS `TELEGRAM_TERMS_URL`. Missing values produce explicit unavailable messages; checkout remains off.
- This provides the user-facing command surfaces but does not itself implement case-managed payment disputes, production Stars refund orchestration, publish legal terms or satisfy Telegram/legal policy. Do not enable checkout until those separate gates are completed.

### Issue #252 — proof-bound backend retry for bounced outbound actions

- Contract #248 includes opcode `RetryFailedOutboundAction` (`0x56450009`), but backend action enum/adapter, API route and frontend action model do not expose it.
- The contract requires the exact recipient stored in the matching BOUNCED descriptor. The decoder already reads descriptors for observer RichBounce matching; the API getter snapshot does not currently include them for user action preparation.
- Issue [#252](https://github.com/AzizIo/Vstore/issues/252) is the release implementation task: read current storage at a trusted masterchain anchor, validate the exact BOUNCED descriptor/query ID/deal salt/retry window, require a verified wallet equal to the exact recipient, then prepare a durable idempotent unsigned request. Unsupported third-party recipients must fail closed.
- This is a functional integration blocker even though the contract's emulator tests pass. A raw client-provided query ID must never be enough to authorize a retry.

## 3. Required integration sequence

1. Complete independent code review and collection-policy review for #241; keep the default collection allowlist empty.
2. PR #250 has been integrated into the #248 feature branch; confirm Contract CI #43832141975 passes on exact head `08daf5afe63c83f6f892fd469d90b3788e0f989c`. The canonical compressed-BOC digest must be reproduced by the verifier alongside code/raw/base64 BOC and StateInit vectors.
3. Refresh #247 backend manifest/physical BOC/code pin/StateInit golden vectors from the final post-#250 #248 artifact, not from any older candidate.
4. Implement #252 proof-bound recipient-authorized outbound retry through provider, backend adapter/API and frontend, including positive and adversarial tests.
5. Build one integrated candidate tree containing #241 identity work, final #248 + #250 contract, matching #247 backend pin and #252 retry path.
6. Run Backend, Contract, Frontend/API E2E and PostgreSQL 16 migration tests on the same exact SHA. The strict backend↔contract artifact test must pass.
7. Obtain independent TON/Tolk audit and remediate all Critical/High findings.
8. Complete owner-approved valueless testnet acceptance and retain immutable evidence before any live-value path is considered.

## 4. External and operational gates

- No independent TON/Tolk audit report has been commissioned or accepted.
- No approved disposable testnet wallets, valueless NFT/collection, concrete collection allowlist or independent oracle/resolver operators are provisioned.
- No live deployment address, transaction trace, masterchain inclusion proof, getter snapshot or NFT owner transition has been recorded.
- Telegram's public Bot Developer Terms §6.2/§6.2.1 require Stars for covered digital-goods transactions and warn against irreversible virtual-item sales; §7 and the Blockchain Guidelines permit TON/TON Connect for blockchain functionality. The exact wallet-to-wallet secondary TEP-62 resale coordinated in a Mini App is not expressly classified by the public text. Written Telegram guidance and legal review remain necessary.
- PR #251 adds production `/paysupport`, `/terms` and `/support` information surfaces without importing the test router; exact-head Backend CI #1758 and Frontend CI #1958 are green. Review, configured terms/support destinations and full payment-support/refund workflow remain open. Full terms/support contacts and actual payment-support/refund workflow remain unconfigured and are still required before any Stars checkout.
- No mainnet configuration, production signing/broadcast, real TON charges/refunds, seller payouts or real NFT transfers are authorized.

**Assessment: BLOCKED.** Green individual PR checks are not equivalent to an integrated candidate, independent audit or live testnet acceptance.
