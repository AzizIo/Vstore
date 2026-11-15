# TON Escrow — contract security audit & lifecycle coverage (Issue #214)

**Review class:** internal, source-level, static/emulator-gap assessment.  
**Not an independent audit. Not a release approval.**  
**Review baseline:** `dd7e5045450f4c95e564fae72c4200f3d921d196`  
**Contract source:** `contracts/ton-escrow-poc/contracts/DealEscrow.tolk`  
**Frozen manifest:** `contracts/ton-escrow-poc/artifacts/frozen/manifest.json`  
**Protocol:** v1, TON testnet scope, Acton 1.2.1 / Tolk 1.5.0.

## Executive result

The inspected source contains meaningful fail-closed controls: fixed per-deal roles/item/amounts, signed ConfigParam 19 testnet check, 2-of-3 signatures over typed cell hashes, distinct oracle/resolver key sets, attempt/query binding, exact NFT sender/payload checks, and manual-review transitions for bounced internal actions.

This pass does **not** establish that the contract is safe to deploy. The current branch fixes two concrete defects from the initial review: late oracle/resolver attestations are rejected after the stored deadline, and a secondary bounce no longer overwrites an already-terminal `SETTLED`, `REFUNDED` or `EXPIRED` state. The emulator suite remains materially narrower than the requested lifecycle matrix; the terminal reserve/payout test still bypasses signature checking for accounting isolation; and oracle evidence semantics remain a 2-of-3 operator trust boundary. No live testnet transactions or independent specialist review were performed. The current reviewed test head is `6f0aee90fe760948ef9a1ab32106496e8538b636`; the exact-head TON Contract CI run #43703777523 succeeded, including build/frozen digest checks and 16/16 Acton emulator tests.

## Findings

### F-01 — MITIGATED IN BRANCH: late secondary bounce no longer overwrites terminal state

**Location:** `DealEscrow.tolk:onBouncedMessage`; regression in `DealEscrow.test.tolk`.

The original handler unconditionally changed every deal to `STATE_MANUAL_REVIEW`, including after principal settlement. The branch now returns without changing storage when the current state is `STATE_SETTLED`, `STATE_REFUNDED` or `STATE_EXPIRED`. A bounce while the deal is non-terminal still moves it to manual review.

**Evidence**
- The updated emulator test seeds `STATE_SETTLED`, submits a synthetic bounced settlement message and asserts the state remains `STATE_SETTLED`.
- The specific seller deployment-allowance refund can be emitted after principal settlement, so preserving the terminal getter state prevents the secondary bounce from hiding the completed principal outcome.
- This remains a callback-level synthetic bounce test. A full action-phase integration test with a rejecting seller destination, real contract-generated bounce and post-bounce balances is still missing.

**Residual limitation**
The handler still does not decode and correlate the bounced envelope to the outbound operation, query ID, attempt or expected destination. The terminal-state overwrite impact is mitigated, but complete bounce provenance/recovery coverage is not established. Keep this residual item in the external review scope.

### F-02 — HIGH coverage blocker: terminal/refund/dispute/expiry lifecycle is not proven by emulator tests

**Locations:** contract transitions `DealEscrow.tolk:313-509`, `592-727`; emulator test file `DealEscrow.test.tolk`.

The visible test file has a focused happy-path deposit/funding/acceptance, rejection for mainnet global ID, stale oracle-attempt rejection, one reserve/payout simulation, signature helper tests, and one synthetic bounce-to-manual-review test. The single terminal reserve test starts from a pre-seeded `STATE_DELIVERED_DISPUTE_WINDOW`, funds via a plain transfer, and uses `testing.setChecksigIgnore(true)` for the payout attestation. It therefore does not demonstrate a complete real-signature end-to-end delivery→payout flow or a complete refund flow.

The current emulator tests do not prove the full requested outcomes for:
- pre-delivery dispute → resolver buyer outcome → NFT returned → buyer principal refund;
- pre-delivery dispute → seller outcome → NFT release/return and terminal balance;
- post-delivery dispute → voluntary buyer NFT return → resolver buyer outcome/refund;
- post-delivery dispute → seller outcome;
- each deadline boundary (-1, exact deadline, +1);
- expiry before funding, failed NFT return, payout/refund reconciliation timeout;
- bounced payout, principal refund, deployment allowance refund and carry-all-balance reserve return;
- duplicate/replayed/out-of-order resolver messages and terminal-state re-entry;
- terminal NFT owner + exact principal/reserve delta invariants for every branch.

**Impact**
No exploit is asserted solely from missing tests. The project Definition of Done requires these invariants, but they are not evidenced by current emulator tests. This blocks a claim of complete lifecycle coverage and blocks Gate B.

