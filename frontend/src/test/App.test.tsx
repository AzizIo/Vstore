import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { App } from "../App";

const tonConnectMocks = vi.hoisted(() => ({
  wallet: null as {
    account: { address: string; chain: string; publicKey?: string; walletStateInit?: string };
    connectItems?: {
      tonProof?: {
        proof: {
          timestamp: number;
          domain: { lengthBytes: number; value: string };
          signature: string;
          payload: string;
        };
      } | { error: number; message: string };
    };
  } | null,
  openModal: vi.fn(),
  disconnect: vi.fn(),
  setConnectRequestParameters: vi.fn(),
}));

vi.mock("@tonconnect/ui-react", () => ({
  CHAIN: { MAINNET: "-239", TESTNET: "-3" },
  TonConnectUIProvider: ({ children, manifestUrl }: { children: ReactNode; manifestUrl: string }) => (
    <div data-testid="tonconnect-provider" data-manifest-url={manifestUrl}>{children}</div>
  ),
  useTonWallet: () => tonConnectMocks.wallet,
  useTonConnectUI: () => [{
    openModal: tonConnectMocks.openModal,
    disconnect: tonConnectMocks.disconnect,
    setConnectRequestParameters: tonConnectMocks.setConnectRequestParameters,
  }, vi.fn()],
}));

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
    item_address: "0:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    name: "Lantern", description: null,
    image_url: "https://example.com/lantern.jpg", verification_status: "verified",
    collection: {
      id: "collection-1", address: "0:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      network: "mainnet", name: "Lantern Guild", marketplace_name: "Getgems",
    },
  },
  seller: { id: "seller-1", username: "collector", first_name: "Ari" },
};
const page = { items: [listing], total: 1, limit: 24, offset: 0 };
const ownListings = [
  { ...listing, id: "mine-draft", status: "draft", title: "My draft lantern" },
  { ...listing, id: "mine-active", status: "active", title: "My active lantern" },
];
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

function makeListings(count: number, prefix: string) {
  return Array.from({ length: count }, (_, index) => ({
    ...listing,
    id: `${prefix}-${index + 1}`,
    title: `${prefix} listing ${index + 1}`,
  }));
}

function renderMarketplace(queryClient = new QueryClient()) {
  return {
    queryClient,
    ...render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>),
  };
}

function setTelegramInitData(initData = "query_id=raw&hash=verified", startParam?: string) {
  const ready = vi.fn();
  const expand = vi.fn();
  window.Telegram = { WebApp: { initData, initDataUnsafe: startParam ? { start_param: startParam } : undefined, ready, expand } };
  return { ready, expand };
}

function setSuccessfulTelegramAuth(profileResponse: Response = jsonResponse(profile)) {
  vi.mocked(fetch).mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/api/auth/telegram")) return jsonResponse(authResponse);
    if (url.endsWith("/api/users/me")) return profileResponse;
    if (url.endsWith("/api/wallets/me")) return jsonResponse([]);
    if (url.endsWith("/api/wallets/proof/challenge")) {
      return jsonResponse({ payload: "fresh-wallet-proof-nonce", expires_at: "2026-11-10T18:00:00Z" });
    }
    return jsonResponse(page);
  });
}

function setAuthenticatedListingsResponse(response: Response | unknown = jsonResponse(ownListings)) {
  vi.mocked(fetch).mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/api/auth/telegram")) return jsonResponse(authResponse);
    if (url.endsWith("/api/users/me")) return jsonResponse(profile);
    if (url.endsWith("/api/listings/me")) {
      return response && typeof response === "object" && "ok" in response && "json" in response
        ? response as Response
        : jsonResponse(response);
    }
    return jsonResponse(page);
  });
}

