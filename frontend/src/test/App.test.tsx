import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
const profile = {
  id: "user-1", telegram_id: 12345, username: "alex", first_name: "Alex",
  last_name: "Example", language_code: "en",
};
const authResponse = {
  access_token: "test-access-token", token_type: "bearer", expires_in: 3600,
  user: {
    id: profile.id, telegram_id: profile.telegram_id, username: profile.username,
    first_name: profile.first_name, last_name: profile.last_name
  },
};

function jsonResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

function renderMarketplace(queryClient = new QueryClient()) {
  return {
    queryClient,
    ...render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>),
  };
}

function setTelegramInitData(initData = "query_id=raw&hash=verified") {
  const ready = vi.fn();
  const expand = vi.fn();
  window.Telegram = { WebApp: { initData, ready, expand } };
  return { ready, expand };
}

function setSuccessfulTelegramAuth(profileResponse: Response = jsonResponse(profile)) {
  vi.mocked(fetch).mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/api/auth/telegram")) return jsonResponse(authResponse);
    if (url.endsWith("/api/users/me")) return profileResponse;
    return jsonResponse(page);
  });
}

describe("marketplace catalog", () => {
  beforeEach(() => {
    Reflect.deleteProperty(window, "Telegram");
    localStorage.clear();
    sessionStorage.clear();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(page)));
  });

  it("shows a loading state while the catalog request is pending", () => {
    vi.mocked(fetch).mockReturnValue(new Promise(() => undefined));
    renderMarketplace();
    expect(screen.getByLabelText("Listings loading")).toHaveAttribute("aria-busy", "true");
  });

  it("renders listings returned by the public API", async () => {
    renderMarketplace();
    expect(await screen.findByText("Moon Lantern")).toBeInTheDocument();
    expect(screen.getByText("12.5 TON")).toBeInTheDocument();
    expect(screen.getByText("TON NFT", { selector: ".listing-card-type" })).toBeInTheDocument();
    expect(screen.getByText("1 item")).toBeInTheDocument();
  });

  it("shows an empty state when the API returns no listings", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...page, items: [], total: 0 }));
    renderMarketplace();
    expect(await screen.findByText("No listings found")).toBeInTheDocument();
  });

  it("shows an error when the API response does not match the listing contract", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({
      ...page,
      items: [{ ...listing, asset: {} }],
    }));
    renderMarketplace();
    expect(await screen.findByText("Catalog unavailable")).toBeInTheDocument();
    expect(screen.getByText("The marketplace returned an invalid catalog response.")).toBeInTheDocument();
  });

  it("shows an error and retries the catalog request", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("Offline")).mockResolvedValueOnce(jsonResponse(page));
    renderMarketplace();
    expect(await screen.findByText("Catalog unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Moon Lantern")).toBeInTheDocument();
  });

  it("sends search, asset type, and sort using supported query parameters", async () => {
    renderMarketplace();
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
    renderMarketplace();
    fireEvent.click(await screen.findByRole("button", { name: /Moon Lantern/ }));
    expect(await screen.findByRole("heading", { name: "Moon Lantern" })).toBeInTheDocument();
    expect(screen.getByText("A collectible lantern.")).toBeInTheDocument();
    expect(screen.getByText("nft-001")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Back to catalog/ }));
    await waitFor(() => expect(screen.getByText("Explore listings")).toBeInTheDocument());
  });

  it("authenticates with raw Telegram initData, loads the Bearer profile, and keeps the token in memory", async () => {
    const telegram = setTelegramInitData("query_id=exact-raw-value&hash=abc123");
    setSuccessfulTelegramAuth();
    renderMarketplace();

    expect(await screen.findByText("Signed in as Alex Example · @alex")).toBeInTheDocument();
    expect(telegram.ready).toHaveBeenCalledOnce();
    expect(telegram.expand).toHaveBeenCalledOnce();
    const authCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith("/api/auth/telegram"));
    expect(JSON.parse(String(authCall?.[1]?.body))).toEqual({ init_data: "query_id=exact-raw-value&hash=abc123" });
    const profileCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith("/api/users/me"));
    expect(new Headers(profileCall?.[1]?.headers).get("Authorization")).toBe("Bearer test-access-token");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("does not authenticate without initData and keeps the public catalog available", async () => {
    renderMarketplace();

    expect(await screen.findByText(/Open this mini app in Telegram to sign in/)).toBeInTheDocument();
    expect(await screen.findByText("Moon Lantern")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith("/api/auth/telegram"))).toBe(false);
  });

  it("treats a 401 from Telegram auth as an unauthenticated session", async () => {
    setTelegramInitData();
    vi.mocked(fetch).mockImplementation(async (input) => {
      if (String(input).endsWith("/api/auth/telegram")) return jsonResponse({ detail: "Invalid initData" }, 401);
      return jsonResponse(page);
    });
    renderMarketplace();

    expect(await screen.findByText(/Telegram session could not be verified/)).toBeInTheDocument();
    expect(await screen.findByText("Moon Lantern")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith("/api/users/me"))).toBe(false);
  });

  it("shows a restricted-account message on 403 without blocking the catalog", async () => {
    setTelegramInitData();
    vi.mocked(fetch).mockImplementation(async (input) => {
      if (String(input).endsWith("/api/auth/telegram")) return jsonResponse({ detail: "This account is restricted" }, 403);
      return jsonResponse(page);
    });
    renderMarketplace();

    expect(await screen.findByRole("alert")).toHaveTextContent("This account is restricted");
    expect(await screen.findByText("Moon Lantern")).toBeInTheDocument();
  });

  it("clears the session and private query cache when the protected profile returns 401", async () => {
    setTelegramInitData();
    setSuccessfulTelegramAuth(jsonResponse({ detail: "Expired token" }, 401));
    const queryClient = new QueryClient();
    await queryClient.fetchQuery({ queryKey: ["private-profile"], queryFn: async () => "private", meta: { private: true } });
    await queryClient.fetchQuery({ queryKey: ["public-preview"], queryFn: async () => "public" });
    renderMarketplace(queryClient);

    expect(await screen.findByText(/Telegram session could not be verified/)).toBeInTheDocument();
    await waitFor(() => expect(queryClient.getQueryData(["private-profile"])).toBeUndefined());
    expect(queryClient.getQueryData(["public-preview"])).toBe("public");
    expect(await screen.findByText("Moon Lantern")).toBeInTheDocument();
  });
});
