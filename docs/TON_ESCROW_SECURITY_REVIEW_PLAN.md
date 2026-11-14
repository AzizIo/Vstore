# TON Escrow — independent security review plan

**Status:** independent review has not yet been performed. This document defines the review programme; it is not an audit report or approval.

**Review baseline:** before a reviewer starts, record the exact commit SHA, generated ABI, compiled BoC/code hash, toolchain version and CI artifact digest. Review a frozen revision, never a moving branch.

## Components in scope

- contracts/ton-escrow-poc/contracts/DealEscrow.tolk — immutable per-deal escrow state machine.
- contracts/ton-escrow-poc/contracts/types.tolk — v1 storage layouts, opcodes, TEP-62, oracle and resolver message TL-B.
- contracts/ton-escrow-poc/contracts/signatures.tolk — Ed25519 verification and 2-of-3 threshold.
- contracts/ton-escrow-poc/contracts/TestNftItem.tolk — test fixture only; never a production NFT item or collection.
- Generated Acton ABI, wrappers, StateInit and BoC artifacts from the frozen commit.
- Backend escrow observer/domain/provider boundary only where it consumes chain evidence. The HTTP adapter/provider still fail closed and are not approved for live use.

## Reviewer independence and required output

The reviewer must be an experienced TON/Tolk smart-contract security specialist who did not author this implementation and is not one of the configured deal oracle/resolver operators.

Record the reviewer identity and qualifications, engagement date, reviewed commit SHA, artifact SHA-256, compiler/toolchain versions, generated ABI, code hash, written findings with severity and reproducible proofs, and a signed final report or equivalent verifiable review record.

A code-owner approval, green CI, internal checklist or this plan is not an independent audit.

## Review programme

### 1. Protocol, StateInit and deployment

- Reconstruct all TL-B schemas and opcodes from generated ABI; compare with documented wallet messages.
- Independently calculate StateInit/address from code plus immutable initial data. Verify workchain, code hash, storage hash, deal salt and network domain separation.
- Confirm seller, buyer, exact NFT item, collection metadata, principal, deployment allowance, execution reserve and authority keys cannot change after deployment.
- Confirm ConfigParam 19 is parsed as signed 32-bit global_id; verify testnet -3 acceptance and mainnet -239 rejection.
- Confirm there is no upgrade, admin withdrawal, arbitrary recipient, unbounded loop or private-key capability.

### 2. NFT custody and TEP-62

- Validate transfer opcode 0x5fcc3d14 and ownership_assigned opcode 0x05138d91, payload selector, magic, salt, query ID and item-sender binding.
- Test wrong item, wrong old owner, wrong query ID, malformed inline payload, referenced payload, duplicate notification, unsolicited notification and an item that rejects transfer.
- Confirm post-delivery buyer disputes require voluntary return of the exact item; the contract cannot seize an NFT from a buyer wallet.
- Validate item-return and unexpected-item recovery. Identify NFTs that could be stranded and keep the user warning explicit.

### 3. Amounts, refunds and transaction modes

- Recompute every nanotons amount: principal, seller deployment allowance, execution reserve, NFT transfer value, forward amount, network fees and terminal storage floor.
- Prove buyer funding requires exactly principal plus execution reserve and cannot exceed fixed principal.
- Reproduce seller payout, buyer principal refund, seller deployment allowance refund and unused buyer reserve refund, including fees and carry-all-balance action ordering.
- Verify reserve semantics and SEND_MODE combinations under action failure, insufficient balance, bounce and no-bounce recipient cases.
- Prove no path pays principal twice, spends more than funded reserve, withdraws terminal storage funds or reports settlement before the relevant source transaction is final.
- Review funds sent to a wallet address that is not yet deployed, and any value left following a bounce.

### 4. Oracle and resolver cryptography

