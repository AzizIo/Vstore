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
- Independent review is still required. The PR currently has no submitted review record. A read-only release review found the core same-block proof/anchor path fail-closed; one defense-in-depth suggestion remains to reject any non-canonical per-deal collection address in terminal-owner reconciliation rather than discarding malformed entries.

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

- Latest PR head: `170dafb2180ec37ada903f3d17518c8d50d25c8c`; Draft.
- Exact Contract CI #43824843864 — success on that exact SHA; all 35 Sandbox tests passed, Tolk formatting and static checks passed, frozen ABI/raw BOC verification passed, StateInit/address cross-check passed, and message BOC golden vectors passed. Contract tree coverage is 85.9% lines / 68.7% branches.
- Compiled code hash: `498A82F9B2DE206BE42108B6413D517CE63D4BCB1C20704D0BD89FCCC9509C46`.
- StateInit hash/address: `4e3845e9d0b4df2f603b0ba7cceca4592276d25d8f43d2c611376344db393f75`.
- BOC base64/decoded digests: `0e7bc7b35eee4ae7003fba0a0e5368df3428b7e32ad0f4fc5ddf0f3230d5daf3` / `86ed08596d0595c711aa2cf7659ee396ff443d7b01c65659b8e7543dd23c6173`.
- **Compressed BOC digest still requires reconciliation:** frozen manifest says `dbca9581e8ce45f2ca68f6dc766e149f4e7ca25a2c740fb58b2b4448c6189963`; my independent Python `zlib.compress(raw_boc)` of BOC bytes from exact artifact #14206172246 yields `1766fd8f3542eb0f9aec9cd8ddd80cdd69297c97d58efbef91cdaf11fdb75407`. Contract CI's build verifier does not currently validate this compressed field. It does not invalidate the 35/35 emulator or StateInit results, but the backend BOC file/manifest pair must be generated and checked together before updating #247.
- The exact Sandbox suite now includes seller-allowance-before-buyer-reserve retry, duplicate TEP-62 callback idempotency, timed-out escrowed-dispute resolver recovery, exact late buyer NFT return, replay rejection and sub-0.01 TON action-value rejection. The two previously failing lifecycle paths have been corrected and the 35-test run passes.

## 3. Required integration sequence

1. Complete independent code review and collection-policy review for #241; keep the default collection allowlist empty.
2. Finish #248: refresh frozen manifest, code/BOC/StateInit vectors and `artifacts/VERIFYING.md` from one exact successful compiler run; resolve the resolver replay ordering and rerun all emulator tests.
3. Refresh #247 backend manifest/BOC/ABI pin from the final #248 artifact, not from any older candidate.
4. Build one integrated candidate tree containing #241 identity work, the final #248 contract and matching #247 backend pin.
5. Run Backend, Contract, Frontend/API E2E and PostgreSQL 16 migration tests on the same exact SHA. The strict backend↔contract artifact test must pass.
6. Obtain independent TON/Tolk audit and remediate all Critical/High findings.
7. Complete owner-approved valueless testnet acceptance and retain immutable evidence before any live-value path is considered.

## 4. External and operational gates

- No independent TON/Tolk audit report has been commissioned or accepted.
- No approved disposable testnet wallets, valueless NFT/collection, concrete collection allowlist or independent oracle/resolver operators are provisioned.
- No live deployment address, transaction trace, masterchain inclusion proof, getter snapshot or NFT owner transition has been recorded.
- Telegram's public Bot Developer Terms §6.2/§6.2.1 require Stars for covered digital-goods transactions and warn against irreversible virtual-item sales; §7 and the Blockchain Guidelines permit TON/TON Connect for blockchain functionality. The exact wallet-to-wallet secondary TEP-62 resale coordinated in a Mini App is not expressly classified by the public text. Written Telegram guidance and legal review remain necessary.
- The production bot does not wire the existing isolated test-bot `/paysupport` handler; production-safe `/paysupport`, `/terms` and `/support` are required before any Stars checkout.
- No mainnet configuration, production signing/broadcast, real TON charges/refunds, seller payouts or real NFT transfers are authorized.

**Assessment: BLOCKED.** Green individual PR checks are not equivalent to an integrated candidate, independent audit or live testnet acceptance.
