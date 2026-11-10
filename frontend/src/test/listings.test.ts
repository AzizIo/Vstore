import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchListing,
  fetchListings,
  fetchMyListings,
  publishListing,
  updateListing,
  cancelListing,
  type Listing,
  type ListingPage,
} from "../api/listings";

const listing: Listing = {
  id: "listing-1",
  status: "active",
  title: "Moon Lantern",
  description: "A collectible lantern.",
  created_at: "2026-01-01T00:00:00Z",
  asset: {
    id: "asset-1",
    asset_type: "ton_nft",
    external_id: "nft-001",
    item_address: null,
    name: "Lantern",
    description: null,
    image_url: "https://example.com/lantern.jpg",
    verification_status: "verified",
  },
  seller: { id: "seller-1", username: "collector", first_name: "Ari" },
};

const page: ListingPage = { items: [listing], total: 1, limit: 24, offset: 0 };

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

describe("listing API client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests the catalog with supported filters and pagination", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(page));

    await expect(fetchListings({
      search: "  lantern  ",
      assetType: "telegram_gift",
    })).resolves.toEqual(page);

    const [url, options] = vi.mocked(fetch).mock.calls[0];
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe("/api/listings");
    expect(parsed.searchParams.get("limit")).toBe("24");
    expect(parsed.searchParams.get("offset")).toBe("0");
    expect(parsed.searchParams.get("search")).toBe("lantern");
    expect(parsed.searchParams.get("asset_type")).toBe("telegram_gift");
        expect(parsed.searchParams.has("currency")).toBe(false);
    expect(options?.signal).toBeUndefined();
  });

  it("omits blank search and the all-assets filter", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...page, items: [] }));

    await fetchListings({ search: "   ", assetType: "all" });

    const parsed = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(parsed.searchParams.has("search")).toBe(false);
    expect(parsed.searchParams.has("asset_type")).toBe(false);
  });

  it("passes the abort signal through to fetch", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(page));
    const controller = new AbortController();

    await fetchListings(
      { search: "", assetType: "all" },
      controller.signal,
    );

    expect(vi.mocked(fetch).mock.calls[0][1]?.signal).toBe(controller.signal);
  });

  it("requests an explicitly selected page limit and offset", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...page, limit: 3, offset: 3 }));

    await fetchListings({ search: "", assetType: "all", limit: 3, offset: 3 });

    const parsed = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(parsed.searchParams.get("limit")).toBe("3");
    expect(parsed.searchParams.get("offset")).toBe("3");
  });

  it("rejects a catalog with invalid pagination metadata", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...page, total: "1" }));

    await expect(fetchListings({
      search: "",
      assetType: "all",
    })).rejects.toThrow("invalid catalog response");
  });

  it("rejects pagination metadata that does not match the requested page", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...page, offset: 24 }));

    await expect(fetchListings({
      search: "",
      assetType: "all",
      limit: 24,
      offset: 48,
    })).rejects.toThrow("invalid catalog response");
  });

  it("rejects a catalog containing an invalid listing", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({
      ...page,
      items: [{ ...listing, seller: null }],
    }));

    await expect(fetchListings({
      search: "",
      assetType: "all",
    })).rejects.toThrow("invalid catalog response");
  });

  it("loads a detail by an encoded listing ID", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(listing));

    await expect(fetchListing("listing/one")).resolves.toEqual(listing);

    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain("/api/listings/listing%2Fone");
  });

  it("loads the current user's listings with the supplied Bearer token", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse([listing]));
    const controller = new AbortController();

    await expect(fetchMyListings("current-session-token", controller.signal)).resolves.toEqual([listing]);

    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(new URL(String(url)).pathname).toBe("/api/listings/me");
    expect(new URL(String(url)).search).toBe("");
    expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer current-session-token");
    expect(options?.signal).toBe(controller.signal);
  });

  it("rejects a private listings response containing an invalid item", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse([{ ...listing, asset: {} }]));

    await expect(fetchMyListings("current-session-token")).rejects.toThrow("invalid listings response");
  });

  it("rejects an invalid detail payload", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...listing, asset: {} }));

    await expect(fetchListing("listing-1")).rejects.toThrow("invalid listing");
  });

  it("surfaces a structured API error detail", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: "Listing not found" }, 404));

    await expect(fetchListing("missing")).rejects.toThrow("Listing not found");
  });

  it("falls back to the HTTP status when an error body is not JSON", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 503,
      json: vi.fn().mockRejectedValue(new Error("not JSON")),
    } as unknown as Response);

    await expect(fetchListing("listing-1")).rejects.toThrow("Request failed (503)");
  });

  it("normalizes connection failures", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Network unavailable"));

    await expect(fetchListing("listing-1")).rejects.toThrow("Could not connect to the marketplace");
  });

  it("reports malformed successful JSON", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockRejectedValue(new SyntaxError("Unexpected token")),
    } as unknown as Response);

    await expect(fetchListing("listing-1")).rejects.toThrow("invalid response");
  });

  it("publishes a listing with the seller session token", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...listing, status: "active" }));
    const controller = new AbortController();

    await expect(publishListing("listing/one", "seller-token", controller.signal))
      .resolves.toMatchObject({ id: listing.id, status: "active" });

    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(new URL(String(url)).pathname).toBe("/api/listings/listing%2Fone/publish");
    expect(options?.method).toBe("POST");
    expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer seller-token");
    expect(options?.signal).toBe(controller.signal);
    expect(options?.body).toBeUndefined();
  });

  it("updates only optional seller-provided details", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({
      ...listing,
      title: "Updated Lantern",
      description: null,
    }));

    await updateListing("listing-1", "seller-token", {
      title: "Updated Lantern",
      description: null,
    });

    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(new URL(String(url)).pathname).toBe("/api/listings/listing-1");
    expect(options?.method).toBe("PATCH");
    expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer seller-token");
    expect(new Headers(options?.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(options?.body))).toEqual({
      title: "Updated Lantern",
      description: null,
    });
    expect(String(options?.body)).not.toMatch(/status|seller_id|owner_id/);
  });

  it("cancels a listing through the seller-only cancel action", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...listing, status: "cancelled" }));

    await expect(cancelListing("listing-1", "seller-token"))
      .resolves.toMatchObject({ id: listing.id, status: "cancelled" });

    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(new URL(String(url)).pathname).toBe("/api/listings/listing-1/cancel");
    expect(options?.method).toBe("POST");
    expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer seller-token");
  });

  it("surfaces provider failures from the publish endpoint", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ detail: "TON NFT ownership provider is temporarily unavailable" }, 503),
    );

    await expect(publishListing("listing-1", "seller-token"))
      .rejects.toThrow("TON NFT ownership provider is temporarily unavailable");
  });

  it("rejects malformed seller mutation responses", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...listing, seller: null }));

    await expect(cancelListing("listing-1", "seller-token"))
      .rejects.toThrow("invalid listing response");
  });

});
