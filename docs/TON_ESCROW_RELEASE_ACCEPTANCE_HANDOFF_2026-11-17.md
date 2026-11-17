# VILTARA TON Escrow — external audit and testnet acceptance handoff

**Snapshot date:** 2026-11-17  
**Repository:** `AzizIo/Vstore`  
**Immutable source baseline:** `4e1308426591f1f023d6827d8744827efe4ce9f9`  
**Network scope:** TON testnet only (`global_id = -3`)  
**Protocol:** DealEscrow v1  
**Toolchain:** Acton 1.2.1 / Tolk 1.5.0  
**Decision:** BLOCKED — this is a reviewer/operator handoff, not an audit report, deployment authorization or release approval.

The smart-contract review baseline is the exact main commit above. PR #257 is a separate frontend direct-StateInit integration and remains Draft until its exact-head frontend, backend and contract checks all pass. Do not silently move the auditor's baseline to a later commit. Any source, ABI, code BOC, compiler, StateInit or protocol change requires a new baseline and hash manifest.

## 1. What has and has not been independently verified

The repository contains automated Acton emulator tests, strict frozen-artifact checks, generated ABI/wrapper checks, StateInit and message-vector cross-checks, backend proof/finality tests, and frontend/API-backed tests. Those are internal engineering evidence only.

**No independent TON/Tolk audit has been completed. No live testnet deployment or full live testnet deal lifecycle has been accepted.** A green CI run, code-owner review, this handoff or an internal audit must not be described as an independent audit.

The current repository deliberately fails closed:
- DealEscrow is testnet-only; the contract checks the stored network ID and ConfigParam 19 global ID.
- The backend returns unsigned TON Connect requests only. It does not sign, broadcast or custody user keys.
- The NFT collection policy allowlist is empty by default. An operator must review and approve the exact collection/item code policy before the relevant path can progress.
- Paid checkout, production escrow, mainnet and real-value NFT transfers are not authorized.

## 2. Frozen smart-contract review identity

Review exactly these source files from the immutable baseline:

| File | Git blob SHA at baseline |
|---|---|
| `contracts/ton-escrow-poc/contracts/DealEscrow.tolk` | `a18506283417bad02e562a69080f4b1b177708f5` |
| `contracts/ton-escrow-poc/contracts/types.tolk` | `d410ec5cca348cffab1c766cd38fb7a3174deb9d` |
| `contracts/ton-escrow-poc/contracts/signatures.tolk` | `67453fc0789efa403e366b33998ee82323413465` |
| `contracts/ton-escrow-poc/tests/DealEscrow.test.tolk` | `98ed0fcda81b32eca5d4dad50d4990f9a44bd557` |
| `contracts/ton-escrow-poc/artifacts/frozen/manifest.json` | `ff006c4450c53534a8610666ea72fdd393a2a4c2` |

Frozen manifest values:

| Artifact | Expected value |
|---|---|
| Contract/protocol | DealEscrow / v1 |
| Network | TON testnet only |
| Manifest source commit | `9d80a65a974b54f115fc697158974bdcee2c6be8` |
| Acton / Tolk | `1.2.1` / `1.5.0` |
| Compiled code hash | `498A82F9B2DE206BE42108B6413D517CE63D4BCB1C20704D0BD89FCCC9509C46` |
| Compiled code BOC SHA-256 | `86ed08596d0595c711aa2cf7659ee396ff443d7b01c65659b8e7543dd23c6173` |
| Compressed BOC SHA-256 | `8dce117db9f0ca883b0438c2f600b10c4caf18d7febd3db26a02d78c0191cbd7` |
| Compact ABI SHA-256 | `df3b2ec393b2d1ed0f74474f630c81be8868b8421d2c7e429747cc2a4a336028` |
| Fixed-vector StateInit hash | `4e3845e9d0b4df2f603b0ba7cceca4592276d25d8f43d2c611376344db393f75` |
| Fixed-vector data-cell hash | `faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b` |

**Important:** the fixed-vector StateInit hash/raw address in the manifest is a deterministic fixture for one fixed set of terms. It is not a pre-deployed production or shared deal address. Every deal must derive its own address from that deal's exact immutable terms.

