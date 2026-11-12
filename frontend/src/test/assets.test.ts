import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createListingDraft, fetchMyInventory, syncMyInventory, type InventoryAsset } from "../api/assets";
import type { Listing } from "../api/listings";

const asset: InventoryAsset = {
  id: "asset-db-id",
  asset_type: "ton_nft",
  external_id: "0:" + "11".repeat(32),
  item_address: "0:" + "11".repeat(32),
  collection_address: "0:" + "22".repeat(32),
  name: "TEP-62 Collectible",
  description: "Display text",
  image_url: "https://example.test/nft.png",
  verification_status: "verified",
  eligible_for_listing: true,
};
const inventory = {
  items: [asset], wallet_id: "wallet-id", limit: 24, offset: 0, next_offset: 1, has_more: false,
};
const listing: Listing = {
  id: "listing-id", status: "draft", price_amount: "1.25", price_currency: "TON",
  title: "My NFT", description: null, created_at: "2026-01-01T00:00:00Z",
  asset: {
    id: asset.id, asset_type: "ton_nft", external_id: asset.external_id,
    item_address: asset.item_address, name: asset.name, description: asset.description,
    image_url: asset.image_url, verification_status: "verified",
  },
  seller: { id: "seller-id", username: "seller", first_name: "Seller" },
};

function jsonResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: vi.fn().mockResolvedValue(body) } as unknown as Response;
}

describe("seller asset API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("requests verified inventory with bearer auth and provider cursor", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(inventory));
    const controller = new AbortController();

    await expect(fetchMyInventory("session-token", { limit: 24, offset: 0 }, controller.signal)).resolves.toEqual(inventory);

    const [url, options] = vi.mocked(fetch).mock.calls[0];
    const parsed = new URL(String(url), "http://localhost");
    expect(parsed.pathname).toBe("/api/assets/me");
    expect(parsed.searchParams.get("limit")).toBe("24");
    expect(parsed.searchParams.get("offset")).toBe("0");
    expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer session-token");
    expect(options?.signal).toBe(controller.signal);
  });

  it("passes an optional wallet ID without accepting an address", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...inventory, offset: 24, next_offset: 25 }));
    await fetchMyInventory("session-token", { walletId: "wallet-id", limit: 24, offset: 24 });

    const parsed = new URL(String(vi.mocked(fetch).mock.calls[0][0]), "http://localhost");
    expect(parsed.searchParams.get("wallet_id")).toBe("wallet-id");
    expect(parsed.searchParams.has("owner_address")).toBe(false);
  });

  it("rejects a page returned for a different explicitly selected wallet", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({
      ...inventory,
      wallet_id: "primary-wallet-id",
    }));

    await expect(fetchMyInventory("session-token", {
      walletId: "connected-wallet-id",
      limit: 24,
      offset: 0,
    })).rejects.toThrow("inventory for a different wallet");
  });

  it("rejects inventory records that are not verified and eligible", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...inventory, items: [{ ...asset, eligible_for_listing: false }] }));
    await expect(fetchMyInventory("session-token")).rejects.toThrow("invalid inventory response");
  });

  it("rejects a pagination cursor that does not advance when more items exist", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...inventory, has_more: true, next_offset: 0 }));
    await expect(fetchMyInventory("session-token")).rejects.toThrow("invalid inventory response");
  });

  it("sends only the existing draft request fields with bearer auth", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(listing, 201));
    const payload = {
      asset_id: asset.id,
      price_amount: "1.25",
      price_currency: "TON" as const,
      title: "My NFT",
      description: "Optional details",
    };

    await expect(createListingDraft("session-token", payload)).resolves.toEqual(listing);

    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toMatch(/\/api\/listings$/);
    expect(options?.method).toBe("POST");
    expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer session-token");
    expect(JSON.parse(String(options?.body))).toEqual(payload);
  });

  it("rejects a response that is not a private draft", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...listing, status: "active" }, 201));
    await expect(createListingDraft("session-token", {
      asset_id: asset.id, price_amount: "1", price_currency: "TON",
    })).rejects.toThrow("invalid draft response");
  });
  it("requests a server-side full inventory sync and validates the result", async () => {
    const synced = {
      wallet_id: "wallet-id",
      synced_at: "2026-11-11T10:00:00Z",
      discovered_count: 28,
      verified_count: 27,
      stale_count: 1,
      invalid_count: 0,
      unsupported_count: 0,
      cancelled_listing_count: 1,
    };
    vi.mocked(fetch).mockResolvedValue(jsonResponse(synced));

    await expect(syncMyInventory("session-token", "wallet-id")).resolves.toEqual(synced);

    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toBe("/api/assets/me/sync?wallet_id=wallet-id");
    expect(options?.method).toBe("POST");
    expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer session-token");
  });

  it("rejects malformed inventory sync results", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({
      wallet_id: "wallet-id",
      synced_at: "not-a-date",
      discovered_count: -1,
      verified_count: 0,
    }));

    await expect(syncMyInventory("session-token")).rejects.toThrow("invalid inventory sync response");
  });

});