describe("marketplace catalog", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    tonConnectMocks.wallet = null;
    tonConnectMocks.openModal.mockReset();
    tonConnectMocks.disconnect.mockReset();
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

  it("loads successive server pages, removes duplicate IDs, and hides Load more at total", async () => {
    const firstPage = makeListings(24, "first");
    const finalListing = { ...listing, id: "last-listing", title: "Last server listing" };
    vi.mocked(fetch).mockImplementation(async (input) => {
      const requestUrl = new URL(String(input));
      const offset = Number(requestUrl.searchParams.get("offset"));
      if (offset === 0) return jsonResponse({ items: firstPage, total: 25, limit: 24, offset: 0 });
      return jsonResponse({ items: [firstPage[0], finalListing], total: 25, limit: 24, offset: 24 });
    });
    renderMarketplace();

    expect(await screen.findByText("first listing 24")).toBeInTheDocument();
    expect(screen.getByText("Showing 24 of 25")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Last server listing")).toBeInTheDocument();
    expect(screen.getAllByText("first listing 1")).toHaveLength(1);
    expect(screen.getByText("25 items")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    const pageRequests = vi.mocked(fetch).mock.calls.map(([input]) => new URL(String(input)));
    expect(pageRequests.map((url) => url.searchParams.get("offset"))).toEqual(["0", "24"]);
  });

  it("resets catalog results and offset to zero when search, type, or sort changes", async () => {
    const initialListings = makeListings(24, "initial");
    const filteredListing = { ...listing, id: "filtered", title: "Filtered result" };
    vi.mocked(fetch).mockImplementation(async (input) => {
      const requestUrl = new URL(String(input));
      if (requestUrl.searchParams.has("search") || requestUrl.searchParams.has("asset_type") || requestUrl.searchParams.get("sort") !== "newest") {
        return jsonResponse({ items: [filteredListing], total: 1, limit: 24, offset: 0 });
      }
      if (requestUrl.searchParams.get("offset") === "24") {
        return jsonResponse({ items: makeListings(24, "next-page"), total: 48, limit: 24, offset: 24 });
      }
      return jsonResponse({ items: initialListings, total: 48, limit: 24, offset: Number(requestUrl.searchParams.get("offset")) });
    });
    renderMarketplace();

    expect(await screen.findByText("initial listing 24")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("next-page listing 1")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search listings" }), { target: { value: "rare" } });
    expect(await screen.findByText("Filtered result")).toBeInTheDocument();
    expect(new URL(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).searchParams.get("offset")).toBe("0");

    fireEvent.change(screen.getByRole("combobox", { name: "Asset type" }), { target: { value: "telegram_gift" } });
    await waitFor(() => expect(new URL(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).searchParams.get("offset")).toBe("0"));
    fireEvent.change(screen.getByRole("combobox", { name: "Sort listings" }), { target: { value: "price_desc" } });
    await waitFor(() => expect(new URL(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).searchParams.get("offset")).toBe("0"));

    expect(screen.getByText("Filtered result")).toBeInTheDocument();
    expect(screen.queryByText("initial listing 1")).not.toBeInTheDocument();
  });

  it("retries a failed next-page request without discarding loaded listings", async () => {
    const initialListings = makeListings(24, "loaded");
    let nextPageRequests = 0;
    vi.mocked(fetch).mockImplementation(async (input) => {
      const requestUrl = new URL(String(input));
      if (requestUrl.searchParams.get("offset") === "0") {
        return jsonResponse({ items: initialListings, total: 25, limit: 24, offset: 0 });
      }
      nextPageRequests += 1;
      return nextPageRequests === 1
        ? jsonResponse({ detail: "Temporary failure" }, 503)
        : jsonResponse({ items: [{ ...listing, id: "retry-result", title: "Loaded after retry" }], total: 25, limit: 24, offset: 24 });
    });
    renderMarketplace();

    expect(await screen.findByText("loaded listing 24")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Temporary failure")).toBeInTheDocument();
    expect(screen.getByText("loaded listing 1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry loading more" }));

    expect(await screen.findByText("Loaded after retry")).toBeInTheDocument();
    expect(nextPageRequests).toBe(2);
  });

  it("prevents duplicate in-flight page requests", async () => {
    const initialListings = makeListings(24, "loaded");
    let resolveNextPage: ((response: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation(async (input) => {
      const requestUrl = new URL(String(input));
      if (requestUrl.searchParams.get("offset") === "0") {
        return jsonResponse({ items: initialListings, total: 25, limit: 24, offset: 0 });
      }
      return new Promise<Response>((resolve) => { resolveNextPage = resolve; });
    });
    renderMarketplace();

    await screen.findByText("loaded listing 24");
    const loadMore = screen.getByRole("button", { name: "Load more" });
    fireEvent.click(loadMore);
    fireEvent.click(loadMore);

    expect(vi.mocked(fetch).mock.calls.filter(([input]) => new URL(String(input)).searchParams.get("offset") === "24")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Loading more..." })).toBeDisabled();
    resolveNextPage?.(jsonResponse({ items: [{ ...listing, id: "last", title: "Last listing" }], total: 25, limit: 24, offset: 24 }));
    expect(await screen.findByText("Last listing")).toBeInTheDocument();
  });

  it("aborts an in-flight next-page request on unmount", async () => {
    const initialListings = makeListings(24, "loaded");
    let pageSignal: AbortSignal | undefined;
    vi.mocked(fetch).mockImplementation(async (input, options) => {
      const requestUrl = new URL(String(input));
      if (requestUrl.searchParams.get("offset") === "0") {
        return jsonResponse({ items: initialListings, total: 25, limit: 24, offset: 0 });
      }
      pageSignal = options?.signal ?? undefined;
      return new Promise<Response>(() => undefined);
    });
    const { unmount } = renderMarketplace();

    await screen.findByText("loaded listing 24");
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    unmount();

    expect(pageSignal?.aborted).toBe(true);
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

  it("shows the seller profile name and Telegram handle on listing detail", async () => {
    vi.mocked(fetch).mockImplementation(async (input) =>
      String(input).endsWith("/api/listings/listing-1") ? jsonResponse(listing) : jsonResponse(page),
    );
    renderMarketplace();
    fireEvent.click(await screen.findByRole("button", { name: /Moon Lantern/ }));

    const sellerProfile = await screen.findByRole("region", { name: "Seller profile" });
    expect(sellerProfile).toHaveTextContent("Ari");
    expect(sellerProfile).toHaveTextContent("@collector");
  });

  it("shows the collection and item address on the listing detail view", async () => {
    vi.mocked(fetch).mockImplementation(async (input) =>
      String(input).endsWith("/api/listings/listing-1") ? jsonResponse(listing) : jsonResponse(page),
    );
    renderMarketplace();
    fireEvent.click(await screen.findByRole("button", { name: /Moon Lantern/ }));
    expect(await screen.findByRole("heading", { name: "Moon Lantern" })).toBeInTheDocument();

    expect(screen.getByText("Lantern Guild")).toBeInTheDocument();
    expect(
      screen.getByText("0:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
    ).toBeInTheDocument();
    expect(screen.getByText("verified")).toBeInTheDocument();
  });

  it("shows an uncollected label when the asset has no collection", async () => {
    const uncollected = {
      ...listing,
      asset: { ...listing.asset, collection: null, item_address: null },
    };
    vi.mocked(fetch).mockImplementation(async (input) =>
      String(input).endsWith("/api/listings/listing-1")
        ? jsonResponse(uncollected)
        : jsonResponse(page),
    );
    renderMarketplace();
    fireEvent.click(await screen.findByRole("button", { name: /Moon Lantern/ }));

    expect(await screen.findByText("Uncollected NFT")).toBeInTheDocument();
    expect(screen.getByText("Not available")).toBeInTheDocument();
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

describe("Buyer orders", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    tonConnectMocks.wallet = null;
    Reflect.deleteProperty(window, "Telegram");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(page)));
  });



  it("opens the exact order from a Telegram startapp deep link", async () => {
    const orderId = "123e4567-e89b-12d3-a456-426614174000";
    const order = {
      id: orderId,
      listing_id: listing.id,
      buyer_id: profile.id,
      seller_id: listing.seller.id,
      status: "pending_payment",
      price_amount: "12.5",
      price_currency: "TON",
      title: listing.title,
      asset_name: listing.asset.name,
      asset_type: listing.asset.asset_type,
      expires_at: "2026-01-01T00:15:00Z",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      events: [{ from_status: null, to_status: "pending_payment", actor_type: "buyer", created_at: "2026-01-01T00:00:00Z" }],
    };
    setTelegramInitData("query_id=raw&hash=verified", `order_${orderId.replace(/-/g, "")}`);
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/auth/telegram")) return jsonResponse(authResponse);
      if (url.endsWith("/api/users/me")) return jsonResponse(profile);
      if (url.endsWith(`/api/orders/${orderId}`)) return jsonResponse(order);
      if (url.includes("/api/orders?")) return jsonResponse({ items: [order] });
      return jsonResponse(page);
    });

    renderMarketplace();

    expect(await screen.findByText("OPENED FROM TELEGRAM NOTIFICATION")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Orders" })).toHaveAttribute("aria-pressed", "true");
    expect(vi.mocked(fetch).mock.calls.some(([input]) =>
      String(input).endsWith(`/api/orders/${orderId}`)
    )).toBe(true);
  });

  it("creates an authenticated order from listing detail and displays its status", async () => {
    setTelegramInitData();
    const pendingOrder = {
      id: "order-1", listing_id: listing.id, buyer_id: profile.id, seller_id: listing.seller.id,
      status: "pending_payment", price_amount: "12.5", price_currency: "TON",
      title: listing.title, asset_name: listing.asset.name, asset_type: listing.asset.asset_type,
      expires_at: "2026-01-01T00:15:00Z", created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      events: [{ from_status: null, to_status: "pending_payment", actor_type: "buyer", created_at: "2026-01-01T00:00:00Z" }],
    };
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/auth/telegram")) return jsonResponse(authResponse);
      if (url.endsWith("/api/users/me")) return jsonResponse(profile);
      if (url.endsWith(`/api/listings/${listing.id}`)) return jsonResponse(listing);
      if (url.endsWith("/api/orders") && init?.method === "POST") return jsonResponse(pendingOrder, 201);
      if (url.includes("/api/orders?")) return jsonResponse({ items: [pendingOrder] });
      return jsonResponse(page);
    });
    renderMarketplace();
    fireEvent.click(await screen.findByRole("button", { name: /Moon Lantern/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Place order" }));

    expect(await screen.findByText(/Order created\. Payment is not enabled/)).toBeInTheDocument();
    const orderRequest = vi.mocked(fetch).mock.calls.find(([input, init]) =>
      String(input).endsWith("/api/orders") && init?.method === "POST"
    );
    expect(orderRequest).toBeDefined();
    expect(JSON.parse(String(orderRequest?.[1]?.body))).toEqual({ listing_id: listing.id });
    expect(new Headers(orderRequest?.[1]?.headers).get("Idempotency-Key")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Orders" }));
    expect(await screen.findByText("Payment pending")).toBeInTheDocument();
  });
});

describe("TON Connect wallet UI", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    tonConnectMocks.wallet = null;
    tonConnectMocks.openModal.mockReset();
    tonConnectMocks.disconnect.mockReset();
    tonConnectMocks.setConnectRequestParameters.mockReset();
    setTelegramInitData();
    setSuccessfulTelegramAuth(jsonResponse(profile));
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/auth/telegram")) return jsonResponse(authResponse);
      if (url.endsWith("/api/users/me")) return jsonResponse(profile);
      if (url.endsWith("/api/wallets/me")) return jsonResponse([]);
      if (url.endsWith("/api/wallets/proof/challenge")) {
        return jsonResponse({ payload: "fresh-wallet-proof-nonce", expires_at: "2026-11-10T18:00:00Z" });
      }
      return jsonResponse({ items: [], total: 0, limit: 24, offset: 0 });
    });
  });

  it("shows a connect action when manifest configuration is available", async () => {
    vi.stubEnv("VITE_TONCONNECT_MANIFEST_URL", "https://wallet.example/manifest.json");
    renderMarketplace();

    expect(await screen.findByRole("button", { name: "Connect & verify" })).toBeInTheDocument();
    expect(screen.getByTestId("tonconnect-provider")).toHaveAttribute(
      "data-manifest-url",
      "https://wallet.example/manifest.json",
    );
    fireEvent.click(screen.getByRole("button", { name: "Connect & verify" }));
    await waitFor(() => expect(tonConnectMocks.openModal).toHaveBeenCalledOnce());
    expect(tonConnectMocks.setConnectRequestParameters).toHaveBeenCalledWith({
      state: "ready",
      value: { tonProof: "fresh-wallet-proof-nonce" },
    });
  });

  it("shows the abbreviated wallet address and mainnet after connection", async () => {
    vi.stubEnv("VITE_TONCONNECT_MANIFEST_URL", "https://wallet.example/manifest.json");
    tonConnectMocks.wallet = { account: { address: "0:abcdef1234567890", chain: "-239" } };
    renderMarketplace();

    expect(await screen.findByText("0:abcd…7890")).toBeInTheDocument();
    expect(screen.getByText("Mainnet")).toBeInTheDocument();
    expect(screen.getByText("Connected only · proof verification required")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeInTheDocument();
    expect(screen.queryByText(/verified/i)).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) =>
      String(input).endsWith("/api/wallets/proof/verify"),
    )).toBe(false);
  });

  it("marks a wallet verified only after the backend accepts its fresh proof", async () => {
    vi.stubEnv("VITE_TONCONNECT_MANIFEST_URL", "https://wallet.example/tonconnect-manifest.json");
    const view = renderMarketplace();
    fireEvent.click(await screen.findByRole("button", { name: "Connect & verify" }));
    await waitFor(() => expect(tonConnectMocks.openModal).toHaveBeenCalledOnce());

    const address = `0:${"a".repeat(64)}`;
    const linkedWallet = {
      id: "wallet-verified",
      address,
      network: "mainnet",
      is_verified: true,
      is_primary: false,
    };
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/wallets/proof/verify")) return jsonResponse(linkedWallet);
      if (url.endsWith("/api/wallets/me")) return jsonResponse([]);
      if (url.endsWith("/api/wallets/proof/challenge")) {
        return jsonResponse({ payload: "fresh-wallet-proof-nonce", expires_at: "2099-01-01T00:00:00Z" });
      }
      if (url.endsWith("/api/auth/telegram")) return jsonResponse(authResponse);
      if (url.endsWith("/api/users/me")) return jsonResponse(profile);
      return jsonResponse({ items: [], total: 0, limit: 24, offset: 0 });
    });
    tonConnectMocks.wallet = {
      account: { address, chain: "-239", walletStateInit: "state-init-boc" },
      connectItems: {
        tonProof: {
          proof: {
            timestamp: 1_900_000_000,
            domain: { lengthBytes: 15, value: "app.example.com" },
            signature: "base64-signature",
            payload: "fresh-wallet-proof-nonce",
          },
        },
      },
    };
    view.rerender(<QueryClientProvider client={view.queryClient}><App /></QueryClientProvider>);

    expect(await screen.findByText("Wallet verified by VILTARA")).toBeInTheDocument();
    const verificationCall = vi.mocked(fetch).mock.calls.find(([input]) =>
      String(input).endsWith("/api/wallets/proof/verify"),
    );
    expect(verificationCall).toBeDefined();
    const body = JSON.parse(String(verificationCall?.[1]?.body));
    expect(body.proof.payload).toBe("fresh-wallet-proof-nonce");
    expect(body.network).toBe("-239");
    expect(body.address).toBe(address);
    expect(body.proof.state_init).toBe("state-init-boc");
  });

  it("keeps a connected wallet unverified when backend proof verification fails", async () => {
    vi.stubEnv("VITE_TONCONNECT_MANIFEST_URL", "https://wallet.example/tonconnect-manifest.json");
    const view = renderMarketplace();
    fireEvent.click(await screen.findByRole("button", { name: "Connect & verify" }));
    await waitFor(() => expect(tonConnectMocks.openModal).toHaveBeenCalledOnce());

    const address = `0:${"b".repeat(64)}`;
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/wallets/proof/verify")) {
        return jsonResponse({ detail: "Invalid or expired wallet proof" }, 401);
      }
      if (url.endsWith("/api/wallets/me")) return jsonResponse([]);
      if (url.endsWith("/api/wallets/proof/challenge")) {
        return jsonResponse({ payload: "fresh-wallet-proof-nonce", expires_at: "2099-01-01T00:00:00Z" });
      }
      if (url.endsWith("/api/auth/telegram")) return jsonResponse(authResponse);
      if (url.endsWith("/api/users/me")) return jsonResponse(profile);
      return jsonResponse({ items: [], total: 0, limit: 24, offset: 0 });
    });
    tonConnectMocks.wallet = {
      account: { address, chain: "-239", walletStateInit: "state-init-boc" },
      connectItems: {
        tonProof: {
          proof: {
            timestamp: 1_900_000_000,
            domain: { lengthBytes: 15, value: "app.example.com" },
            signature: "base64-signature",
            payload: "fresh-wallet-proof-nonce",
          },
        },
      },
    };
    view.rerender(<QueryClientProvider client={view.queryClient}><App /></QueryClientProvider>);

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid or expired wallet proof");
    expect(screen.queryByText("Wallet verified by VILTARA")).not.toBeInTheDocument();
  });

  it("shows testnet when reported by the connected wallet", async () => {
    vi.stubEnv("VITE_TONCONNECT_MANIFEST_URL", "https://wallet.example/manifest.json");
    tonConnectMocks.wallet = { account: { address: "0:abcdef1234567890", chain: "-3" } };
    renderMarketplace();

    expect(await screen.findByText("Testnet")).toBeInTheDocument();
  });

  it("calls the SDK disconnect method", async () => {
    vi.stubEnv("VITE_TONCONNECT_MANIFEST_URL", "https://wallet.example/manifest.json");
    tonConnectMocks.wallet = { account: { address: "0:abcdef1234567890", chain: "-239" } };
    tonConnectMocks.disconnect.mockResolvedValue(undefined);
    renderMarketplace();

    fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(tonConnectMocks.disconnect).toHaveBeenCalledOnce());
  });

  it("explains that wallet connection is unavailable without manifest configuration", async () => {
    vi.stubEnv("VITE_TONCONNECT_MANIFEST_URL", "");
    renderMarketplace();

    expect(await screen.findByText("Wallet connection is not configured.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect & verify" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("tonconnect-provider")).not.toBeInTheDocument();
  });
});