The manifest's embedded historical source commit and workflow/artifact identifiers are provenance fields. The reviewer must independently rebuild the exact reviewed source baseline with the pinned toolchain, compare generated ABI/code BOC/StateInit and message vectors, and record the current CI artifact and archive digest. Do not edit frozen hashes merely to silence a mismatch.

## 3. Independent auditor requirements

The reviewer must be an experienced TON/Tolk smart-contract security specialist who:
- did not author this implementation;
- is not one of the deal's configured oracle or resolver signers;
- independently reproduces StateInit/address and signed-cell hashing;
- receives only the frozen source and public artifact package, never private keys.

Required report:
1. Reviewer identity, qualifications, scope, date, exact commit and all artifact/toolchain hashes.
2. Threat model, trust assumptions, attack surfaces and deployment configuration.
3. Findings classified Critical/High/Medium/Low/Informational with file/line references, exploit preconditions, impact and reproducible tests.
4. Independent reproduction of StateInit/address, ABI message layouts, TEP-62 transfer payload and Ed25519 2-of-3 oracle/resolver preimages.
5. Analysis of all outbound message action modes, bounce envelope correlation, retries, principal/reserve accounting, storage floor, terminal states and replay/order races.
6. Analysis of every timeout/dispute/expiry/refund/payout branch, including exact deadline boundaries and NFT ownership invariants.
7. Provider/finality/getter/oracle trust-boundary review and operational failure/recovery guidance.
8. Explicit residual risks and a signed report or other verifiable final review record.

Gate: no unresolved Critical or High findings. Any source/storage/ABI/opcode correction invalidates the reviewed source hash and requires a new exact-head review of affected components.

Reference review programme: `docs/TON_ESCROW_SECURITY_REVIEW_PLAN.md`. Existing internal review: `docs/TON_ESCROW_CONTRACT_SECURITY_AUDIT_2026-11-15.md`; it is not an independent audit.

## 4. Valueless TON testnet acceptance plan

### 4.1 Preconditions — do not start the live run until each is recorded

- Independent audit completed on the exact frozen code/artifact hashes with no unresolved Critical/High findings.
- Operator reviewed the exact standard TEP-62 collection and item code hashes and explicitly approved a narrowly scoped testnet collection policy. Keep the allowlist empty until then.
- Use a disposable test collection/NFT with no economic value and separate disposable buyer/seller testnet wallets. Record wallet ownership proof and intended operator.
- Provision three distinct oracle test signers and three distinct resolver test signers. Oracle and resolver key sets must be pairwise disjoint. Each signer keeps its private key outside VILTARA, CI, repository, logs and backend; only public keys are committed to the immutable deal terms.
- Confirm TON testnet global ID `-3`, testnet-only Mini App/runtime configuration, and that mainnet, production checkout, automated signing and broadcast are disabled.
- Prepare an operator-run log with UTC timestamps, immutable deal terms, code/StateInit hashes, wallet addresses, transaction/message/trace identifiers, provider identity, masterchain anchors, getter snapshots and balance measurements.
- Do not use a valuable user's NFT or real-value TON. Testnet TON and test NFTs only.

### 4.2 Positive lifecycle

1. Generate immutable deal terms and independently derive the per-deal StateInit/address from the pinned code and exact storage. Have two operators compare the values before any deployment.
2. Seller deploys the exact StateInit through TON Connect on testnet. Verify the deployed account code hash, address and initial getters against the reviewed artifact and terms.
3. Seller activates the deal. Verify participant authorization, testnet domain and the 30-minute deposit window.
4. Seller transfers the exact snapshotted NFT item to escrow using TEP-62. Verify item sender, previous owner, destination, query ID, deal salt and inline payload; confirm the item owner at a trusted finalized chain position.
5. Buyer funds the exact principal plus execution reserve. Verify the exact amount, query ID and buyer identity. Confirm that a submission hash alone does not mark the deal funded.
6. Buyer accepts under the required state/deadline rules. Verify the exact contract state/getter transition.
7. Execute the outbound NFT release to the snapshotted buyer. Verify the contract-generated message, actual item owner, transaction trace, masterchain finality and accepted 2-of-3 oracle evidence.
8. Complete the post-delivery dispute window using a controlled test schedule. Verify seller payout, fixed seller deployment allowance and unused buyer reserve treatment; prove principal is paid exactly once and terminal storage reserve remains above its required floor.
9. Record all final getters, item ownership, TON balances, trace evidence and proof anchors. A reviewer independent of the operator compares the evidence with the contract's immutable terms.

