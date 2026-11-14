# TON Escrow frontend boundary

This is an isolated frontend preparation layer for the VILTARA/MRKT-style TON Escrow testnet PoC. It follows the coordinator-owned [TON Escrow Shared Interface Contract](https://github.com/AzizIo/Vstore/blob/docs/mrkt-style-ton-escrow-architecture/docs/TON_ESCROW_SHARED_INTERFACE.md) and the [MRKT-style architecture](https://github.com/AzizIo/Vstore/blob/docs/mrkt-style-ton-escrow-architecture/docs/MRKT_STYLE_TON_ESCROW_ARCHITECTURE.md), currently maintained on the dedicated documentation branch. It is not mounted into current App navigation, current `orders` API, Telegram Stars, or the seller-direct `DeliveryWorkspace`.

## Canonical resource model

**Listing intent and DealEscrow are different resources.**

1. Seller creates an off-chain listing intent from an NFT returned by the existing Backend-verified inventory API. Asking price is typed as a decimal TON string and converted to exact integer nanotons without floating point. This does not deploy a contract or claim that the NFT is in escrow.
2. Buyer selects a public listing intent and creates a deal intent with a persisted verified testnet wallet. This binds one buyer/seller/NFT/principal snapshot to one deal.
3. Only after the buyer is bound does the seller prepare the immutable single-deal DealEscrow deployment and deposit operation. Contract address and state are treated as unconfirmed until the Backend observer reconciles them.
4. Buyer can fund only after the deal reaches `awaiting_buyer_funds`. In `funded_review`, buyer accepts before the NFT release is initiated, or opens a dispute.
5. Delivery and settlement remain pending until the observer/oracle-backed contract projection is reconciled. A post-delivery dispute may require the buyer to return the exact NFT to escrow first.
6. Seller payout and buyer refund are contract-initiated. The frontend only displays `seller_payout_pending` / `buyer_refund_pending`; there is no manual claim/payout/refund button in this PoC. Unsold NFT withdrawal is a separate seller action exposed only when Backend supplies `withdraw_unsold_nft`.

The frontend uses the canonical deal statuses:
`intent_created`, `awaiting_nft`, `awaiting_buyer_funds`, `funded_review`, `nft_release_pending`, `delivered_dispute_window`, `disputed`, `nft_return_pending`, `seller_payout_pending`, `buyer_refund_pending`, `settled`, `refunded`, `expired`, `manual_review`.

Listing-intent states are a separate enum:
`intent_only`, `active`, `reserved`, `cancelled`, `manual_review`.

This supersedes any earlier UI shorthand such as `payment_received`, `buyer_confirmation_window`, or `seller_claimable_ton`. Buyer acceptance happens in `funded_review` **before** NFT release; there is no post-delivery confirm-receipt action. Availability of every button is driven by Backend `available_actions`, not inferred from a local status guess.

## Current UI/data flow

- `EscrowWorkspace` owns the standalone seller and buyer workspaces, listing intents, deal timeline, dispute details, transaction review, and unsold-NFT withdrawal history.
- `inventory.ts` reuses `fetchMyWallets` and `fetchMyInventory`. It only exposes NFTs from persisted, server-verified TON **testnet** wallets and validates the returned wallet ID and NFT verification/eligibility fields. A TonConnect connection is never an ownership signal.
- `TonConnectEscrowAdapter.ts` accepts only Backend-prepared transaction data. It validates testnet chain `-3`, expiry, exact verified signer and action-specific message recipients:
  - `create_deal_escrow` → Factory;
  - `deposit_nft` / `return_nft_to_escrow` → exact NFT item;
  - `fund_deal`, `accept_deal`, `open_dispute`, `withdraw_unsold_nft` → DealEscrow.
- The transaction review shows every outgoing message destination and amount in nanotons and TON, Factory/DealEscrow/NFT addresses, price, fee_bps, execution reserve, signer and expiry. No opcode or payload is created in the browser.
- `api/escrow.ts` contains provisional listing-intent/deal/dispute/withdrawal DTOs, runtime validators and an injected HTTP contract. No endpoint URL or unapproved request path is guessed.
- `escrowState.ts` maps canonical listing and deal states. It converts decimal TON to/from nanotons using string/BigInt operations only.

## Shared API/ABI decisions still required

The Backend/contract workstreams must finalize and version:

1. API paths, HTTP methods, cursor format, payload and response schema for listing intents, buyer deal-intent creation, buyer/seller deal feeds, action preparation, participant-scoped detail, withdrawal history and BOC-reference submission.
2. Exact canonical field names/nullability and immutable snapshot fields, including listing key, network, escrow address, seller/buyer wallet, NFT item, price_nano, fee_bps, deadlines, chain evidence and dispute projection.
3. `available_actions` values and participant authorization. UI only renders buttons when the Backend includes the canonical action in this array.
4. Action preparation fields: `action_id`, action, testnet network, valid_until, exact Factory/DealEscrow/NFT addresses, nanotons per outgoing message, payload/state-init bytes, display purpose and execution reserve.
5. Confirmation semantics: the returned wallet BOC digest is a lookup hint only. Backend observer must distinguish off-chain evidence observation from oracle-accepted contract state, then reconcile the contract getter/state before updating the view model.
6. Exact deployment transaction sequence and predicted DealEscrow address. Factory address may be shown for deployment; do not invent a deal address before the backend returns it.
7. Seller unsold-NFT withdrawal eligibility and its finality projection. No payout/refund transaction is user-signed in this PoC.
8. The first PoC fixes `fee_bps = 0`. Non-zero commission/payout arithmetic must be rejected until separately reviewed.
9. Listing and deal timers must expose the exact triggering event/deadline. UI must not create local deadlines or start the dispute clock from a client callback.

All path/serializer functions are injected through `EscrowHttpContract`. The host can add them only after the shared API is approved; until then `api` is optional and the workspace renders an explicit unavailable state.

## Wallet signing safety

Signing requires both `allowTestnetSigning={true}` and build-time `VITE_ESCROW_TESTNET_SIGNING_ENABLED=true`. It is otherwise fail-closed. The adapter has no mainnet path. Each action validates an action-specific recipient allowlist before invoking TON Connect and forwards Backend-prepared destination, nanotons and BOC/state-init bytes unchanged.

The UI never treats wallet connection, submitted hash, a pending API response or BOC digest as success. Unknown wallet result blocks new signing attempts until Backend observer reconciliation. No seed phrase/private key is requested or handled. Backend-projected claimable balances are not computed locally; in this PoC, seller payout/refund are contract-initiated and shown only as pending/finalized states.

## Platform / product gate

The public TON purchase CTA must not be enabled inside the Telegram Mini App until Issue #155's written platform ruling and qualified legal review clear this exact P2P resale flow. The workspace is standalone and is not added to `App.tsx`. A testnet prototype is not permission to expose a real purchase flow.

## Integration and acceptance

A future reviewed host integration must provide:
- an `EscrowApiClient` created from the final `EscrowHttpContract`;
- authenticated `accessToken` and authoritative `currentUserId`;
- public TON Connect manifest URL;
- explicit testnet-only signing opt-in after ABI/API review.

Tests use mocked API responses and mocked TON Connect only. There are no real transactions, no mainnet credentials, no production order/Stars integration, and no DB or contract writes.
