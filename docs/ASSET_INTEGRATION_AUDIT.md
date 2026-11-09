# Asset Integration Audit — VILTARA SHOP

**Audit date:** 2026-11-09  
**Scope:** Telegram Bot API gifts, TON NFT standard, wallet connection, payment constraints.  
**Status:** Initial technical assessment based on official documentation. Live end-to-end transfer tests are still required.

## 1. Executive decision

VILTARA SHOP should launch its first real-asset flow around **standard TON NFTs that implement TEP-62**, while treating Telegram Gifts as a separate, restricted integration.

Do not model every Telegram gift as a freely transferable TON NFT. Do not advertise escrow or automatic delivery until the exact asset transfer and payment path has passed testnet and operational tests.

## 2. Telegram Gifts: what the Bot API actually permits

The current Telegram Bot API documents these relevant methods:

- `getBusinessAccountGifts`: lists gifts owned by a managed business account. Requires `can_view_gifts_and_stars`.
- `getUserGifts`: lists gifts owned and hosted by a user, with pagination and filters.
- `getChatGifts`: lists gifts owned by a chat.
- `getUniqueGift`: gets information about a unique gift by its unique name.
- `upgradeGift`: upgrades a regular gift owned by a managed business account; requires `can_transfer_and_upgrade_gifts`, and may require `can_transfer_stars`.
- `transferGift`: transfers an owned unique gift from a managed business account; requires `can_transfer_and_upgrade_gifts`. The recipient chat must have been active in the last 24 hours. Paid transfers also require `can_transfer_stars`.

### Consequences

1. Gift discovery and gift transfer are different capabilities. The existence of `getUserGifts` does not grant the bot a general right to transfer gifts from arbitrary users.
2. The documented `transferGift` operation is scoped to a managed business account and a `business_connection_id`.
3. A seller-to-marketplace flow based on Telegram Business requires the seller to connect a business account and grant the necessary rights. It is not a universal custody mechanism for all Telegram users.
4. Gifts assigned from the TON blockchain may be flagged as `exclude_from_blockchain` because they cannot be resold or transferred in Telegram. Their blockchain transfer path must be treated separately.
5. The app must check the actual gift state and transfer eligibility before allowing an order to be created.

**MVP decision:** Telegram Gifts can initially be displayed and enriched using supported Bot API data, but should be marked as non-transferable / unsupported for automatic escrow unless a tested supported transfer path exists for that exact gift and seller account.

## 3. TON NFT: supported standard and verification

The baseline standard is **TEP-62**:

- Each NFT item is a separate smart contract.
- The item exposes `get_nft_data()`, including initialization state, item index, collection address and current owner address.
- A collection exposes `get_nft_address_by_index(index)`.
- The item transfer message uses the TEP-62 `transfer` operation.

### Verification requirements

For every listed NFT:

1. Normalize and validate the item contract address.
2. Read `get_nft_data()`; reject uninitialized or malformed items.
3. Read the collection address and item index.
4. If the NFT claims a collection, call the collection's `get_nft_address_by_index(index)` and verify that it resolves to the same item address.
5. Read the owner address and compare it with the seller's wallet address.
6. Resolve metadata defensively; treat name, image and attributes as untrusted display data, not proof of ownership or authenticity.
7. Re-check ownership immediately before accepting a seller deposit and after the transfer to the destination is finalized.

Important: TON is asynchronous. A read of an NFT owner is a point-in-time observation, not a reservation. Ownership can change after the check. A listing therefore needs periodic revalidation and a final verification during purchase.

### Transfer and escrow implications

A normal TEP-62 transfer is initiated by the current owner. TON Connect lets the user connect a wallet and approve a transaction; it does not give the backend custody of the user's private key.

For escrow of a standard TON NFT, the seller would need to transfer the item to a designated escrow smart contract or controlled address. A custom escrow contract is a separate security-critical component and must be designed, reviewed and tested before handling valuable assets.

**MVP decision:** begin with wallet-connected listing verification and direct seller-to-buyer transfer in a test environment. Add on-chain escrow only after a dedicated contract design and audit. Do not claim the marketplace guarantees delivery while the seller retains unilateral control of the NFT.

## 4. Payments inside Telegram

Telegram's official digital-goods payment documentation says sales of digital goods and services inside Telegram bots and Mini Apps must use Telegram Stars (`XTR`). The Bot API flow includes invoice creation, `pre_checkout_query`, confirmation, and a `successful_payment` update. The successful payment's `telegram_payment_charge_id` should be stored for possible refunds.

TON Connect is still appropriate for permitted blockchain interactions such as wallet connection and user-approved NFT transactions. It must not be presented as a workaround for Telegram's Stars requirement for digital goods checkout inside Telegram.

The marketplace's business model and the legal/payment classification of peer-to-peer NFT resale need a separate review before production. We should not assume that collecting Stars automatically creates a compliant escrow or payout system.

## 5. Recommended product scope

### Phase A — safe catalogue and verification

- Browse curated TON NFT collections.
- Open an NFT by item address.
- Verify TEP-62 structure, collection membership and current owner.
- Let a seller connect a wallet and prove control by signing/approving a supported wallet action.
- Create a listing with a short validity window and automatic ownership re-check.
- Display Telegram Gifts as a separate asset type, with explicit capability/status labels.

### Phase B — testnet transfer

- Seller approves transfer of a test NFT to a buyer-controlled wallet.
- Backend watches the item contract and verifies the new owner.
- Order state changes only after confirmed chain data is observed.
- Add idempotency keys, retry handling and an immutable order event log.

### Phase C — escrow and payments

- Specify the custody model and contract state machine.
- Threat-model reentrancy/message ordering, failed messages, timeouts, refunds, cancellation, and disputes.
- Test on TON testnet, then arrange an independent contract review.
- Integrate Telegram Stars only for in-Telegram digital-goods purchases where applicable; define a separate permitted payout process.
- Do not launch real-value escrow until all failure and recovery paths are proven.

## 6. Architecture impact

Keep the modular monolith, but define separate adapters:

- `assets/ton_nft` — TEP-62 reads, collection checks, metadata, owner verification.
- `assets/telegram_gifts` — Bot API gift lookups and business-account capabilities.
- `blockchain/ton` — RPC/indexer client, transaction watcher, confirmation policy.
- `wallets` — TON Connect proof/session association; never store user private keys.
- `orders` — order state machine and immutable event log.
- `escrow` — disabled behind a feature flag until its contract and operational design are approved.
- `payments/stars` — Stars invoices, successful-payment processing and refunds.

Suggested listing statuses: `draft`, `pending_verification`, `active`, `reserved`, `sold`, `expired`, `suspended`.

Suggested asset capability values: `view_only`, `wallet_transfer`, `business_transfer`, `escrow_supported`, `unsupported`. Capabilities must be computed from verified asset type and current account permissions, not user input.

## 7. Official references

- Telegram Bot API: https://core.telegram.org/bots/api
- Telegram Stars payments for digital goods: https://core.telegram.org/bots/payments-stars
- TON NFT standard TEP-62: https://github.com/ton-blockchain/TEPs/blob/master/text/0062-nft-standard.md
- TON NFT implementation guide: https://docs.ton.org/contracts/standard/tokens/nft/how-it-works
- TON Connect overview: https://docs.ton.org/applications/ton-connect/overview

---

This document is a technical assessment, not a legal opinion or a security audit. All real-value transfer paths require testnet validation and review before launch.
