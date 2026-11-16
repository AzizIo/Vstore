# VILTARA TON Escrow — release gate snapshot

**Snapshot date:** 2026-11-16  
**Baseline:** `main` at `b592a4b889221aeb314e521a357b1746091a5976`  
**Network:** TON testnet only (`global_id = -3`)  
**Decision:** **BLOCKED — not a production release candidate**

This document supersedes the older handoff material based on `525215b9a51a34be811e73a1cc26995cd3cb25a1`. It is a release-coordination snapshot, not an independent security audit, live testnet acceptance, or authorization to deploy.

## 1. Current candidate tracks

| Track | Exact head at snapshot | Status | Release condition |
|---|---|---|---|
| NFT identity / Issue #213 / [PR #241](https://github.com/AzizIo/Vstore/pull/241) | `9be7a06fa1ca8207dfb0934b1bb36836bf869b50` | Draft; Backend CI #43816635436 passed; Frontend/API E2E #43816635486 passed; PG16 migration upgrade/downgrade/re-upgrade passed; previous test assertion now exercises the new #20 identity trigger independently | Exact-head Backend, Frontend and API-backed E2E green; PostgreSQL 16 migration upgrade/downgrade and immutable-evidence tests pass; collection policy remains empty until explicitly approved |
| Backend artifact pin / Issue #206 / [PR #247](https://github.com/AzizIo/Vstore/pull/247) | `2c83cd3f2af3faba902d5d809ffe83f889fd6086` | Draft; strict compressed/decoded/base64 BOC guard passed Backend #43815732686 (866 tests), Frontend/API #43815732770 and Contract #43815732694 | Pin must be refreshed to the final contract artifact from the #248 track before integration |
| Contract lifecycle and refund ordering / Issue #225 / [PR #248](https://github.com/AzizIo/Vstore/pull/248) | `75926f137f057c56253a87a63b52d8c08586c52f` | Draft; code hash/BOC digests refreshed but manifest warning remains; Contract CI #43815040780 fails strict StateInit vector comparison; agent has exact new vector and zlib SHA to pin | Frozen manifest must contain non-null StateInit, raw address and data hash reproduced by generated wrapper and `@ton/core`; exact-head emulator and static checks green; backend adapter must consume this same artifact |
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

## 3. Artifact state and why #248 is not ready yet

The current PR #248 exact-head build now identifies candidate code hash:

`498A82F9B2DE206BE42108B6413D517CE63D4BCB1C20704D0BD89FCCC9509C46`

The compiled BOC digests from exact artifact #14201523108 are:

- base64 BOC SHA-256: `0e7bc7b35eee4ae7003fba0a0e5368df3428b7e32ad0f4fc5ddf0f3230d5daf3`;
- decoded BOC SHA-256: `86ed08596d0595c711aa2cf7659ee396ff443d7b01c65659b8e7543dd23c6173`;
- zlib-compressed BOC SHA-256: `1766fd8f3542eb0f9aec9cd8ddd80cdd69297c97d58efbef91cdaf11fdb75407`.

The latest manifest at #248 head `75926f137f057c56253a87a63b52d8c08586c52f` has refreshed code/BOC fields but still contains the older compressed BOC digest and old StateInit vector. The generated Acton wrapper + `@ton/core` output from exact run #43815040780 / artifact #14201912732 reports:

- StateInit hash: `4e3845e9d0b4df2f603b0ba7cceca4592276d25d8f43d2c611376344db393f75`;
- raw address: `0:4e3845e9d0b4df2f603b0ba7cceca4592276d25d8f43d2c611376344db393f75`;
- initial data hash: `faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b`.

The current frozen manifest still pins StateInit `cfa1d4f9...`; the exact run failed at the expected strict vector comparison. Agent 2 has been sent the computed new vector and zlib digest. Refresh the complete manifest and `artifacts/VERIFYING.md`, then rerun Contract CI.

