# VILTARA TON Escrow — release gate snapshot

**Snapshot date:** 2026-11-16  
**Baseline:** `main` at `b592a4b889221aeb314e521a357b1746091a5976`  
**Network:** TON testnet only (`global_id = -3`)  
**Decision:** **BLOCKED — not a production release candidate**

This document supersedes the older handoff material based on `525215b9a51a34be811e73a1cc26995cd3cb25a1`. It is a release-coordination snapshot, not an independent security audit, live testnet acceptance, or authorization to deploy.

## 1. Current candidate tracks

| Track | Exact head at snapshot | Status | Release condition |
|---|---|---|---|
| NFT identity / Issue #213 / [PR #241](https://github.com/AzizIo/Vstore/pull/241) | `e296f1d3586473c775abcbea6f845237f7474954` | Draft; Backend and Frontend/API CI running | Exact-head Backend, Frontend and API-backed E2E green; PostgreSQL 16 migration upgrade/downgrade and immutable-evidence tests pass; collection policy remains empty until explicitly approved |
| Backend artifact pin / Issue #206 / [PR #247](https://github.com/AzizIo/Vstore/pull/247) | `c93867f2e3469807135bffd2f5a7701c4b1fbabe` | Draft; Backend, Frontend/API E2E and Contract CI passed | Pin must be refreshed to the final contract artifact from the #248 track before integration |
| Contract lifecycle and refund ordering / Issue #225 / [PR #248](https://github.com/AzizIo/Vstore/pull/248) | `4140eb78d4218b8f52a6828b8d6cb3fb44fa47d9` | Draft; exact-head Contract CI running | Frozen manifest must contain non-null StateInit, raw address and data hash reproduced by generated wrapper and `@ton/core`; exact-head emulator and static checks green; backend adapter must consume this same artifact |
| Earlier audit handoff / [PR #246](https://github.com/AzizIo/Vstore/pull/246) | `d0b19d2bd948edacbaf336285f9fff6afef0a748` | Draft; stale base | Based on older main and must not be used as current release evidence; this document is the current coordination snapshot |

PR heads and CI status can move. Always re-query the exact head SHA before treating a check as evidence.

## 2. Integration invariant: one contract build, one backend pin

The backend adapter must use the exact same DealEscrow build that the contract source and frozen manifest describe. The following values must agree across the backend manifest and `contracts/ton-escrow-poc/artifacts/frozen/manifest.json`:

- source commit and compiler provenance (workflow run, artifact ID, archive digest);
- compact ABI digest and Acton/Tolk versions;
- compiled code hash and base64, decoded and compressed BOC SHA-256 digests;
- StateInit hash, raw address and initial data hash.

PR #247 adds `backend/tests/escrow/test_escrow_artifact_alignment.py` to enforce this invariant and changes Backend CI path filters so contract-source/artifact changes also run the backend checks. On PR #247 head `c93867f2e3469807135bffd2f5a7701c4b1fbabe`, these checks passed:

- Backend CI: [#43813770054](https://github.com/AzizIo/Vstore/actions/runs/43813770054) — success;
- Frontend CI, including API-backed E2E: [#43813770080](https://github.com/AzizIo/Vstore/actions/runs/43813770080) — success;
- TON Escrow Contract CI: [#43813770065](https://github.com/AzizIo/Vstore/actions/runs/43813770065) — success.

Those results validate PR #247 against the frozen contract artifact present in that PR's merge tree. They do **not** validate it against the later contract candidate in PR #248. The gate is intentionally fail-closed: do not merge the contract update and backend pin as separate, incompatible revisions. Build one integrated candidate and rerun Backend, Contract, Frontend and API-backed E2E CI on the same resulting SHA.

## 3. Artifact state and why #248 is not ready yet

The current PR #248 manifest identifies a new candidate code hash:

`AA6F1024D4DB9B6B9AD89AD98C76D3BA72F34E0D49433B0A88C4F9EDA53B852F`

Its manifest still has `state_init_hash: null`, `raw_address: null` and a non-null intermediate warning. An earlier CI build artifact contained a generated StateInit vector, but it is not sufficient by itself to clear the gate: the **final exact-head** workflow must regenerate the code/BOC and independently verify the StateInit/address/data vector with the generated wrapper and `@ton/core`. The final frozen manifest and `artifacts/VERIFYING.md` must then describe the same exact source commit and artifact. Never copy a vector from an older run into a newer source revision without reproducing it.

The backend pin in PR #247 is currently for the prior frozen artifact (code hash `9011F274BC3D7E32B76A17F13FCBA17AC49429BB4EECBC4AB97FA202BDAC2940`, StateInit `674227296eff6ac5ee02c8e2eaa12857ac339d10a9ed7f4f7ea0591e7b4adfca`). It must be updated only from the final, successful #248 compiler artifact and must pass the cross-track test against that final manifest. No runtime action may be prepared against a stale code hash.

## 4. Security and acceptance gates still open

### NFT identity and collection policy

PR #241 implements proof-backed standard TEP-62 item/collection identity and an explicit collection policy. Its default allowlist is empty by design. Do not approve a collection based on a marketplace/indexer response or guessed code hash. An operator must review and approve the exact testnet collection address, collection code hash, item code hash and derivation policy. Existing deals without proof snapshots must remain blocked from unsafe terminal release.

### Independent TON/Tolk audit

No independent report has been accepted for the final combined source, ABI, code BOC and StateInit hashes. Internal review, green CI and emulator coverage are not an external audit. The reviewer must be independent of implementation authors, release operators and oracle/resolver signers, and the report must bind findings to immutable final hashes.

### Valueless live TON testnet acceptance

No evidence bundle currently demonstrates an owner-approved valueless live testnet lifecycle. Required evidence includes deployment transaction, trusted masterchain inclusion, account/getter snapshots, exact TEP-62 item owner transitions, oracle/resolver attestations, payout/refund traces, both bounce/retry paths and balance/storage-floor reconciliation. Disposable wallets and a reviewed valueless NFT/collection must be owner-approved; keys stay with their owners and never enter CI or backend services.

### Telegram Stars and NFT resale policy

Issue #155 remains a separate policy gate. There is no recorded written ruling approving the exact third-party P2P NFT resale/purchase flow inside the Telegram Mini App. Keep paid checkout and any fee-taking resale flow disabled until Telegram's written position and legal review are recorded. Do not treat Telegram Stars as interchangeable with TON escrow funds.

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
