# Issue #225 — current contract security and release-gate assessment

**Assessment baseline:** `main` at `b592a4b889221aeb314e521a357b1746091a5976`  
**Network scope:** TON testnet only (`global_id = -3`)  
**Toolchain:** Acton 1.2.1 / Tolk 1.5.0  
**Assessment class:** internal source/CI review and integration check; not an independent audit.

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

- Exact head: `7b8775b628e9df9d22cbb18549bb9a51cf51828d`; Draft and stacked on #248's exact prior head.
- Contract CI #43829081437 — SUCCESS; artifact #14208215967.
- Adds deterministic RFC 1950/DEFLATE stored-block encoding (fixed 65,535-byte blocks, fixed header and Adler-32), plus tests for byte-exact small vectors, empty input, multi-block round-trip and wrong-digest rejection.
- Updates frozen contract manifest compressed BOC SHA-256 to `8dce117db9f0ca883b0438c2f600b10c4caf18d7febd3db26a02d78c0191cbd7`.
- This closes the contract CI verifier gap on the #250 stack, but #250 is not yet integrated into the #248 branch. Keep it stacked until reviewed/integrated; rerun Contract CI on the new resulting #248 head.

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

- Latest #248 head: `170dafb2180ec37ada903f3d17518c8d50d25c8c`; Draft.
- Exact Contract CI #43824843864 — success on that SHA; all 35 Sandbox tests passed, Tolk formatting/static checks, frozen ABI/raw BOC checks, StateInit/address cross-check and message vectors passed. Contract tree coverage is 85.9% lines / 68.7% branches.
- Compiled code hash: `498A82F9B2DE206BE42108B6413D517CE63D4BCB1C20704D0BD89FCCC9509C46`.
- StateInit hash/address: `4e3845e9d0b4df2f603b0ba7cceca4592276d25d8f43d2c611376344db393f75`.
- BOC base64/decoded digests: `0e7bc7b35eee4ae7003fba0a0e5368df3428b7e32ad0f4fc5ddf0f3230d5daf3` / `86ed08596d0595c711aa2cf7659ee396ff443d7b01c65659b8e7543dd23c6173`.
- **Canonical compressed-BOC follow-up:** [PR #250](https://github.com/AzizIo/Vstore/pull/250) is stacked on the exact #248 head. It adds a portable RFC 1950/DEFLATE stored-block encoder and makes Contract CI verify the compressed representation itself. Canonical compressed digest: `8dce117db9f0ca883b0438c2f600b10c4caf18d7febd3db26a02d78c0191cbd7`. Exact PR #250 head `7b8775b628e9df9d22cbb18549bb9a51cf51828d` passed Contract CI #43829081437 (artifact #14208215967), including verifier tests, Acton build, StateInit/message vectors, static checks and the emulator suite. **PR #250 is green but still stacked; it must be integrated into #248 and Contract CI rerun on the resulting #248 head before #247 is refreshed.**
- The 35-test suite covers seller-allowance-before-buyer-reserve retry, duplicate TEP-62 callback idempotency, timed-out escrowed-dispute resolver recovery, exact late buyer NFT return, replay rejection and sub-minimum action-value rejection.

### PR #251 — production bot support surfaces

- [PR #251](https://github.com/AzizIo/Vstore/pull/251) adds production command registration and information-only `/paysupport`, `/terms`, `/support` handlers without importing the isolated Stars test router.
- Exact head `018ee6ed4181fe8fc4f2e7ee2504e199f37d5dd7`: Frontend CI #43831818022 and Backend CI #43831818067 are running. PR remains Draft pending exact-head CI and review.
- Contact/terms destinations appear only when operators configure validated `TELEGRAM_SUPPORT_USERNAME` and public HTTPS `TELEGRAM_TERMS_URL`. Missing values produce explicit unavailable messages; checkout remains off.
- This provides the user-facing command surfaces but does not itself implement case-managed payment disputes, production Stars refund orchestration, publish legal terms or satisfy Telegram/legal policy. Do not enable checkout until those separate gates are completed.

### Issue #252 — proof-bound backend retry for bounced outbound actions

- Contract #248 includes opcode `RetryFailedOutboundAction` (`0x56450009`), but backend action enum/adapter, API route and frontend action model do not expose it.
- The contract requires the exact recipient stored in the matching BOUNCED descriptor. The decoder already reads descriptors for observer RichBounce matching; the API getter snapshot does not currently include them for user action preparation.
- Issue [#252](https://github.com/AzizIo/Vstore/issues/252) is the release implementation task: read current storage at a trusted masterchain anchor, validate the exact BOUNCED descriptor/query ID/deal salt/retry window, require a verified wallet equal to the exact recipient, then prepare a durable idempotent unsigned request. Unsupported third-party recipients must fail closed.
- This is a functional integration blocker even though the contract's emulator tests pass. A raw client-provided query ID must never be enough to authorize a retry.

## 3. Required integration sequence

1. Complete independent code review and collection-policy review for #241; keep the default collection allowlist empty.
2. Integrate reviewed PR #250 into #248, then rerun Contract CI on the resulting exact #248 SHA. The canonical compressed-BOC digest must be reproduced by the verifier alongside code/raw/base64 BOC and StateInit vectors.
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
- PR #251 is adding production `/paysupport`, `/terms` and `/support` information surfaces without importing the test router; exact-head Backend/Frontend CI and review remain pending. Full terms/support contacts and actual payment-support/refund workflow remain unconfigured and are still required before any Stars checkout.
- No mainnet configuration, production signing/broadcast, real TON charges/refunds, seller payouts or real NFT transfers are authorized.

**Assessment: BLOCKED.** Green individual PR checks are not equivalent to an integrated candidate, independent audit or live testnet acceptance.