### 4.3 Negative and recovery matrix

At minimum, exercise the following with test fixtures and valueless testnet assets:

- Wrong network/global ID, wrong contract code, wrong deal address and mismatched StateInit.
- Wrong NFT item, collection/item identity mismatch, wrong previous owner, wrong destination, malformed/non-inline payload, wrong salt/query ID, duplicate notification and transfer rejection.
- Wrong buyer/seller, unverified or changed wallet, wrong recipient, unauthorized action and stale/replayed idempotency key.
- Funding below/above the exact principal-plus-reserve amount; duplicate funding; acceptance/dispute/timeout at deadline -1, exact deadline and deadline +1.
- Oracle/resolver signatures 0-of-3, 1-of-3, 2-of-3, copied/duplicate signer slots, wrong signer set, changed signed field, wrong network/deal/attempt, stale or out-of-order decision.
- Actual bounced NFT release/return, seller payout, buyer refund, seller deployment allowance refund and execution-reserve refund. Correlate RichBounce against exact outbound descriptor, destination, original body/value, query ID, attempt and deal salt.
- Retry by the wrong wallet, retry before it is ready, replay of an old query ID, duplicate retry, and a successful authorized retry with a new attempt/query ID.
- Provider outage, delayed indexer, non-final observation, conflicting trace, cursor replay, stale observer lease and getter mismatch. None may advance canonical state optimistically.
- Dispute buyer outcome and seller outcome, NFT return, pre-funding expiry, post-delivery dispute, payout/refund reconciliation timeout and manual-review recovery.

For each scenario assert all applicable invariants: exact NFT owner, exact principal paid once or refunded once (never both), no arbitrary recipient, no reuse of stale attempt/query IDs, unused reserve accounting, seller allowance accounting, and terminal storage floor. Ambiguous results must remain pending/manual review until independently reconciled.

### 4.4 Evidence and acceptance record

Attach a machine-readable index plus raw references for:
- deployed account address, code hash, StateInit/data hashes and immutable deal terms;
- every relevant transaction, message and full trace hash;
- trusted masterchain block/sequence/hash and provider identity for each finalized observation;
- before/after contract getter snapshots;
- current NFT item/collection identity and owner proofs from the same trusted chain anchor;
- before/after TON balances and reserve-floor calculations;
- oracle/resolver signatures and public-key identifiers (never private keys);
- all negative/replay/bounce/retry test results and operator sign-offs.

Do not call an event finalized because a wallet displayed “sent”, an indexer displayed a transfer, or a user supplied a transaction hash. Acceptance requires authoritative provider evidence, finality policy and getter/ownership reconciliation.

## 5. Telegram policy clarification — exact product questions

### Current product vs proposed future flow

**Current flow:** a third-party Telegram Mini App lists an already-existing TON TEP-62 NFT. Seller and buyer are separate Telegram users and control their own TON wallets. VILTARA coordinates the listing/reservation and independently verifies the seller-signed NFT transfer to the buyer. VILTARA does not currently collect the purchase price or custody the NFT.

**Proposed future flow:** VILTARA may introduce a TON wallet-to-wallet consideration/payment and/or a per-deal TON escrow/conditional-delivery flow. That proposed purchase flow is not enabled. We are not claiming that TON Connect, P2P terminology or direct wallet ownership creates a policy exemption.

### Questions to send to Telegram