- Independently reproduce the signed cell representation hash and Ed25519 preimage/byte order.
- Verify signatures from A/B/C are checked only against their respective unique public keys; copied signatures cannot count twice.
- Verify oracle and resolver keys are unique and pairwise disjoint in every deployable configuration.
- Verify 2-of-3 acceptance, 1-of-3 rejection, invalid signature rejection, wrong key, altered field, wrong network, wrong contract, wrong deal salt, wrong attempt, wrong query ID and replay after a state change.
- Review private-key generation, custody, rotation, loss recovery and operator independence. No private keys may be stored in this repository or application backend.

### 5. State machine, timeout and disputes

- Prove transitions for seller deposit, buyer funding/acceptance, delivery, pre-delivery dispute, post-delivery dispute, voluntary NFT return, both resolver outcomes, expiry, payout, refund and manual review.
- Test deadline boundaries at deadline minus one, deadline, and deadline plus one.
- Test duplicate, replayed and out-of-order oracle/resolver attestations.
- Test bounces on every outbound NFT and TON action; ambiguous outcomes must fail closed into manual review/reconciliation.
- Test terminal-state re-entry, timeout/acceptance/dispute races and concurrent messages.

### 6. Provider, finality and operations

- Review the testnet provider against an explicit finality policy; validate transaction/message/trace identity, query ID, attempt ID, logical time, masterchain sequence number, code hash and getter reconciliation.
- Test delayed indexing, provider outage, conflicting trace, shallow reorg, expired observer lease, replay and non-final-to-final promotion.
- Raw observations and user-supplied transaction hashes must never advance canonical state without contract-accepted, finalized evidence.
- Review pause, incident, manual-review and reconciliation runbooks.

## Current automated evidence — not an audit

The Acton CI workflow currently covers BoC build, generated ABI/wrappers, formatting and static checks; deterministic StateInit address; seller activation and participant checks; exact TEP-62 deposit and wrong-item rejection; exact buyer funding and buyer acceptance; raw NFT transfer not settling the deal; mainnet global-ID rejection; stale oracle attempt rejection; seller payout with seller deployment allowance and unused reserve returned to buyer; real Ed25519 2-of-3 helper tests (3/3, 2/3, 1/3 and duplicate-slot cases); and bounced internal message entering manual review.

The emulator suite does not prove live TON testnet deployment, real Tonkeeper/TON Connect transaction traces, independent key operators, every post-delivery dispute/refund/expiry path, provider reorg/finality behaviour or an external audit. The emulator-only checksig-ignore setting is scoped to one reserve-accounting unit test and must never appear in deployable code or a live provider.

## Release gates

### Gate A — merge isolated PoC source

- Exact-head Backend, Frontend/API E2E and TON Contract CI are green.
- Backend router remains unmounted; adapter/provider remain fail-closed; frontend signing and checkout remain disabled.
- PR and docs clearly describe isolated testnet PoC, not production custody or buyer protection.

### Gate B — valueless TON testnet acceptance

- Independent review has no unresolved critical/high findings.
- Independent test-only oracle and resolver operators provision distinct keys outside the backend.
- Exact reviewed BoC/code hash and StateInit are verified at a testnet deployment.
- Tonkeeper/TON Connect matrix covers happy path, wrong NFT, timeout, bounce, dispute, payout/refund and reserve accounting.
- Finalized provider evidence and getters are recorded for each tested action.

### Gate C — any public purchase or production consideration

- Written Telegram platform ruling and qualified legal/compliance review for the precise NFT resale/payment UX are recorded.
- Custody/refund/chargeback/dispute model, accounting, operator procedures and production audit are independently approved.
- Atomic listing reservation is integrated with the existing Orders lifecycle and covered by API-backed E2E.
- Only a separate reviewed PR may mount a route or enable a user-facing action. Mainnet and live checkout are out of scope for this PoC.

**Current decision:** Gate A may be considered for merging as disabled, isolated testnet-only source after exact-head CI. Gates B and C remain closed until the external evidence above exists.
