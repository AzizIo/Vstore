# TON Escrow — contract security audit & lifecycle coverage (Issue #214)

**Review class:** internal, source-level, static/emulator-gap assessment.  
**Not an independent audit. Not a release approval.**  
**Review baseline:** `dd7e5045450f4c95e564fae72c4200f3d921d196`  
**Contract source:** `contracts/ton-escrow-poc/contracts/DealEscrow.tolk`  
**Frozen manifest:** `contracts/ton-escrow-poc/artifacts/frozen/manifest.json`  
**Protocol:** v1, TON testnet scope, Acton 1.2.1 / Tolk 1.5.0.

## Executive result

The inspected source contains meaningful fail-closed controls: fixed per-deal roles/item/amounts, signed ConfigParam 19 testnet check, 2-of-3 signatures over typed cell hashes, distinct oracle/resolver key sets, attempt/query binding, exact NFT sender/payload checks, and manual-review transitions for bounced internal actions.

This pass does **not** establish that the contract is safe to deploy. The emulator suite is materially narrower than the requested lifecycle matrix; bounce recovery loses action identity and can overwrite terminal state; oracle/resolver handlers do not enforce their state deadlines; and the reserve-accounting test bypasses signature checking for the terminal payout path. Core contract source blobs were compared between the manifest source commit and the current review baseline and found identical; exact-head rebuild and independent StateInit/BoC reproduction remain outstanding. No live testnet transactions or independent specialist review were performed. The branch adds three Acton emulator reproducers for late oracle attestation, late resolver decision and terminal-state overwrite after bounce; all 16 contract emulator tests passed in TON Contract CI run #132 (43649259704) on exact head `f38221a45fca937f67d7f2f45cf4b72bd102fd32`.

## Findings

### F-01 — MEDIUM: bounced message handler can overwrite a completed terminal state

**Location:** `DealEscrow.tolk:738-745`.

`onBouncedMessage(_in)` ignores the entire bounced message and unconditionally changes the current deal state to `STATE_MANUAL_REVIEW`. It does not inspect the original bounced body, sender/destination identity, operation opcode, query ID, deal salt or the current pending action/attempt. The critical practical case is a bounce of `sendSellerDeploymentRefund` sent during `settleRemainingBalanceForBuyer`: the principal may already have been paid and state set to `STATE_SETTLED` / `STATE_REFUNDED`, while the later refund bounce overwrites that terminal state.

**Preconditions / potential impact**
- Principal settlement has already been reconciled by the oracle and the contract has entered `STATE_SETTLED` or `STATE_REFUNDED`.
- `settleRemainingBalanceForBuyer` also sends the fixed seller deployment allowance in a separate bounce-enabled message.
- If the seller endpoint rejects that deployment-refund message, the resulting genuine TVM bounce is delivered after the terminal state was saved.
- The bounce callback overwrites the terminal state with `STATE_MANUAL_REVIEW` and clears the deadline. It does not reverse the principal transfer or set `principalLocked` back to true, but it destroys the explicit terminal-state signal for reconciliation and any consumer relying on getters.

**Evidence**
- The existing bounce test exercises a synthetic bounce and expects manual review (`DealEscrow.test.tolk:615-640`).
- The added `test bounced message can overwrite an already terminal state` seeds `STATE_SETTLED`, delivers a bounced settlement message and observes `STATE_MANUAL_REVIEW`. This proves the callback does not preserve terminal states. A full transaction-chain test with a seller contract rejecting the actual deployment-refund message remains to be added.
- `sendSellerDeploymentRefund` is bounce-enabled (`DealEscrow.tolk:179-195`) and is emitted during terminal settlement (`DealEscrow.tolk:223-235`); the handler does not discriminate message kind (`DealEscrow.tolk:738-745`).

**Reproducer**
- Added emulator test proves terminal-state overwrite by calling the bounced-message path after a seeded terminal state. The test is a callback-level synthetic bounce, not proof of arbitrary third-party bounce forgery or the full network action ordering.
- Follow-up integration test should deploy a rejecting seller contract and cause the contract-controlled deployment allowance refund to bounce after the principal payout/refund message.

**Recommendation**
Decode the bounced body and bind recovery to the expected outbound operation/pending state/attempt/query/salt and trusted destination. Define a safe policy for unrecognized bounces (ignore vs manual review with recorded evidence). This is protocol/behavior-sensitive and must be coordinated with the #206 adapter owner before editing. Do not patch ABI/storage here.

**Severity caveat:** MEDIUM is based on loss of terminal-state reporting after a genuine bounce of a contract-controlled, bounce-enabled refund. Exact transaction ordering and consumer impact still require an independent TON/Tolk reviewer.

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

### F-06 — MEDIUM: oracle and resolver attestations are not rejected after their state deadline

**Locations:** oracle path `DealEscrow.tolk:329-352`; resolver path `DealEscrow.tolk:456-472`; timeout path `DealEscrow.tolk:640-696`.

The contract checks deadlines for funding/acceptance, NFT deposit/return notifications and dispute opening, but `handleOracleAttestation` and `handleDisputeResolution` do not compare `blockchain.now()` with `progress.deadlineUnix`. The timeout path only moves the state forward when a separate `TimeoutDeal` message is processed.

**Preconditions**
- The deal is still in an oracle- or resolver-pending state.
- `deadlineUnix` has passed.
- No permissionless `TimeoutDeal` transaction has yet been included.
- A correctly signed attestation/decision for the current attempt is submitted after expiry.