1. Does a third-party Telegram Mini App that lists an existing TON NFT and coordinates a wallet-to-wallet secondary sale between two users fall within Bot Developer Terms §6.2 as a transaction pertaining to digital goods/services?
2. If it does, must the purchase consideration be paid exclusively in Telegram Stars even where the NFT is an already-existing asset, the seller and buyer are independent users, and the NFT transfer is signed directly from the seller's TON wallet?
3. Is there a distinction between (a) a Mini App that only lists NFTs and coordinates a seller-signed transfer without handling any purchase payment, and (b) a Mini App that coordinates or prompts direct TON wallet-to-wallet consideration? Which buttons, descriptions, purchase CTAs or external links are permitted in each case?
4. Is any external website/checkout or TON wallet-payment flow permitted to be linked or promoted from this Mini App for this exact resale model, or would that be treated as an attempt to route a covered in-Telegram sale outside Stars?
5. Section 6.2.1 warns against real-time sales of valuable virtual items that cannot be reclaimed after a successful dispute/chargeback. Does Telegram consider an irreversible TON NFT transfer compatible with the TPA dispute/refund obligations? Is any approved escrow, conditional-delivery, compensation or dispute pattern available for this model?
6. Which written policy, product or legal team can provide a product-specific decision, and what exact additional architecture, UX screenshots or flow diagrams are required for assessment?

### English message template

> **Subject: Policy clarification request — peer-to-peer secondary TON NFT sales in a Telegram Mini App**
>
> Hello Telegram team,
>
> We operate VILTARA SHOP, a third-party Telegram Mini App. We would like written clarification before enabling any purchase or payment flow.
>
> Our current experience lists already-existing TON TEP-62 NFTs. A seller and a buyer are separate Telegram users, each controlling their own TON wallet. VILTARA coordinates the listing/reservation and independently verifies the seller-signed NFT transfer to the buyer. VILTARA currently does not collect the purchase price or custody NFTs.
>
> We are considering a future optional flow in which consideration may be transferred directly between the users' TON wallets and/or coordinated through a per-deal TON escrow. This flow is not enabled.
>
> Could you please clarify:
> 1. Whether this exact user-to-user secondary sale is a transaction pertaining to digital goods/services under Bot Developer Terms §6.2.
> 2. Whether Stars are mandatory if the NFT already exists and both parties control their own wallets.
> 3. Whether a listing/transfer-coordination-only Mini App with no payment is treated differently from one that coordinates or prompts TON consideration.
> 4. Whether any external checkout link or direct TON wallet-payment prompt is permitted for this model.
> 5. How §6.2.1's dispute/chargeback guidance applies to an irreversible NFT transfer, and whether Telegram has an approved escrow or conditional-delivery pattern.
>
> We can provide architecture diagrams, UX screenshots, a step-by-step transaction sequence and a test-only demonstration. Please route this to the appropriate policy/product/legal team and, if possible, provide a written answer tied to the described flow.
>
> We will keep all paid checkout and escrow purchase flows disabled until the applicable policy requirements are clear.
>
> Thank you.

Submit the question to Telegram's official [@BotSupport](https://t.me/BotSupport) developer-support account, which Telegram identifies as support for Mini App and bot developers, and explicitly ask for routing to the relevant policy/product/legal team. This is a support contact path, not a promise of a formal policy ruling: a support reply is not automatically a legal opinion or guaranteed platform approval. Preserve the complete response, date, sender/team and any conditions in Issue #155. No Telegram request has been sent from this repository or on the user's behalf, and no written Telegram ruling is currently recorded.

## 6. Relevant first-party policy sources

