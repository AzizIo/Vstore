# Listing Creation Flow — Technical Design

**Status:** implemented seller inventory, private drafts, live-verified publication, and seller listing management.
**Scope:** seller-owned TON NFT discovery, safe draft creation, verified publication, editing, and unpublishing.  
**Non-goal:** checkout, escrow, payment collection, NFT transfers, or Telegram Gift custody.

## 1. Current repository state

- `NFTAsset` already stores asset type, external ID, item address, owner user ID, metadata, verification status, and verification timestamp.
- NFT asset identity is scoped by asset type, TON network, and external ID so the same address on mainnet and testnet cannot overwrite the other network's asset.
- `Wallet` stores a user association, network, address, and `is_verified`.
- `GET /api/listings/me` returns the authenticated user's listings.
- `POST /api/listings` creates a draft only when the supplied asset exists, belongs to the current user, and has `verification_status=verified`.
- The existing TON NFT verifier can validate an item address against an expected owner address.
- POST /api/listings/{listing_id}/publish publishes only an owned TON NFT draft after a fresh TEP-62 owner check against a verified seller wallet.
- Seller-only PATCH /api/listings/{listing_id} and POST /api/listings/{listing_id}/cancel support permitted field edits and cancellation/unpublishing.
- `GET /api/assets/me` discovers candidates from verified wallets owned by the authenticated user and returns only items freshly verified by the TEP-62 verifier.
- TON Center provider pagination and network-specific configuration are implemented in `backend/app/assets/ton_nft/`.

The existing draft endpoint is not enough for a usable create-listing flow: the frontend has no supported way to discover and select an eligible asset.

## 2. Dependency on the merged wallet-proof flow

Issue #9 is merged. The backend now exposes authenticated `POST /api/wallets/proof/challenge`, `POST /api/wallets/proof/verify`, and `GET /api/wallets/me` endpoints. A wallet is marked verified only after the server validates its TON Connect proof and binds it to the authenticated user.

The inventory endpoint consumes only server-side wallet records associated with the authenticated user and marked verified. It never accepts an arbitrary wallet address as proof that the caller owns that wallet. The proof verifier accepts raw workchain-0 addresses; inventory uses the configured `TON_CONNECT_NETWORK` and network-specific TON Center endpoint.

A verified wallet proof is not an NFT ownership proof. The inventory flow must still verify each NFT owner against that wallet, and must re-check ownership before accepting a listing draft.

## 3. Proposed API contract

### `GET /api/assets/me`

Authentication: `Authorization: Bearer <JWT>` required.

Query parameters:

| Parameter | Type | Default | Constraints |
|---|---|---:|---|
| `wallet_id` | UUID | omitted | Must identify a verified wallet belonging to the current user and configured network |
| `limit` | integer | 24 | 1–100 |
| `offset` | integer | 0 | >= 0 |

Behavior:

1. Resolve the current user from the JWT.
2. Select only verified wallet records belonging to that user and configured network. If `wallet_id` is supplied, an unavailable, foreign, unverified, or wrong-network wallet returns the same 404 response. If omitted, choose the primary verified wallet, otherwise the most recently linked verified wallet.
3. Query TON Center API v3 `GET /nft/items` using the selected wallet's normalized `owner_address`, `limit`, and `offset`. `TON_CENTER_API_KEY` is sent only in the server-side provider header.
4. Treat indexer results as discovery candidates only. For each candidate, run the existing TEP-62 verifier against the wallet address. Owner-mismatched or otherwise unverified items are excluded.
5. Upsert the corresponding `NFTAsset` with the current user as owner, verified status, verification timestamp, and bounded display metadata. The `(asset_type, external_id)` unique constraint plus PostgreSQL upsert makes repeated and concurrent syncs idempotent. Assets with active/reserved listings are not reassigned or returned as eligible.
6. Never trust metadata as proof of ownership and never fetch metadata/image URLs server-side. The provider response is bounded to 2 MB.
7. Provider outage returns HTTP 503; malformed or oversized provider data returns HTTP 502, never a successful empty inventory.

Proposed response:

```json
{
  "items": [
    {
      "id": "asset-database-uuid",
      "asset_type": "ton_nft",
      "external_id": "normalized-item-address",
      "item_address": "normalized-item-address",
      "name": "Collectible name",
      "description": null,
      "image_url": null,
      "verification_status": "verified",
      "eligible_for_listing": true
    }
  ],
  "wallet_id": "verified-wallet-uuid",
  "limit": 24,
  "offset": 0,
  "next_offset": 24,
  "has_more": false
}
```

TON Center v3 documents `nft_items` and `limit`/`offset`, but does not document a total count for this filter. The provider requests one lookahead row and the API returns `has_more` plus `next_offset`; it deliberately does not fabricate `total`. A response may contain fewer eligible items than `limit` because candidates are independently verified, so clients continue pagination using `next_offset` while `has_more` is true.

### `POST /api/listings` (existing endpoint)

Keep the existing request contract:

```json
{
  "asset_id": "asset-database-uuid",
  "price_amount": "1.25",
  "price_currency": "TON",
  "title": "Optional seller title",
  "description": "Optional description"
}
```

Server requirements before accepting the draft:

