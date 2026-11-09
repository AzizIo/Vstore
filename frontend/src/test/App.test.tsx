import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";

const listing = {
  id: "listing-1",
  status: "active",
  price_amount: "12.5",
  price_currency: "TON" as const,
  title: "Moon Lantern",
  description: "A collectible lantern.",
  created_at: "2026-01-01T00:00:00Z",
  asset: {
    id: "asset-1", asset_type: "ton_nft" as const, external_id: "nft-001",
    item_address: null, name: "Lantern", description: null,
    image_url: "https://example.com/lantern.jpg", verification_status: "verified",
  },
  seller: { id: "seller-1", username: "collector", first_name: "Ari" },
};
const page = { items: [listing], total: 1, limit: 100, offset: 0 };

function jsonResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

describe("marketplace catalog", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(page))));

  it("shows a loading state while the catalog request is pending", () => {
    vi.mocked(fetch).mockReturnValue(new Promise(() => undefined));
    render(<App />);
    expect(screen.getByLabelText("Listings loading")).toHaveAttribute("aria-busy", "true");
  });

  it("renders listings returned by the public API", async () => {
    render(<App />);
    expect(await screen.findByText("Moon Lantern")).toBeInTheDocument();
    expect(screen.getByText("12.5 TON")).toBeInTheDocument();
    expect(screen.getByText("TON NFT", { selector: ".listing-card-type" })).toBeInTheDocument();
    expect(screen.getByText("1 item")).toBeInTheDocument();
  });

  it("shows an empty state when the API returns no listings", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...page, items: [], total: 0 }));
    render(<App />);
    expect(await screen.findByText("No listings found")).toBeInTheDocument();
  });

  it("shows an error when the API response does not match the listing contract", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({
      ...page,
      items: [{ ...listing, asset: {} }],
    }));
    render(<App />);
    expect(await screen.findByText("Catalog unavailable")).toBeInTheDocument();
    expect(screen.getByText("The marketplace returned an invalid catalog response.")).toBeInTheDocument();
  });

  it("shows an error and retries the catalog request", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("Offline")).mockResolvedValueOnce(jsonResponse(page));
    render(<App />);
    expect(await screen.findByText("Catalog unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Moon Lantern")).toBeInTheDocument();
  });

  it("sends search, asset type, and sort using supported query parameters", async () => {
    render(<App />);
    await screen.findByText("Moon Lantern");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search listings" }), { target: { value: "lantern" } });
    await waitFor(() => expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).toContain("search=lantern"));
    fireEvent.change(screen.getByRole("combobox", { name: "Asset type" }), { target: { value: "telegram_gift" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Sort listings" }), { target: { value: "price_desc" } });
    await waitFor(() => {
      const requestUrl = String(vi.mocked(fetch).mock.calls.at(-1)?.[0]);
      expect(requestUrl).toContain("asset_type=telegram_gift");
      expect(requestUrl).toContain("sort=price_desc");
    });
  });

  it("loads and displays the listing detail view", async () => {
    vi.mocked(fetch).mockImplementation(async (input) =>
      String(input).endsWith("/api/listings/listing-1") ? jsonResponse(listing) : jsonResponse(page),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Moon Lantern/ }));
    expect(await screen.findByRole("heading", { name: "Moon Lantern" })).toBeInTheDocument();
    expect(screen.getByText("A collectible lantern.")).toBeInTheDocument();
    expect(screen.getByText("nft-001")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Back to catalog/ }));
    await waitFor(() => expect(screen.getByText("Explore listings")).toBeInTheDocument());
  });
});
