# TON Escrow frontend boundary

This folder is an isolated frontend preparation layer for the proposed MRKT-style escrow flow. It is not wired into the current App navigation, current `orders` API, Telegram Stars flow, or the non-custodial `DeliveryWorkspace`.

## Current UI/data flow

- `EscrowWorkspace` owns the standalone seller and buyer workspaces, state timelines, disputes, transaction review, and withdrawal history.
- `inventory.ts` reuses `fetchMyWallets` and `fetchMyInventory`. It only exposes NFTs from persisted, server-verified TON **testnet** wallets and checks the returned wallet ID and NFT verification/eligibility fields. A TonConnect connection is never treated as ownership evidence.
- `TonConnectEscrowAdapter.ts` accepts only a Backend-prepared transaction. It does not create opcodes, payload BOCs, addresses, amounts, or fee calculations. It checks chain ID `-3`, exact prepared network, transaction expiry and canonical address equality with the persisted verified wallet. A BOC digest is only an untrusted observer lookup hint.
- `api/escrow.ts` contains provisional domain types, runtime validators and an injected HTTP contract. No endpoint path, JSON request body, response URL or transaction opcode is invented here.
- `escrowState.ts` is presentation-only. It never infers chain completion, balance or withdrawal eligibility from UI state.

## API and ABI decisions still required

The Backend/contract team must publish and version:

1. Exact API paths, HTTP methods, query parameters, pagination/cursor format, request DTOs, response DTOs and participant-scoped authorization for public marketplace listings, seller listings, buyer deals, seller deals, withdrawal history, listing/deal detail, action preparation and wallet-reference submission.
2. Canonical field names and nullability. Current TypeScript examples use snake_case and these provisional snapshots:
   - Listing: `id`, `seller_id`, `state`, `network`, `nft`, `contract_address`, `seller_wallet_address`, `price_ton`, `platform_fee_ton`.
   - Deal: buyer/seller IDs and wallet addresses, immutable listing/NFT/price snapshots, `seller_claimable_ton`, confirmation/dispute deadlines and optional dispute.
   - Withdrawal: listing/deal, kind, state, amount/destination, optional transaction reference.
   - Prepared wallet action: unique operation ID, `testnet`, exact contract and NFT addresses, value-bearing messages, explicit amounts, fee fields and `valid_until`.
3. Distinguish **platform fee** from **network execution reserve**. `fee_ton` is shown as the platform commission; optional `network_fee_ton` is shown separately. The UI does not calculate either value.
4. Publish separate buyer and seller deal feeds. Seller claimability must come from the authenticated Backend projection/contract evidence, never a locally summed balance.
5. Define the buyer NFT return action for buyer-favourable post-delivery disputes. The UI exposes it only in `refund_pending_nft_return`; the contract/Backend must ensure funds cannot be refunded until the NFT return is independently confirmed.
6. Define operation idempotency and reconciliation for TON Connect BOC references. A submitted BOC digest is not a transaction hash or success event. Backend observer remains the authority for all terminal/confirmed states.
7. Freeze the transaction ABI/TL-B and approved message schema before turning on the wallet signer. The browser must never derive opcodes or construct arbitrary payloads.

All endpoint and serializer functions are injected through `EscrowHttpContract`. The host can add its implementation only after the API contract is approved; until then `api` is optional and the workspace renders an explicit unavailable state.

## Wallet signing safety

Signing requires both the component prop `allowTestnetSigning={true}` and build-time `VITE_ESCROW_TESTNET_SIGNING_ENABLED=true`. The feature is otherwise fail-closed. Do not enable this flag until the ABI, backend API, transaction review text and live **testnet** acceptance have been reviewed. There is no mainnet path.

The transaction review must show the exact network, escrow address, NFT item (when relevant), amount, platform commission, network reserve, signer and expiry before TON Connect is called. Wallet connection is not proof of ownership; the signer must match the already verified Backend wallet snapshot. No secret material is requested or handled.

An ambiguous TON Connect result must never cause an automatic second signing request. Resolve the first operation from Backend/observer state before creating another operation.

## Integration and acceptance

The workspace is intentionally not added to `App.tsx` or the existing shell navigation because the requested file boundary excludes those files and the API/ABI/product gates remain open. A separate, reviewed host integration should provide:
- a stable `EscrowApiClient` created from the final `EscrowHttpContract`;
- authenticated `accessToken` and authoritative `currentUserId`;
- the public TON Connect manifest URL;
- an explicit signing opt-in only for an approved testnet environment.

This frontend is not a payment processor, custody service or source of chain truth. Never label a wallet response, pending API intent or submitted reference as paid, delivered, settled, refunded or withdrawn before Backend observer confirmation.