describe("My Listings dashboard", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    tonConnectMocks.wallet = null;
    Reflect.deleteProperty(window, "Telegram");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(page)));
  });

  async function openMyListings() {
    fireEvent.click(screen.getByRole("button", { name: "My Listings" }));
  }

  it("requires Telegram authentication and does not request private listings when unauthenticated", async () => {
    renderMarketplace();
    await openMyListings();

    expect(await screen.findByText("Open VILTARA in Telegram")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith("/api/listings/me"))).toBe(false);
  });

  it("does not request private listings while the Telegram session is loading", async () => {
    setTelegramInitData();
    vi.mocked(fetch).mockImplementation((input) => {
      if (String(input).endsWith("/api/auth/telegram")) return new Promise(() => undefined);
      return Promise.resolve(jsonResponse(page));
    });
    renderMarketplace();
    await openMyListings();

    expect(screen.getByText("Waiting for Telegram session verification...")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith("/api/listings/me"))).toBe(false);
  });

  it("does not request private listings when Telegram authentication fails", async () => {
    setTelegramInitData();
    vi.mocked(fetch).mockImplementation(async (input) => {
      if (String(input).endsWith("/api/auth/telegram")) return jsonResponse({ detail: "Unavailable" }, 503);
      return jsonResponse(page);
    });
    renderMarketplace();
    await openMyListings();

    expect(await screen.findByText("Session unavailable")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith("/api/listings/me"))).toBe(false);
  });

  it("loads only the current-user endpoint with the access token from session", async () => {
    setTelegramInitData();
    setAuthenticatedListingsResponse();
    renderMarketplace();
    expect(await screen.findByText("Signed in as Alex Example · @alex")).toBeInTheDocument();
    await openMyListings();

    expect(await screen.findByText("My draft lantern")).toBeInTheDocument();
    const privateCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith("/api/listings/me"));
    expect(String(privateCall?.[0])).toMatch(/\/api\/listings\/me$/);
    expect(new Headers(privateCall?.[1]?.headers).get("Authorization")).toBe("Bearer test-access-token");
    expect(vi.mocked(fetch).mock.calls.some(([input]) => {
      const path = new URL(String(input), "http://localhost").pathname;
      return path.startsWith("/api/listings/") && path !== "/api/listings/me";
    })).toBe(false);
  });

  it("shows an empty state for an account with no listings", async () => {
    setTelegramInitData();
    setAuthenticatedListingsResponse([]);
    renderMarketplace();
    await openMyListings();

    expect(await screen.findByText("No listings yet")).toBeInTheDocument();
  });

  it("renders all known statuses and a safe fallback for unknown status", async () => {
    const statusListings = [
      ...["draft", "active", "reserved", "sold", "cancelled", "expired"].map((status) => ({
        ...listing, id: `status-${status}`, status, title: `Listing ${status}`,
      })),
      { ...listing, id: "status-new", status: "unexpected", title: "Listing unknown" },
    ];
    setTelegramInitData();
    setAuthenticatedListingsResponse(statusListings);
    renderMarketplace();
    await openMyListings();

    for (const label of ["Draft", "Active", "Reserved", "Sold", "Cancelled", "Expired", "Unknown status"]) {
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
  });

  it("filters listings by status on the client", async () => {
    setTelegramInitData();
    setAuthenticatedListingsResponse();
    renderMarketplace();
    await openMyListings();
    await screen.findByText("My active lantern");

    fireEvent.change(screen.getByRole("combobox", { name: "Filter my listings by status" }), {
      target: { value: "draft" },
    });

    expect(screen.getByText("My draft lantern")).toBeInTheDocument();
    expect(screen.queryByText("My active lantern")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 1")).toBeInTheDocument();
  });

  it.each([
    [401, "Expired session"],
    [403, "Access denied"],
  ])("shows API %s errors and retries without leaving My Listings", async (status, detail) => {
    setTelegramInitData();
    let privateRequests = 0;
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/auth/telegram")) return jsonResponse(authResponse);
      if (url.endsWith("/api/users/me")) return jsonResponse(profile);
      if (url.endsWith("/api/listings/me")) {
        privateRequests += 1;
        return privateRequests === 1
          ? jsonResponse({ detail }, status)
          : jsonResponse(ownListings);
      }
      return jsonResponse(page);
    });
    renderMarketplace();
    await openMyListings();

    expect(await screen.findByText(detail)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("My draft lantern")).toBeInTheDocument();
  });

  it("handles network errors with retry", async () => {
    setTelegramInitData();
    let privateRequests = 0;
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/auth/telegram")) return jsonResponse(authResponse);
      if (url.endsWith("/api/users/me")) return jsonResponse(profile);
      if (url.endsWith("/api/listings/me")) {
        privateRequests += 1;
        if (privateRequests === 1) throw new Error("offline");
        return jsonResponse(ownListings);
      }
      return jsonResponse(page);
    });
    renderMarketplace();
    await openMyListings();

    expect(await screen.findByText(/Could not connect to the marketplace/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("My draft lantern")).toBeInTheDocument();
  });

  it("rejects runtime-invalid private listing responses", async () => {
    setTelegramInitData();
    setAuthenticatedListingsResponse([{ ...listing, asset: {} }]);
    renderMarketplace();
    await openMyListings();

    expect(await screen.findByText("The marketplace returned an invalid listings response.")).toBeInTheDocument();
  });

  it("opens a draft from its private response without calling the public detail endpoint", async () => {
    setTelegramInitData();
    setAuthenticatedListingsResponse();
    renderMarketplace();
    await openMyListings();
    fireEvent.click(await screen.findByRole("button", { name: /My draft lantern/ }));

    expect(await screen.findByRole("heading", { name: "My draft lantern" })).toBeInTheDocument();
    expect(screen.getByText("Back to my listings")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) => {
      const path = new URL(String(input), "http://localhost").pathname;
      return path.startsWith("/api/listings/") && path !== "/api/listings/me";
    })).toBe(false);
  });

  it("returns from a private listing detail to the public catalog through navigation", async () => {
    setTelegramInitData();
    setAuthenticatedListingsResponse();
    renderMarketplace();
    await openMyListings();
    fireEvent.click(await screen.findByRole("button", { name: /My draft lantern/ }));
    await screen.findByRole("heading", { name: "My draft lantern" });

    fireEvent.click(screen.getByRole("button", { name: "Catalog" }));

    expect(await screen.findByText("Explore listings")).toBeInTheDocument();
  });
});
