# VILTARA TON Escrow PoC — Acton / Tolk

This is an isolated, **TON testnet-only** implementation of one immutable DealEscrow per buyer/seller deal. It is not mounted by the VILTARA FastAPI app, not linked to Orders or Telegram Stars, and not exposed as a public Mini App purchase flow.

## Safety boundary

- Contract state-changing entrypoints check TON global ID **-3** (testnet/localnet) and reject mainnet global ID -239.
- A deal has one fixed seller, buyer, exact TEP-62 NFT item, collection reference, integer nanotons principal, unique salt and fixed operation query IDs.
- Contract code has no upgrade method, owner-withdraw method, arbitrary payout recipient, or server-held signing key.
- Buyer funds are accepted only after the exact configured NFT item reports the seller-to-escrow ownership notification with the expected query ID and deal salt.
- The buyer must accept in FUNDED_REVIEW before the NFT transfer. Raw transfer observations do not start the dispute window.
- Delivery, seller payout and buyer refund remain pending until a 2-of-3 evidence-oracle attestation with deal/network/route/query/message/trace/evidence/finality fields is accepted.
- Disputes require a separately configured 2-of-3 resolver. A post-delivery buyer-favourable dispute requires the same NFT to be returned to escrow; the contract cannot seize an NFT from a buyer-controlled wallet.
- Initial fee is zero. The exact NFT item address is allowlisted in each deal's immutable StateInit; collection address is retained as metadata and does not substitute for item authenticity.

**Only transfer the exact NFT item address frozen into the deal.** The contract intentionally ignores notifications from other item contracts; sending an unrelated NFT to this escrow address may strand it. This is a PoC with a deliberately narrow item allowlist, not a general-purpose NFT receiver.

## Protocol v1

The numeric opcodes and typed cell layouts are defined in `contracts/types.tolk` and generated ABI output. Custom opcodes are 32-bit unsigned integers.

| Opcode | Struct | Purpose |
|---:|---|---|
| `0x56450001` | `ActivateDeal` | Seller opens the 30-minute NFT deposit window |
| `0x56450002` | `FundDeal` | Bound buyer attaches exactly principal + execution reserve |
| `0x56450003` | `AcceptDeal` | Bound buyer accepts in the 24-hour FUNDED_REVIEW window |
| `0x56450004` | `OpenDispute` | Bound buyer opens a pre- or post-delivery dispute |
| `0x56450005` | `OracleAttestation` | 2-of-3 evidence quorum attests an exact finalized chain action |
| `0x56450006` | `ResolveDispute` | 2-of-3 resolver signs a constrained outcome |
| `0x56450007` | `TimeoutDeal` | Permissionless state-specific timeout |
| `0x56450008` | `RecoverUnexpectedNft` | Fixed-recipient recovery for a malformed callback from the configured item |

The escrow uses standard TEP-62 `transfer#5fcc3d14` and `ownership_assigned#05138d91`. The forwarded payload is inline-only for protocol v1: selector bit 0, `NFT_FORWARD_MAGIC` (32 bits), and deal salt (256 bits). Non-inline or malformed payloads never activate a deposit. The test-only NFT mock implements these message shapes and is not a public NFT collection/item.

### Oracle signatures

The evidence signature is Ed25519 over the TON representation hash of `OracleAttestationData` as a typed cell. The typed data is composed of four referenced cells:

1. `OracleContext`: domain, protocol version, network global ID, escrow address, deal salt, action and attempt ID.
2. `OracleRoute`: exact NFT item, source, destination, amount and operation query ID.
3. `OraclePosition`: positive masterchain sequence number and transaction logical time.
4. `OracleEvidenceHashes`: message hash, trace hash and retained raw evidence hash.

Three independent public keys are snapshotted in StateInit. At least two signatures must validate; each signature is tied to its corresponding key slot, so one signer cannot be counted twice. Oracle public keys must be unique and disjoint from resolver keys. Every outbound action advances a stored, monotonic `oracleAttemptId`; the same value is placed into its TON query ID and must match the signed context and the observed route. Resolver decisions separately bind to a monotonic `disputeAttemptId`, so an old decision cannot be replayed in a later dispute even when the buyer reuses the same reason hash. The backend observer is not automatically an oracle; private keys must be held by independent test operators and must never be stored in VILTARA's backend.

