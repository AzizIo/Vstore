# VILTARA TON Escrow — external audit and live acceptance handoff

**Prepared against current main:** `a08b3b7632e1e1d8c38ac7a896b519a595f32df8`  
**Network scope:** TON testnet only (`global_id = -3`)  
**Contract:** `contracts/ton-escrow-poc/contracts/DealEscrow.tolk`  
**Toolchain:** Acton 1.2.1 / Tolk 1.5.0  
**Status:** handoff package only; no independent audit or live testnet acceptance has occurred.

## 1. Do not treat this revision as release-approved

The contract-specific CI passed on commit `2ecf38943216a773dc27fb1841f11edc3ee67b9f` (run [43762485072](https://github.com/AzizIo/Vstore/actions/runs/43762485072)). Current main `a08b3b7632e1e1d8c38ac7a896b519a595f32df8` is one later preview-runtime-gating commit ahead; the compare contains no changes to contract sources, contract tests, ABI, frozen manifest or the contract workflow.

However, two coordinated remediation branches are still Draft:
- [PR #241 — proof-anchored allowlisted TEP-62 NFT identity](https://github.com/AzizIo/Vstore/pull/241). It adds same-masterchain-block item/collection account proofs and standard collection item-address derivation. It has not been merged/accepted. Its collection policy intentionally defaults to empty; no collection or code hash is approved by default.
- [PR #242 — preserve storage reserve on carry-all refund retry](https://github.com/AzizIo/Vstore/pull/242). It fixes the carry-all retry reserve-floor finding and adds a balance-floor assertion. Frozen code/BOC/StateInit values have been regenerated; strict exact-head Contract CI passed on head `9b6e79de2b35aa526dc517b13eebdf73898ba02d` (run [#43766977381](https://github.com/AzizIo/Vstore/actions/runs/43766977381)), including StateInit/message vectors, static checks and 30 Acton tests. It remains Draft pending adapter BOC pin coordination with #206.

**Audit recommendation:** do not start the final sign-off review against a moving branch. Review the exact post-remediation commit only after #241/#242 (or equivalent fixes) are integrated and all affected CI/artifact checks are green. The reviewer may inspect the open PRs now as pre-audit material.

## 2. Frozen contract artifact currently in main

Source-controlled frozen manifest: `contracts/ton-escrow-poc/artifacts/frozen/manifest.json`.

| Artifact | Current frozen value |
|---|---|
| Acton / Tolk | `1.2.1` / `1.5.0` |
| Compiled code hash | `1BCCBF586878F8032F4E860707B0102EC554B4E1C0CFD7DEA362E1DD391D6666` |
| Compiled BOC (base64) SHA-256 | `2ba55420e6b09c94986d51b045db92959df11f66b339cd77df4e919d30a0e50b` |
| Decoded BOC SHA-256 | `b4a46ef78089119fb10272e1edbd152f8b5e9c337b59d759ad5e1c661dd4fbb5` |
| Compact ABI SHA-256 | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| StateInit hash test vector | `ffd464daa07d4fd3b99e2469520eb77624f3265de9784d103df3babc15c5199f` |
| Raw address test vector | `0:ffd464daa07d4fd3b99e2469520eb77624f3265de9784d103df3babc15c5199f` |
| Initial data cell hash | `faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b` |
| Frozen build artifact | `14180230821` |
| Manifest source commit | `979ec32f07224726532fdf48b941eda8314f32b0` |

The deterministic raw address above is a **test vector**, not evidence that this contract is deployed. Any Tolk code change, including PR #242, changes the compiled code hash/BOC and must be rebuilt with the pinned toolchain. Do not hand-copy hashes or reuse this address after a code change.

## 3. Exact automated evidence presently available

Contract CI run [43762485072](https://github.com/AzizIo/Vstore/actions/runs/43762485072) completed successfully on contract commit `2ecf38943216a773dc27fb1841f11edc3ee67b9f`. The job passed:
- frozen verifier unit tests and ABI snapshot check;
- pinned Acton build and generated code/BOC comparison;
- ABI wrapper generation;
- StateInit/address/data-hash cross-check using generated Acton wrapper and `@ton/core`;
- ABI message BOC golden vectors;
- Tolk format check and static checks;
- 30 Acton emulator tests.

The 30 emulator tests currently cover deployment/activation, exact NFT deposit, buyer funding/acceptance, mainnet rejection, oracle/resolver signature quorum, timeout/late finality, delivery/return/payout/refund disputes, real mock NFT transfer bounce, seller payout bounce, seller allowance bounce, carry-all reserve refund bounce/retry, stale retry and terminal-state protection.

CI and emulator success are **not** an independent security review and do not prove live-chain finality, real collection identity, or live TON wallet behavior.

## 4. Independent reviewer scope

The reviewer must be independent of the implementation author, release operator, and all oracle/resolver signers. Require written confirmation of hands-on TON/Tolk (Tolk 1.5.0 / TVM) review experience before engagement.

### Contract and protocol
- Reconstruct TL-B layouts/opcodes from source and generated ABI.
- Rebuild StateInit independently from code and immutable constructor data; verify workchain, code/data hashes, deal salt, network separation and all message vectors.
- Review ConfigParam 19 signed global-ID check and mainnet rejection.
- Review all authorization checks, immutable roles/recipients, item sender checks, payload parsing, query IDs, attempt IDs, oracle/resolver cell hashes and 2-of-3 Ed25519 key-slot semantics.
- Review TEP-62 transfer/notification and exact item address pinning; identify all NFT-stranding conditions.

### Message execution, bounce and financial invariants
- Independently derive the RichBounce TL-B layout and pinned Tolk 1.5.0 parser assumptions.
- Review both descriptor slots and every path that can produce a primary plus secondary refund.
- For every outbound message, cover compute failure, action-phase failure, remote bounce, no-funds bounce, delayed/duplicate/out-of-order/mismatched bounce, missing bounce, recipient contract wallet and restart/replay.
- Recompute all principal, seller allowance, transfer, forward-fee, execution-reserve and terminal-storage amounts.
- Explicitly review `SEND_MODE_CARRY_ALL_BALANCE`, fee flags, reserve ordering, bounce and authorized retry. Confirm the terminal storage reserve cannot be consumed by a bounced carry-all refund retry (PR #242 is the current fix candidate).
- Prove principal is paid/refunded exactly once, NFT owner matches each accepted terminal result, terminal reserve survives, and a late/duplicate attestation cannot re-settle.

### Provider/finality boundary
- Verify the trust-level-0 LiteServer trust anchor and masterchain validator/config update chain independently.
- Prove shard-block inclusion into the masterchain, exact transaction inclusion, source/destination, message hash, trace relationship, action phase, code hash, account state and getter snapshot.
- Check that TonCenter/indexer discovery fields never authorize canonical state changes.
- Review bounce-to-original-outbound-transaction correlation and stale/incomplete transaction-history handling.
- Review NFT identity proof in PR #241 separately: item and collection state at the same trusted masterchain block; allowlisted collection/item code hashes; collection-stored item code; minted index bounds; independently reconstructed `get_nft_address_by_index(index)`; immutable policy evidence; owner revalidation. Empty allowlist must remain fail-closed.

### Required audit deliverable
- Reviewer identity, qualifications, engagement date and independence declaration.
- Exact reviewed commit SHA, source file hashes, ABI/code/BOC/StateInit hashes and pinned toolchain.
- Findings with severity, affected lines, preconditions, impact, exploit/reproducer and remediation.
- Re-run evidence for every fix and a final signed report tied to the exact post-remediation hashes.
- Explicit residual risk and written statement that CI/emulator tests are not live testnet acceptance.

## 5. Candidate external audit leads

These are **leads to request a scoped proposal**, not an endorsement, booking or confirmation that they accept Tolk 1.5.0 work:
- [Hacken — TON smart contract audit](https://hacken.io/services/blockchain-security/ton-smart-contract-audit/)
- [CertiK — TON ecosystem security](https://www.certik.com/ecosystems/ton)
- [Trail of Bits — TON blockchain assessment reference](https://docs.ton.org/audits/TON_Blockchain_ToB.pdf). This is a prior TON core/TVM assessment, not an audit of VILTARA; confirm current availability and Tolk-specific expertise.

The request for proposal must explicitly say `Tolk 1.5.0`, Acton `1.2.1`, TVM asynchronous message/bounce behavior, TEP-62 and the exact escrow/finality scope. Do not accept a generic EVM-only review as satisfying this gate. No source has been submitted to an external service and no audit engagement has been initiated.

## 6. Valueless TON testnet acceptance procedure

### Preconditions
- Independent audit has no unresolved critical/high findings.
- Final code/BOC/StateInit/ABI hashes are frozen and independently reproduced.
- A reviewed testnet collection policy is configured (exact collection address, collection code hash, item code hash and approved derivation). PR #241 introduces an empty-by-default allowlist and same-block proof-backed identity checks, but no real collection is approved yet; no policy/hash may be guessed.
- Disposable testnet wallets are provisioned separately for seller, buyer, oracle operators and resolver operators. Private keys remain with their owners/offline; never store them in GitHub, CI, backend, logs or this handoff.
- Oracle and resolver public keys are distinct, unique, and configured only after operators confirm key custody.
- Explicit owner authorization records the testnet deal terms, valueless NFT, tiny testnet TON amounts, operator roles and abort procedure.

### Required action trace
1. Deploy the exact frozen DealEscrow StateInit; verify address, code hash and immutable getters from a trusted masterchain checkpoint.
2. Activate; verify state/deadline.
3. Deposit the exact approved NFT item; verify TEP-62 notification sender, previous owner, query ID, salt, item index, collection, and actual owner.
4. Fund exact principal + reserve; verify account balance and getter state.
5. Accept and deliver; verify outbound NFT transfer transaction, message hash, trace, item owner, signed oracle attestation and getters.
6. Run pre-delivery and post-delivery dispute branches with both resolver outcomes, voluntary NFT return, seller payout and buyer refund.
7. Deliberately cause each allowed outbound failure/bounce against controlled test contracts/wallets; exercise unauthorized retry, authorized retry with new attempt/query ID, stale/duplicate bounce, out-of-order bounce, timeout before proof and late finality.
8. Reconcile each transaction/message/trace against the same or later trusted masterchain block and compare the complete contract getter/storage snapshot plus live NFT item owner/collection/index.
9. Reconcile principal, deployment allowance, execution reserve, fees and terminal storage floor before and after each branch.
10. Restart the observer between discovery, proof verification and persistence; replay the same candidate and prove idempotent monotonic reconciliation.

### Evidence record per transition
Capture the network/global ID, contract/item/collection/wallet addresses, source commit and code hash, StateInit hash, transaction hash, inbound/outbound message hashes, trace identifier, shard block ID, masterchain seqno/root hash, inclusion proof digest, transaction compute/action/bounce phases and exit codes, query/attempt/deal salt, attached and delivered value, fee breakdown, complete relevant getters, item owner and item/collection code/data hashes. Preserve raw proof material and reproducible verification commands; a provider JSON `finalized=true` field is not evidence by itself.

## 7. Current live-acceptance blockers

- No actual DealEscrow deployment address or live transaction/trace/getter evidence is recorded in the repository. The frozen StateInit address is only a deterministic vector (and the PR #242 StateInit address is a newer deterministic vector, still not a deployed address).
- No disposable testnet wallets, approved valueless NFT item/collection, or independently held oracle/resolver key operators are provisioned in this workstream.
- Current repository defaults keep oracle/resolver public-key lists empty and finality observer disabled. PR #241 adds a further empty-by-default collection policy. No operator public keys, collection allowlist entry, disposable wallets, live deal or transaction proof has been supplied.
- No live transaction will be signed or broadcast by this handoff. Live wallet actions require the approved disposable-wallet setup and explicit operator execution described above.

**Decision: BLOCKED.** This package enables a qualified external specialist and release operator to perform a bounded review and testnet acceptance; it does not substitute for either. Mainnet, production signing/broadcast, real TON funds, and real NFT transfers remain out of scope.