- [Telegram Bot Developer Terms — §6.2 Digital Goods and Services](https://telegram.org/tos/bot-developers#6-2-digital-goods-and-services)
- [Telegram Bot Developer Terms — §6.2.1 Payment Disputes](https://telegram.org/tos/bot-developers#6-2-1-payment-disputes-for-digital-goods-and-services)
- [Telegram Bot Developer Terms — §7 Blockchain Integration](https://telegram.org/tos/bot-developers#7-blockchain-integration)
- [Telegram Stars Payments API](https://core.telegram.org/bots/payments-stars)
- [Telegram Blockchain Guidelines](https://core.telegram.org/bots/blockchain-guidelines)

Public policy text currently establishes that covered digital goods/services transactions inside a TPA must use Stars, and §6.2.1 raises a material issue for irreversible valuable virtual items. TON/TON Connect blockchain support does not itself create an exception to those payment rules. Public documentation does not expressly classify this exact P2P secondary sale of an existing TON NFT; that product-specific question remains open.

## 7. Release decision and gates

**Decision remains BLOCKED.** Do not enable paid checkout, escrow deposits, external purchase CTAs, mainnet, production signing, server-side signing, custody or real-value asset transfers until all gates below are documented and approved:

- [ ] Independent TON/Tolk audit on the exact frozen source and artifact hashes; no unresolved Critical/High findings.
- [ ] Exact collection/item testnet policy reviewed and approved; empty default allowlist preserved until approval.
- [ ] Disposable test wallets, valueless test NFT, and independently operated 2-of-3 oracle and resolver sets provisioned.
- [ ] Full live testnet lifecycle accepted with trusted finality, traces, getters, owner proofs and balance/storage-floor evidence.
- [ ] Telegram's written product-specific policy response received and assessed by qualified legal/compliance counsel.
- [ ] Relevant implementation, frontend, backend and contract CI green on one exact release candidate SHA.
- [ ] Release owner explicitly signs off on the exact artifact and operational controls.

Passing automated tests is not an independent audit, live testnet acceptance or launch authorization.


## 8. Independent auditor shortlist — procurement leads, not endorsements

The following firms publicly advertise TON smart-contract security work. Their public pages do **not** prove that a specific assigned reviewer has hands-on Acton 1.2.1 / Tolk 1.5.0 experience. Before sharing the frozen package or selecting a vendor, require a named reviewer, verifiable TON/Tolk references, conflict-of-interest confirmation and written scope.

1. **Cecuro — Tolk-specific TON review claim.** Its TON audit page explicitly lists Tolk, FunC and Tact coverage and calls out TON-specific async message, bounce, gas/storage and replay risks. The page is branded around agentic audits, so this is only a technical-fit lead, not evidence of a fully human independent audit. Ask for a named human reviewer, manual line-by-line scope, independently reproducible PoCs and client references before considering it. [TON audit page](https://cecuro.ai/ecosystems/ton).
2. **CertiK — TON ecosystem audit.** CertiK publicly advertises TON contract audits and describes source submission, scoping, security analysis, remediation and final report delivery. It also published a Tolk-specific security analysis in September 2026. Ask for the CV of the actual Tolk reviewer and a manual review commitment; AI tooling or an ecosystem listing alone is not independent audit evidence. Request scoping through the [official CertiK TON ecosystem page](https://www.certik.com/ecosystems/ton).
3. **Hacken — TON Smart Contract Audit.** Its dedicated TON audit page describes TVM-focused reviewers, line-by-line code review, static/dynamic analysis, fuzzing, attack simulation, gas optimization and remediation follow-up. Its public page also refers to experience with TON and FunC, so require explicit confirmation that the assigned team will manually audit this Tolk v1 / Acton project (not translate it to a generic EVM review). Request a quote through the [official Hacken TON audit page](https://hacken.io/services/blockchain-security/ton-smart-contract-audit/).
4. **TierZero.dev — specialist alternative to screen.** Its public audit page shows TON contract work, including a Tact multisig audit and a TON Jetton design review, and states that its reviews include manual line-by-line work and reproducible proof-of-concepts. No public evidence reviewed here establishes Acton/Tolk delivery; include only if it can name a reviewer with Tolk/TVM bounce and async-message experience. [Public audit record](https://www.tierzero.dev/audits).

### Mandatory vendor-screening questions

- Who, by name, will manually review `DealEscrow.tolk` and the generated Acton/ABI artifacts? How many production Tolk/Acton audits have they personally completed?
- Can they independently reproduce the fixed StateInit/address and message BOC vectors using Acton 1.2.1 / Tolk 1.5.0 and an independent TON SDK?
- Can they review RichBounce envelope semantics, action-phase failures, message ordering, retry descriptors, TEP-62 custody, cell serialization, 2-of-3 Ed25519 attestations and TON balance/storage-floor invariants?
- Will they inspect the backend finality/observer proof boundary as a separate scope item, or only the on-chain contract?
- Will the report bind every finding and final sign-off to the exact source commit and artifact hashes and include reproducible PoCs?
- Will the assigned reviewers disclose conflicts and confirm they did not author this code or operate the deal oracle/resolver keys?
- What are the fixed scope, deliverables, quote, timeline, retest allowance, and conditions for public disclosure of the final report?

**Procurement status:** shortlist prepared only. No company has been contacted, engaged, paid or authorized to receive private project information. No quote, reviewer assignment or audit slot has been confirmed. Select only after written confirmation of Tolk capability and scope.
