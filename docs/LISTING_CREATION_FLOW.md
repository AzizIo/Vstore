# Listing Creation Flow — Technical Design

**Status:** technical design for the next seller-inventory implementation step. TON Connect wallet proof (Issue #9) is now merged; this document is still a proposal, not implemented functionality.  
**Scope:** seller-owned TON NFT discovery and safe creation of private listing drafts.  
**Non-goal:** publishing, checkout, escrow, payment collection, NFT transfers, or Telegram Gift custody.

## 1. Current repository state

- `NFTAsset` already stores asset type, external ID, item address, owner user ID, metadata, verification status, and verification timestamp.
- `Wallet` stores a user association, network, address, and `is_verified`.
- `GET /api/listings/me` returns the authenticated user's listings.
- `POST /api/listings` creates a draft only when the supplied asset exists, belongs to the current user, and has `verification_status=verified`.
- The existing TON NFT verifier can validate an item address against an expected owner address.
- There is currently no API endpoint that discovers a user's NFT inventory and no provider method for listing all NFT items by owner.

The existing draft endpoint is not enough for a usable create-listing flow: the frontend has no supported way to discover and select an eligible asset.

## 2. Dependency on the merged wallet-proof flow

Issue #9 is merged. The backend now exposes authenticated `POST /api/wallets/proof/challenge`, `POST /api/wallets/proof/verify`, and `GET /api/wallets/me` endpoints. A wallet is marked verified only after the server validates its TON Connect proof and binds it to the authenticated user.

The inventory endpoint must consume only server-side wallet records associated with the authenticated user and marked verified. It must never accept an arbitrary wallet address as proof that the caller owns that wallet. Read `docs/TON_CONNECT_PROOF.md` and the actual `Wallet` model/API implementation before coding; the exact owner-address format and supported network/workchain limitations must be respected.

A verified wallet proof is not an NFT ownership proof. The inventory flow must still verify each NFT owner against that wallet, and must re-check ownership before accepting a listing draft.

## 3. Proposed API contract

### `GET /api/assets/me`

Authentication: `Authorization: Bearer <JWT>` required.

Query parameters:

| Parameter | Type | Default | Constraints |
|---|---|---:|---|
| `wallet_id` | UUID | omitted | Must identify a verified wallet belonging to the current user |
| `limit` | integer | 24 | 1–100 |
| `offset` | integer | 0 | >= 0 |

Behavior:

1. Resolve the current user from the JWT.
2. Select only verified wallet records belonging to that user. If `wallet_id` is supplied, reject a wallet that is not theirs; never leak whether another user's wallet exists.
3. Query TON Center API v3 `GET /nft/items` using the selected wallet's normalized `owner_address`, `limit`, and `offset`. Do not expose the provider API key to the frontend.
4. Treat indexer results as discovery candidates only. For each candidate, run the existing TEP-62 verifier against the wallet address. Only currently verified items may be offered as eligible for draft creation.
5. Upsert or reconcile the corresponding `NFTAsset` records with the current user as owner, verified status, and safe display metadata. Do not trust metadata as proof of ownership; do not fetch arbitrary metadata URLs or images server-side.
6. Return a stable page response. Provider outage must produce a clear service error, not an empty inventory that looks like the user owns nothing.

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
  "total": 1,
  "limit": 24,
  "offset": 0
}
```

The exact provider response and total-count strategy must be validated against the selected TON Center API v3 version before implementation. Do not fabricate `total` if the provider does not return it; use an explicit `has_more`/cursor contract instead if needed.

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

The current endpoint checks the stored owner and verification status but does not perform a live ownership re-check. This is a known hardening requirement before the seller flow can be considered robust. It should be implemented as a separately reviewed backend change after the wallet proof work, not by changing Issue #9's files.

## 4. Frontend flow after the API exists

1. User opens **My Listings** and chooses **Create listing**.
2. If no verified wallet exists, show a connect/verify-wallet state and link to the existing TON Connect UI. A connected wallet alone is not proof of ownership.
3. Load `GET /api/assets/me` with the current SessionProvider access token.
4. Show only verified eligible TON NFTs; include loading, empty, error/retry, and pagination states.
5. User selects an NFT, enters a price and optional title/description.
6. Submit the existing draft request.
7. Show a success state and refresh My Listings. Clearly label the result **Draft — not published**.

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
- provider metadata is bounded and never fetched as a URL.

## 7. Official technical references

- TON Center API v3 NFT items: https://docs-next.ton.org/api/v3/nfts/get-nft-items
- TON Center API v3 pagination: https://docs-next.ton.org/api/v3/pagination
- TON Center API v3 overview: https://docs.ton.org/ecosystem/api/toncenter/v3/overview
- TON NFT standard TEP-62: https://github.com/ton-blockchain/TEPs/blob/master/text/0062-nft-standard.md

This document is a technical design, not an implementation or a security audit.