**Recommendation**
Add deterministic Acton emulator tests for each state/actor/timing/failure branch, assert getters, NFT owner and before/after TON balances, and exercise real Ed25519 signatures on contract entrypoint paths. Do not use the checksig-ignore bypass except isolated accounting unit tests, which must be labeled as such.

### Provenance note — frozen manifest source commit differs, but no contract source drift was found

**Location:** `artifacts/frozen/manifest.json`; `contracts/DealEscrow.tolk`.

The manifest records `source_commit=2913ea7d53ea7344f57d6503142c08e0b328bc7d`, while this review baseline is `dd7e5045450f4c95e564fae72c4200f3d921d196`. A direct Git-tree comparison confirms identical blob SHAs at both commits for:
- `DealEscrow.tolk`: `3b7e7c220020ff7614fec0267fb3f427b7474dd4`
- `types.tolk`: `5720ff7090138641c6354c850b7322d60451b3a5`
- `signatures.tolk`: `67453fc0789efa403e366b33998ee82323413465`
- pre-existing `DealEscrow.test.tolk`: `5b2d0ae96103663f0ef0eb795237ddd8d1c7fd34`

Therefore this review found **no contract source drift** in these files between those commits. The difference in manifest commit labels is a provenance bookkeeping caveat, not a finding that the bytecode differs from the source. The manifest itself explicitly warns it does not prove reproducibility, StateInit correctness or audit safety.

**Remaining evidence**
- Rebuild the exact reviewed head SHA with the pinned Acton/Tolk toolchain.
- Compare generated ABI, compiled BoC SHA-256 and code hash with the existing manifest.
- If the build is byte-identical, record the exact-head run as confirming equivalence. If it differs, coordinate a new frozen manifest, ABI snapshot and BoC/code hash with Issue #206 adapter owner and #197 parent.
- Independently reproduce StateInit/address for golden vectors before external review.

### F-04 — MEDIUM: reserve/payout integration test bypasses signature verification

**Location:** `DealEscrow.test.tolk:504-516`.

The terminal accounting test explicitly sets `testing.setChecksigIgnore(true)` before invoking the contract with all-zero dummy signatures and turns it off immediately afterward. This is clearly scoped to the test, not deployable code, and the signature helper has separate cryptographic tests. Still, the payout test does not verify the composition of valid signatures + route/context/state validation + terminal accounting in one contract execution. It should be complemented by real signed oracle/resolver integration fixtures.

**Impact**
Test suite may pass the financial settlement branch if the signature gate is accidentally bypassed in test configuration, because the existing test does bypass it. This is a validation blind spot, not proof of production bypass.

### F-06 — MITIGATED IN BRANCH: late oracle and resolver attestations are rejected

**Locations:** `DealEscrow.tolk:handleOracleAttestation` and `handleDisputeResolution`.

Both handlers now require a non-zero stored state deadline and `blockchain.now() <= progress.deadlineUnix` before signature verification or state mutation. Messages submitted after the deadline fail with `Errors.Deadline`. The inclusive boundary matches the contract's other deadline checks.

**Regression evidence**
- The late-oracle emulator case advances time beyond the delivery-confirmation deadline, submits an oracle attestation and expects `Errors.Deadline`; state remains `STATE_NFT_RELEASE_PENDING`.
- The late-resolver emulator case opens a pre-delivery dispute, advances beyond its arbitration deadline, submits the resolver decision and expects `Errors.Deadline`; state remains disputed and the NFT remains held by escrow.
- These tests no longer turn on `testing.setChecksigIgnore`; the deadline guard is reached before signature processing.

**Remaining boundary coverage**
The exact `deadline - 1`, `deadline`, `deadline + 1` matrix has not been exhaustively repeated for every action/deadline type. The code-level late-message race is fixed for these handlers, but the complete deadline matrix remains part of F-02.

## Positive controls observed

- State-changing entrypoints check testnet network ID and signed ConfigParam 19 global ID `-3`; mainnet fixture `-239` rejection exists in test.
- Immutable per-deal roles, item address, deal salt, principal, reserve and keys are stored in initial terms.
- Exact TEP-62 item sender, previous owner, query ID, deadline, inline payload selector, magic and deal salt are required for valid deposit/return.
- Oracle context binds domain, protocol, testnet ID, escrow address, salt, action, attempt; route binds item/source/destination/amount/query ID; 2-of-3 slot-specific signatures are validated.
- Oracle/resolver key sets are required to be unique/disjoint by `assertTestnet`.
- Buyer funding requires exactly principal + execution reserve and buyer acceptance precedes NFT release.
- Resolver signature context is separately domain-separated and bound to dispute attempt/evidence.
- No direct owner withdraw/upgrade method was observed in the inspected contract source.

