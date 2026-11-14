# TON Escrow — testnet acceptance runbook

**Status: NOT APPROVED FOR DEPLOYMENT.** This runbook is an operator checklist and evidence format, not proof that any on-chain test has run. It must not be used to enable signing, custody, paid checkout, or mainnet operations.

## Safety boundary

- Use TON testnet only (global ID `-3`) and disposable, valueless test NFTs from the repository's `TestNftItem` fixture.
- Use independent test-only oracle and resolver operators. Their private keys must remain outside this repository, backend, CI variables, logs, and this runbook.
- Do not use mainnet wallets, keys, assets, endpoints, addresses, or funds.
- Keep TON Connect signing disabled until an independent TON/Tolk security review has been completed against the exact code, ABI, compiler output and BoC hash.
- A transaction hash, submitted BOC, indexer row, wallet UI status, or unfinalized trace is not settlement evidence.
- Never manually advance a deal state to make a test pass.

## Frozen artifact baseline

The contract CI artifact for PR #193 was produced from commit `2913ea7d53ea7344f57d6503142c08e0b328bc7d`:

| Item | Value |
|---|---|
| Contract | `DealEscrow` v1.0.0 |
| Compiler | Acton 1.2.1 / Tolk 1.5.0 |
| TON network | Testnet, global ID `-3` |
| Contract code hash | `E9358DAA6FFCC8FCEC979FBD631C7FC0BE336347D1DD44F3F06113E7B2A37548` |
| ABI SHA-256 | `05d3bc9b7aafc7fc71889cffc6d4fea2f607ea14aa48f3854c8e432747623597` |
| Build JSON SHA-256 | `f38b6c867af8ed13d95bc7fed75136961eb97c21290360197ccf9520907ffc3b` |
| CI workflow run | [43634396094](https://github.com/AzizIo/Vstore/actions/runs/43634396094) |
| Artifact | [ton-escrow-acton-artifacts.zip](https://github.com/AzizIo/Vstore/actions/runs/43634396094/artifacts/14129775225) |
| Artifact SHA-256 | `80db85f1dfc91450e6e7e47990bd89bf2ff80e0ecb99d17d8f40a07f33feba58` |

The artifact expires on 2027-02-12. Before review or deployment, download it, verify the archive digest, extract it, and independently verify the ABI and build JSON digests above. Do not rebuild and silently substitute different artifacts. A rebuild is a new baseline and requires a new digest and review.

## Pre-deployment gates

All gates below are mandatory. Any failed or missing gate means STOP.

1. Freeze the exact source commit, generated ABI, compiled BoC, code hash, toolchain versions and artifact digests.
2. Have an independent TON/Tolk specialist (not an author or oracle/resolver operator) review the frozen baseline and publish a signed report. No unresolved critical/high findings.
3. Independently reconstruct StateInit and the address from the exact code cell and immutable data; compare workchain, code hash and full address with two independent implementations.
4. Provision distinct test-only oracle and resolver key sets. Confirm all six public keys are nonzero, pairwise distinct, and the corresponding private keys are not held by the backend.
5. Confirm the testnet-only deployment wallet is a disposable wallet with a capped faucet-funded balance. Check the network global ID before every deployment and operation.
6. Run backend migrations against a disposable PostgreSQL database; verify the escrow tables and unique constraints. Do not run this migration against production.
7. Confirm the escrow router is exposed only in a testnet-configured deployment, provider endpoints point only to testnet, and frontend signing remains disabled until the review gate is separately approved.
8. Capture the initial contract getters and deployment transaction trace before proceeding.

## Transaction preparation and evidence requirements

For every action, persist the unsigned wallet request and its digest before returning it to the client. Bind it to deal ID, actor, action, network, ABI/code hash, contract address, query ID, attempt ID, and expiration. A repeated idempotency key with the same request returns the same action; a different request returns HTTP 409.

A wallet reference is only a correlation hint. Persist it idempotently and never treat it as proof. The observer must independently discover the transaction and reconcile the full trace and getters before a canonical state transition.

A qualifying evidence record must include:

- network/global ID and masterchain sequence number;
- finalized transaction hash, account address, logical time and transaction phase;
- inbound and outbound message hashes, trace identity and full trace;
- source, destination, value, bounce/bounced flags and decoded body/opcode;
- deal salt, action/query ID and monotonic attempt ID;
- contract code hash and the exact getter result before/after the transaction;
- provider identity, retrieval time, raw response digest and parser version;
- explicit finality and getter-reconciliation decisions.

TON Center v3/indexer observations alone are not a cryptographic proof of finality. The provider's finality policy and evidence source must be independently reviewed; if the implementation cannot establish the configured finality guarantee, keep the event pending/manual-review and do not advance state.

## Required test matrix

Use a fresh deal and valueless fixture NFT per independent scenario. Record the complete evidence bundle above for every successful transition.

| Scenario | Expected assertion | Required evidence |
|---|---|---|
| Seller activation / deployment | Deterministic address from exact StateInit; immutable roles and terms | StateInit BOC, address derivation output, deployment trace, getters |
| NFT deposit | Only the snapshotted item, seller owner, deposit query ID and inline payload accepted | Finalized item-to-escrow trace and `get_progress` |
| Wrong NFT / wrong sender / wrong query ID | No canonical progress; unexpected item goes to manual recovery where applicable | Rejected trace and unchanged/recovery getter |
| Buyer funding | Exact principal plus configured execution reserve; wrong amount rejected | Finalized inbound value and progress getter |
| Buyer acceptance | Buyer-only and valid state; no optimistic delivery on submitted reference | Finalized accepted message and progress getter |
| Release / delivery | Exact NFT transfer, expected recipient, accepted oracle attestation and matching getter | Full NFT trace, attestation, finalized seqno, getter reconciliation |
| Refund | Correct buyer recipient and exactly-once principal settlement | Finalized payout/refund trace and terminal getter |
| Timeout / expiry | Deadline boundary at -1, 0, +1 seconds; no premature expiry | Block time, finalized timeout trace and getter |
| Dispute / hold | Correct phase, buyer authorization, nonce and resolver threshold; no automatic release | Dispute and resolver traces, getter |
| Voluntary NFT return | Buyer actually returns the exact NFT; escrow cannot seize it | TEP-62 trace and getter |
| Bounce | Every outbound action bounce is detected; ambiguous state goes to manual review | Bounced message/action phase and recovery getter |
| Duplicate/replayed messages | No second settlement or state transition | Same message replay, unchanged terminal getter |
| Reordered / stale attestations | Stale nonce, wrong deal salt, wrong query/attempt or wrong contract rejected | Rejected trace and unchanged getter |
| Provider outage / lag / conflicting fork | Cursor remains durable; pending may promote monotonically; conflict freezes for review | Raw provider responses, cursor/lease record and reconciliation report |
| Concurrent purchase | Exactly one buyer reserves the listing; all competing requests conflict | Concurrent API test, DB row locks/unique index and ordinary Orders assertion |

## Evidence bundle layout

Store sanitized evidence in the PR or a restricted test evidence store; never store secrets:

```text
evidence/<test-run-id>/
  manifest.json              # commit, ABI/code hash, network, fixture IDs
  stateinit.json             # immutable inputs, BOC digest, derived address
  transactions/<step>.json   # finalized transaction + complete trace
  getters/<step>.json        # raw getter response + parsed state
  provider/<step>.json       # provider response digest and finality decision
  assertions.md              # expected vs observed transition
```

Each manifest must identify the exact source commit and artifact digest. Redact wallet credentials and all private keys.

## Stop conditions and rollback

- Any mainnet global ID, mainnet endpoint, unknown code hash, mismatched StateInit/address, unexpected recipient, wrong NFT, duplicate settlement, missing getter, non-final trace, provider conflict or ABI mismatch: STOP and set the deal to manual review.
- Do not retry a wallet action with a new idempotency key merely because a response timed out. First reconcile the action record and chain trace.
- Do not delete or rewrite evidence. Record corrections as append-only follow-up evidence.
- A failed deployment/test uses only disposable testnet wallets and assets. Never compensate from real funds.

## Current acceptance status

The PR #193 Sandbox suite is useful contract-level evidence, but it is not live testnet evidence. As of this runbook revision, no independent audit, valueless testnet deployment, finalized transaction trace bundle, independent oracle/resolver operator evidence, or live provider finality/getter reconciliation has been supplied. Gate B is therefore **closed**. Signing must remain disabled.