The previous emulator run #43814617994 (head `5b65380e33c814be95bea0c931873a7620b56783`) also found two lifecycle issues, which have not yet been revalidated against the newer source:

- In `duplicate nft delivery callbacks are idempotent and buyer refund bounce is retryable`, the buyer-refund retry leaves progress at `STATE_MANUAL_REVIEW` (13) where the test expects `STATE_BUYER_REFUND_PENDING` (9). The retry must actually create a new pending outbound action, preserve locked principal and be reconcilable; do not accept a terminal/manual-review state as a substitute for successful retry.
- In `expired dispute with NFT in escrow remains resolvable by the resolver quorum`, replay after the first resolver decision returns `Errors.Deadline` (710) before the state guard, while the expected state-specific rejection is `Errors.InvalidState` (703). Validate the state class first, then the deadline for an active dispute; preserve the explicit timed-out escrowed-dispute resolver path.

Both findings were sent to Agent 2. They require a fresh exact-head emulator run after manifest/vector and source are finalized.

The backend pin in PR #247 is currently for the prior frozen artifact (code hash `9011F274BC3D7E32B76A17F13FCBA17AC49429BB4EECBC4AB97FA202BDAC2940`, StateInit `674227296eff6ac5ee02c8e2eaa12857ac339d10a9ed7f4f7ea0591e7b4adfca`). It must be updated only from the final, successful #248 compiler artifact and must pass the cross-track test against that final manifest. No runtime action may be prepared against a stale code hash.

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

There is also a production support-surface gap for any future Stars checkout: `/paysupport` exists only in the isolated Stars test bot (`payments_test_bot.py` requires `environment=test` and a dedicated local test database). The regular production bot dispatcher does not register that payment router, and its `BOT_COMMANDS` menu omits `paysupport`, `terms` and `support`. Before any live digital-goods checkout, wire a production-safe payment support handler and publish/test all three commands; do not expose the isolated test bot in production.

Keep paid checkout, escrow deposits, platform resale fees and external payment CTAs disabled until Telegram answers the exact model in writing, production support flows are implemented, and legal review accepts the resulting UX. Do not treat Telegram Stars as interchangeable with TON escrow funds.

## 5. Release controls

Until every gate above is closed:

- testnet-only protocol scope; no mainnet configuration or production checkout;
- no server-side signing, transaction broadcast, automated custody, real TON charges/refunds, seller payouts or real NFT transfer;
- Preview observer remains explicitly opt-in and disabled by default; production runtime must not mount testnet escrow paths except the isolated Preview stack;
- no collection allowlist entry without human approval;
- keep remediation PRs Draft until exact-head checks, source/artifact alignment and review are complete.

## 6. Merge and release sequence

1. Agent 1 completes PR #241, fixes every exact-head Backend lint/test failure, proves PostgreSQL 16 migration behavior and obtains exact-head Backend + Frontend/API E2E success.
2. Agent 2 completes PR #248, resolves every lifecycle/bounce/retry finding, regenerates the frozen compiler artifacts and passes exact-head Contract CI with non-null independently reproduced StateInit/address/data vectors.
3. Release integration refreshes PR #247's backend code BOC, manifest, expected code hash and message/StateInit vectors from that final #248 artifact.
4. Create an integrated candidate tree containing the final contract source and matching backend pin. Run Backend, Contract, Frontend, API-backed E2E and migration checks on the **same exact SHA**; verify the cross-track artifact test passes.
5. Obtain independent TON/Tolk audit and remediate all Critical/High findings. Then complete owner-approved valueless testnet acceptance and record the evidence bundle.
6. Resolve Telegram/ legal policy for the exact NFT resale flow before enabling paid checkout or any platform fee.

**Release decision at this snapshot: BLOCKED.** A green PR in isolation is not enough. The only acceptable candidate is a single immutable revision with matching contract/backend artifacts, all required CI green, independent review and approved live-testnet evidence.