**Potential impact**
The accepted outcome becomes a transaction-order race: a late oracle confirmation can advance a delivery/payout/refund path after its confirmation grace, or a late resolver decision can leave the arbitration window and still initiate NFT return/release. This weakens the documented rule that expired unresolved cases enter manual review. No loss of principal is proven from this condition alone; the impact is deadline-policy bypass and inconsistent handling of stale evidence.

**Reproducers added**
- `test expired oracle attestation is still accepted before timeout transaction` sets emulator time beyond the stored deadline and exercises the oracle handler.
- `test expired resolver decision is still accepted before timeout transaction` opens a real pre-delivery dispute, advances time beyond the arbitration deadline, then exercises the resolver handler.
- These tests deliberately bypass only the signature VM check with `testing.setChecksigIgnore(true)` to isolate the missing time check; they do not claim cryptographic acceptance. The signature helper tests remain separate.

**Recommendation**
Define whether the deadline constrains (a) the source-chain action timestamp, (b) the attestation submission time, or (c) only the time by which a permissionless timeout must be processed. If it constrains contract submission, add `blockchain.now() <= progress.deadlineUnix` before state mutation. If late proof of an in-deadline source transaction is permitted, include and validate an authenticated source timestamp/checkpoint in the signed oracle data rather than relying only on positive masterchain seqno/logical time. Coordinate semantics with #206/#213 before protocol or adapter changes.

### F-05 — MEDIUM: oracle attestation evidence hashes are only checked for non-zero and persisted

**Location:** `DealEscrow.tolk:334-339` and route checks in `313-443`.

The contract checks that message/trace/evidence hashes are non-zero and persists the supplied evidence hash. On-chain code cannot itself prove external indexer finality or trace membership unless that evidence is independently interpreted by the oracle quorum. Therefore security rests on the actual 2-of-3 oracle governance and evidence validation procedure. This must be independently reviewed; signature quorum alone does not make the underlying observation true.

**Impact**
Compromise, collusion or correlated failure of two oracle operators can attest a false transfer/settlement observation. This is an explicit trust assumption but must not be described as trustless/finality proven.

**Recommendation**
Independent reviewer to inspect signed payload format, source evidence verification rules, operator independence and key custody. Add hostile oracle fixtures (valid signatures over wrong but internally consistent traces, conflicting observations, wrong masterchain checkpoint, false destination/amount/query). The contract only constrains fields; oracle policy validates evidence semantics.

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
| Build, format, ABI generation | TON Contract CI #132 passed build, frozen digest compare, ABI snapshot, wrapper generation, format and static checks | Passed for exact reviewed head |
| Exact testnet ConfigParam 19 gate | mainnet global ID fixture | Partial |
| Exact NFT item deposit | happy path + wrong-item behavior in existing plan | Partial |
| Buyer funding and acceptance | happy path | Partial |
| Signature helper quorum | 3/3, 2/3, 1/3, duplicate slot helper | Partial; not end-to-end |
| Full pre/post delivery dispute | no complete emulator traces | Missing |
| Buyer principal refund | no full real-signature path | Missing |
| Seller expiry/return | not fully exercised | Missing |
| Every outbound bounce branch | generic bounce + terminal-state overwrite reproducer (CI passed); full real NFT/principal/refund bounce matrix absent | Partial |
| Deadline boundaries | late oracle/resolver reproducers (CI passed); -1/exact/+1 boundary matrix still incomplete | Partial |
| Terminal principal/NFT/reserve invariants across branches | one seeded seller payout/reserve case | Missing |
| Replay and stale attempt | stale oracle check only | Partial |
| Live valueless testnet lifecycle | none attached | Blocked |
| Independent TON/Tolk audit | none attached | Blocked |

## Frozen artifact provenance recorded for this review

- Current source review SHA: `dd7e5045450f4c95e564fae72c4200f3d921d196`
- Manifest source commit: `2913ea7d53ea7344f57d6503142c08e0b328bc7d`
- Workflow run ID: `43634396094`
- Artifact ID: `14129775225`
- Original archive SHA-256: `80db85f1dfc91450e6e7e47990bd89bf2ff80e0ecb99d17d8f40a07f33feba58`
- Original ABI SHA-256: `05d3bc9b7aafc7fc71889cffc6d4fea2f607ea14aa48f3854c8e432747623597`
- Build descriptor SHA-256: `f38b6c867af8ed13d95bc7fed75136961eb97c21290360197ccf9520907ffc3b`
- Compiled code hash: `E9358DAA6FFCC8FCEC979FBD631C7FC0BE336347D1DD44F3F06113E7B2A37548`
- Compiled BoC SHA-256: `aaaa3822a52e28410589cbd11e7e81252ea8d52b07ece73a9b5dda1c07d8a167`
- Compact ABI SHA-256: `25fc5f338f45db7d7198961a75c1d5cfe04f996ae36013cca0d70f03870c3923`
- Acton 1.2.1 / Tolk 1.5.0

These are copied from the frozen manifest; this pass did not independently download/rebuild the original artifact to verify its SHA values.

## Independent reviewer status

**NOT PERFORMED.** No reviewer identity/qualifications, signed report, engagement record or independent finding disposition is available. This internal review cannot be represented as external audit.

## Live testnet status

**BLOCKED — owner approval required.** No transactions, deployment, wallet connection, real funds or testnet NFT transfers were performed for this pass.

## Decision

**BLOCKED for testnet acceptance / any production use.** The contract may only proceed as an isolated disabled testnet PoC under the existing Gate A controls. Do not enable signing, mount public routes, claim buyer protection, or merge as proof of live acceptance. Resolve or explicitly disposition the above findings, complete missing emulator matrix, rebuild/bind the frozen artifact to an exact source SHA, and obtain independent TON/Tolk review before Gate B.