- asset belongs to the authenticated user;
- asset type is supported for this flow (`ton_nft`);
- asset has a valid item address and is marked verified;
- perform a fresh owner verification against one of the user's verified wallets before creating the draft, or explicitly reject stale verification;
- ensure there is no conflicting active/reserved listing for the same asset;
- never accept `seller_id`, `owner_id`, `status`, `is_verified`, or owner address from the client.

The endpoint now locks the owned asset, rejects unsupported, stale, foreign, or active/reserved assets, then performs a fresh TEP-62 owner check against the user's verified wallets on the configured network before creating the draft. Provider outage returns HTTP 503; failed ownership verification returns HTTP 409. Wallet proof verification code is unchanged.

### POST /api/listings/{listing_id}/publish

Authentication: Bearer JWT required. The caller must own the listing.

- Only a DRAFT listing backed by a seller-owned, verified TON NFT asset on the configured network is eligible.
- The server takes an unlocked snapshot of the listing, asset, and the seller's verified wallets, then rolls back the read transaction before contacting TON Center through the TEP-62 verifier.
- The live owner must match one of the seller's verified wallets on the asset network. Provider outage returns HTTP 503; stale, unsupported, or mismatched ownership returns HTTP 409.
- After verification the server starts a new transaction, locks and re-reads the listing, selected wallet, and asset, and verifies that the seller, asset identity, draft status, owner, network, verification state, and wallet binding have not changed.
- The wallet is locked before the asset (matching the existing draft-creation lock order), then the asset row is locked before checking for another ACTIVE/RESERVED listing. This serializes concurrent publication attempts; the PostgreSQL partial unique index uq_listings_open_asset remains the final database-level guard.
- Only then does the server change DRAFT to ACTIVE. Public catalog, public detail, and order creation continue to query ACTIVE listings only.

### PATCH /api/listings/{listing_id} and POST /api/listings/{listing_id}/cancel

Both endpoints require the authenticated seller. Edits are limited to price_amount, title, and description; seller IDs, asset ownership, currency, and status are never client-editable. Edits are allowed only while DRAFT or ACTIVE. Cancellation is allowed for a private DRAFT or public ACTIVE listing; cancelling an active listing unpublishes it. RESERVED, SOLD, CANCELLED, and EXPIRED listings are not editable or cancellable. These transitions lock and re-read the seller-owned listing inside a transaction.

## 4. Frontend flow after the API exists

1. User opens **My Listings** and chooses **Create listing**.
2. If no verified wallet exists, show a connect/verify-wallet state and link to the existing TON Connect UI. A connected wallet alone is not proof of ownership.
3. Load `GET /api/assets/me` with the current SessionProvider access token.
4. Show only verified eligible TON NFTs; include loading, empty, error/retry, and `has_more`/`next_offset` pagination states.
5. User selects an NFT, enters a price and optional title/description.
6. Submit the existing draft request.
7. Show a success state and refresh My Listings. Clearly label the result **Draft — not published**.
8. From a draft detail, the seller can edit price/title/description, request publication (with confirmation), and cancel the draft. Publication displays a verifying/loading state and reports provider/state conflicts accessibly.
9. From an active listing, the seller can edit permitted fields or confirm unpublishing. Listings reserved by a pending order are read-only until the reservation ends.

Telegram Gifts remain excluded from this first creation flow until a supported, tested ownership and transfer capability is available for the specific account/gift type.

## 5. Security and correctness requirements

- Derive user identity exclusively from the JWT dependency.
- Never trust wallet addresses, ownership flags, asset owner IDs, verification status, or listing status supplied by the browser.
- A verified wallet proof is separate from NFT ownership: check the current NFT owner for each candidate and again before draft creation.
- TON Center v3 is an indexed data provider, not a trustless proof. Record verification time and handle provider lag/outages explicitly.
- Treat NFT name, description, image URL, and attributes as untrusted display metadata.
- Never fetch arbitrary metadata URLs on the server; prevent SSRF and oversized responses.
- Do not log JWTs, wallet proof payloads, signatures, or sensitive user data.
- Make inventory sync idempotent and handle concurrent requests/unique constraints safely.
- Do not create on-chain transactions or transfer NFTs during inventory discovery or draft creation.

## 6. Required tests for the future backend task

- unauthenticated request is rejected;
- a user cannot request inventory for another user's wallet;
- unverified wallet is not used;
- provider pagination and empty inventory;
- malformed provider response and provider timeout/outage;
- owner mismatch is excluded from eligible inventory;
- valid TEP-62 item is persisted/updated idempotently;
- stale ownership is rejected at draft creation;
- asset owned by another user is rejected;
- unsupported Telegram Gift is not made eligible;
- concurrent sync does not create duplicate assets;
- provider metadata is bounded and never fetched as a URL;
- publication rejects stale/foreign/unsupported/unverified assets and provider outages;
- provider calls run without database locks, then listing/asset/wallet state is rechecked under locks;
- concurrent publication attempts for different drafts of one NFT produce at most one active listing;
- seller-only edit/cancel transitions reject reserved and terminal listings.

## 7. Official technical references

- TON Center API v3 NFT items: https://docs-next.ton.org/api/v3/nfts/get-nft-items
- TON Center API v3 pagination: https://docs-next.ton.org/api/v3/pagination
- TON Center API v3 overview: https://docs.ton.org/ecosystem/api/toncenter/v3/overview
- TON NFT standard TEP-62: https://github.com/ton-blockchain/TEPs/blob/master/text/0062-nft-standard.md

This document is a technical design, not an implementation or a security audit.