Resolver signatures are separately domain-separated and bind network, escrow, deal salt, dispute phase, outcome, attempt ID and the buyer's dispute evidence hash. Oracle and resolver key sets are distinct. Test fixtures must never be reused for a real deployment.

## State Init and address derivation

There is no reusable listing contract or factory with buyer-less terms. The per-deal `DealEscrow` address is the standard TON address calculated from the contract code and immutable initial storage:

`address = workchain(0) : hash(StateInit(code = DealEscrow.code, data = EscrowStorage(DealTerms, DealProgress)))`

Acton's generated `DealEscrow.fromStorage(...)` wrapper calculates StateInit and address deterministically. Re-generate wrappers after any contract, storage, opcode or ABI change; never reuse an address across differing terms or code hashes. The compiled BoC, ABI and generated wrappers are CI artifacts from the pinned Acton toolchain.

## Amounts and wallet transaction rules

- `principalNanotons` is the seller's exact ask.
- `executionReserve` is separate from principal and seller proceeds. It is not a platform fee or extra payment to the seller.
- `nftTransferValue` is the fixed TON value attached by escrow to each outbound TEP-62 transfer. It is funded by execution reserve.
- Seller's deposit transaction targets the snapshotted NFT item and sets `new_owner = escrowAddress`, `response_destination = sellerAddress`, `forward_amount > 0`, and inline payload containing the fixed magic + deal salt. It must use the stored `nftDepositQueryId`.
- Buyer funding targets the escrow address, carries exactly `principalNanotons + executionReserve`, and uses `fundQueryId`.
- Buyer acceptance and dispute messages target the escrow address with operation query ID and deal salt; they do not attach principal again. For outbound NFT releases/returns and TON payout/refund, the contract ignores the static operation query IDs and uses the next persisted `oracleAttemptId` as the message query ID.
- No frontend or backend callback can mark delivery/settlement successful. The observer must provide finalized transaction and trace evidence to the separate oracle quorum.
- Payout and refund are contract-initiated to the fixed seller/buyer addresses. A client cannot choose or replace recipient or amount.

## Default testnet timing fixtures

- Seller NFT deposit: 30 minutes.
- Buyer funding after NFT lock: 60 minutes.
- Buyer review: 24 hours.
- NFT delivery confirmation grace: 30 minutes; timeout enters manual review.
- Post-delivery dispute window: 48 hours.
- NFT return after a post-delivery dispute: 24 hours.
- Arbitration: 7 days; unresolved disputes enter manual review, not automatic payout/refund.
- Payout/refund reconciliation grace: 30 minutes; missed finality enters manual review.

These are PoC fixtures, not production SLAs. Execution reserve and transfer value must be remeasured in emulator and on testnet before any wallet action is enabled.

## Build and test

From this directory:

```bash
acton up
acton build
acton wrapper --all
acton wrapper DealEscrow --ts --output wrappers-ts/DealEscrow.gen.ts
acton fmt --check
acton check
acton test --coverage --no-studio-reporting
```

The repository CI workflow runs the same pipeline and uploads compiled BoC, ABI and generated wrapper artifacts when the toolchain produces them.

## Required before live testnet acceptance

1. Inspect the exact ABI, code hash, StateInit and generated wrappers from a green CI artifact.
2. Have an independent TON smart-contract reviewer validate code, storage, signatures, bounced-message behavior, gas bounds, state machine and invariants.
3. Generate independent oracle and resolver test keys off the backend, distribute them among test operators, and configure only public keys in each deal's immutable terms.
4. Deploy one valueless test deal to TON testnet, record exact address, code hash, StateInit, transaction/message/trace hashes and masterchain checkpoints.
5. Use Tonkeeper/TON Connect testnet wallets to execute happy path, wrong NFT, wrong sender, replay, bounce, dispute, timeout and refund/payout cases.
6. Only after those checks may a separate PR wire an unsigned transaction-preparation adapter and read-only testnet provider into the backend. Do not mount the public router or activate the frontend workspace.
7. ADR-0001, Issue #153, Issue #155, live Issue #46 acceptance and legal/platform gates remain open. No mainnet, production custody, Stars conversion or in-Mini-App TON purchase is authorized.

Passing CI is not an independent audit or proof of live testnet behavior.