## Test coverage assessment

| Requirement | Current evidence | Result |
|---|---|---|
| Build, format, ABI generation | TON Contract CI run #43703777523 on `6f0aee90fe760948ef9a1ab32106496e8538b636` passed frozen verifier, source ABI snapshot, Acton build/code+BoC digest check, wrapper generation, formatting, static checks and artifact upload | Passed on current reviewed test head |
| Exact testnet ConfigParam 19 gate | mainnet global ID fixture | Partial |
| Exact NFT item deposit | happy path + wrong-item behavior in existing plan | Partial |
| Buyer funding and acceptance | happy path | Partial |
| Signature helper quorum | 3/3, 2/3, 1/3, duplicate slot helper | Partial; not end-to-end |
| Full pre/post delivery dispute | no complete emulator traces | Missing |
| Buyer principal refund | no full real-signature path | Missing |
| Seller expiry/return | not fully exercised | Missing |
| Bounce handling | non-terminal bounce→manual review and terminal-state preservation regression; real generated bounce/action-phase matrix absent | Partial |
| Late oracle/resolver deadline rejection | post-deadline oracle/resolver regressions pass on current head; deadline -1/exact/+1 matrix for every deadline remains incomplete | Improved; partial |
| Terminal principal/NFT/reserve invariants across branches | one seeded seller payout/reserve case | Missing |
| Replay and stale attempt | stale oracle check only | Partial |
| Live valueless testnet lifecycle | none attached | Blocked |
| Independent TON/Tolk audit | none attached | Blocked |

## Frozen artifact provenance and exact-head validation

The frozen manifest was rebuilt after the contract-source deadline/bounce changes and now binds the compiled bytecode to source commit `079fa1f4717cde1d8963faed180b2fa1e9ea9ac6`. The final current branch head `6f0aee90fe760948ef9a1ab32106496e8538b636` adds a test-only regression isolation change after that source commit; the exact-head CI rebuild proves the compiled code and BoC still match the manifest.

- Current reviewed/test head: `6f0aee90fe760948ef9a1ab32106496e8538b636`
- Manifest contract-source commit: `079fa1f4717cde1d8963faed180b2fa1e9ea9ac6`
- Latest exact-head TON Contract CI: [run #43703777523](https://github.com/AzizIo/Vstore/actions/runs/43703777523) — SUCCESS
- CI artifact: `ton-escrow-acton-artifacts`, artifact ID `14157294381`
- Manifest build artifact ID: `14157303414`
- Original archive SHA-256: `82e8dc2bfda3b9418003aa6a9994c487a9086bec9416436b59db752ad2d087e5`
- Compiled code hash: `359B02C177CE033C6FE1A673C4E04B59D6D43434AF09B1CBE4BDCD8BE4779450`
- Compiled code BoC SHA-256: `df82a5603142e77344b3f201c13d6c77d3900893bf06cfe719bece784caf0422`
- ABI compact SHA-256: `25fc5f338f45db7d7198961a75c1d5cfe04f996ae36013cca0d70f03870c3923`
- Toolchain: Acton 1.2.1 / Tolk 1.5.0
- Emulator result: 16/16 tests passed on exact reviewed test head.

## Independent reviewer status

**NOT PERFORMED.** No reviewer identity/qualifications, signed report, engagement record or independent finding disposition is available. This internal review cannot be represented as external audit.

## Live testnet status

**BLOCKED — owner approval required.** No transactions, deployment, wallet connection, real funds or testnet NFT transfers were performed for this pass.

## Decision

**BLOCKED for testnet acceptance / any production use.** The contract may only proceed as an isolated disabled testnet PoC under the existing Gate A controls. Do not enable signing, mount public routes, claim buyer protection, or merge as proof of live acceptance. Resolve or explicitly disposition the above findings, complete missing emulator matrix, rebuild/bind the frozen artifact to an exact source SHA, and obtain independent TON/Tolk review before Gate B.


## Follow-up changes on the current branch

- F-01: terminal states now survive late bounces; non-terminal bounces still enter manual review.
- F-06: oracle and resolver handlers now reject after-deadline messages with `Errors.Deadline`; regressions assert the deal/NFT state does not advance.
- F-02, F-04 and F-05 remain open: full dispute/refund/expiry financial matrix, real-signature settlement integration fixtures and oracle trust/evidence review are not complete.
- CI evidence for these follow-up commits must be recorded separately from the historical run IDs above.
