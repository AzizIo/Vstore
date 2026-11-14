import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createEscrowApiClient,
  isEscrowDeal,
  isEscrowListing,
  isEscrowWithdrawal,
  type EscrowHttpContract,
  type PreparedEscrowTransaction,
} from "../../api/escrow";

function listing() {
  return {
    id: "listing-1",
    seller_id: "seller-1",
    state: "listed",
    network: "testnet",
    nft: {
      asset_id: "asset-1",
      title: "Test NFT",
      image_url: null,
      item_address: `0:${"1".repeat(64)}`,
      collection_address: null,
    },
    contract_address: `0:${"2".repeat(64)}`,
    seller_wallet_address: `0:${"3".repeat(64)}`,
    price_ton: "2.5",
    platform_fee_ton: "0.1",
    created_at: "2026-11-14T10:00:00Z",
    updated_at: "2026-11-14T10:00:00Z",
  };
}

function deal() {
  return {
    id: "deal-1",
    listing_id: "listing-1",
    buyer_id: "buyer-1",
    seller_id: "seller-1",
    state: "buyer_confirmation_window",
    network: "testnet",
    nft: listing().nft,
    contract_address: `0:${"2".repeat(64)}`,
    seller_wallet_address: `0:${"3".repeat(64)}`,
    buyer_wallet_address: `0:${"4".repeat(64)}`,
    price_ton: "2.5",
    platform_fee_ton: "0.1",
    seller_claimable_ton: null,
    buyer_confirmation_deadline: "2026-11-15T10:00:00Z",
    dispute_deadline: "2026-11-16T10:00:00Z",
    created_at: "2026-11-14T10:00:00Z",
    updated_at: "2026-11-14T10:00:00Z",
    dispute: null,
  };
}

function withdrawal() {
  return {
    id: "withdrawal-1",
    listing_id: null,
    deal_id: "deal-1",
    kind: "seller_proceeds",
    status: "observing",
    amount_ton: "2.4",
    destination_address: `0:${"3".repeat(64)}`,
    transaction_hash: null,
    created_at: "2026-11-14T10:00:00Z",
    updated_at: "2026-11-14T10:00:00Z",
  };
}

function prepared(action: PreparedEscrowTransaction["action"] = "purchase") {
  return {
    id: "operation-1",
    action,
    network: "testnet",
    contract_address: `0:${"2".repeat(64)}`,
    nft_item_address: `0:${"1".repeat(64)}`,
    amount_ton: "2.5",
    fee_ton: "0.1",
    network_fee_ton: "0.02",
    valid_until: "2099-01-01T00:00:00Z",
    display_summary: "Подготовить действие",
    messages: [{
      address: `0:${"2".repeat(64)}`,
      amount_nanotons: "2520000000",
      payload_boc: null,
      state_init_boc: null,
    }],
  };
}

function contract(): EscrowHttpContract {
  const operation = (url: string, body?: unknown) => ({ url, method: "POST" as const, body });
  return {
    marketplaceListings: () => "/test/escrow/listings",
    sellerListings: () => "/test/escrow/seller/listings",
    buyerDeals: () => "/test/escrow/buyer/deals",
    sellerDeals: () => "/test/escrow/seller/deals",
    sellerWithdrawals: () => "/test/escrow/seller/withdrawals",
    listingDetails: (id) => `/test/escrow/listings/${id}`,
    dealDetails: (id) => `/test/escrow/deals/${id}`,
    prepareNftDeposit: (input) => operation("/test/escrow/prepare-deposit", input),
    preparePurchase: (input) => operation("/test/escrow/prepare-purchase", input),
    prepareBuyerConfirmation: (input) => operation("/test/escrow/prepare-confirm", input),
    prepareDispute: (input) => operation("/test/escrow/prepare-dispute", input),
    prepareBuyerNftReturn: (input) => operation("/test/escrow/prepare-nft-return", input),
    prepareUnsoldNftWithdrawal: (input) => operation("/test/escrow/prepare-unsold-withdrawal", input),
    prepareSellerProceedsWithdrawal: (input) => operation("/test/escrow/prepare-payout", input),
    submitWalletReference: (input) => operation("/test/escrow/submit-reference", input),
  };
}

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("escrow API boundary", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("validates participant-scoped listings, deals and withdrawals", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ items: [listing()], total: 1, next_cursor: null }))
      .mockResolvedValueOnce(response({ items: [deal()], total: 1, next_cursor: null }))
      .mockResolvedValueOnce(response({ items: [withdrawal()], total: 1, next_cursor: null }));

    const api = createEscrowApiClient("access-token", contract());

    await expect(api.listMarketplaceListings()).resolves.toMatchObject({ total: 1 });
    await expect(api.listBuyerDeals()).resolves.toMatchObject({ items: [{ buyer_id: "buyer-1" }] });
    await expect(api.listSellerWithdrawals()).resolves.toMatchObject({ items: [{ status: "observing" }] });

    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/test/escrow/listings");
    expect((vi.mocked(fetch).mock.calls[0][1] as RequestInit).headers).toMatchObject({
      Authorization: "Bearer access-token",
    });
  });

  it("has separate seller-deal feed and buyer NFT-return preparation methods", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ items: [deal()], total: 1, next_cursor: null }))
      .mockResolvedValueOnce(response(prepared("buyer_nft_return")));

    const api = createEscrowApiClient("access-token", contract());
    await expect(api.listSellerDeals()).resolves.toMatchObject({ items: [{ seller_id: "seller-1" }] });
    await expect(api.prepareBuyerNftReturn({
      deal_id: "deal-1",
      buyer_wallet_id: "wallet-1",
    })).resolves.toMatchObject({ action: "buyer_nft_return" });

    expect(String(vi.mocked(fetch).mock.calls[1][0])).toBe("/test/escrow/prepare-nft-return");
  });

  it("uses the injected URL and payload rather than guessing API paths", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response(prepared()));
    const api = createEscrowApiClient("access-token", contract());

    await api.preparePurchase({ listing_id: "listing-1", buyer_wallet_id: "wallet-1" });

    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/test/escrow/prepare-purchase");
    expect(JSON.parse(String(init.body))).toEqual({
      listing_id: "listing-1",
      buyer_wallet_id: "wallet-1",
    });
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({
      Authorization: "Bearer access-token",
      "Content-Type": "application/json",
    });
  });

  it("rejects an empty session before any fetch", () => {
    expect(() => createEscrowApiClient("  ", contract())).toThrow(/авторизованной сессии/i);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects unrecognized states, mainnet data and malformed pages", async () => {
    expect(isEscrowListing({ ...listing(), state: "complete" })).toBe(false);
    expect(isEscrowListing({ ...listing(), network: "mainnet" })).toBe(false);
    expect(isEscrowListing({ ...listing(), price_ton: "NaN" })).toBe(false);
    expect(isEscrowListing({ ...listing(), price_ton: "0" })).toBe(false);
    expect(isEscrowListing({ ...listing(), platform_fee_ton: "-0.1" })).toBe(false);
    expect(isEscrowDeal({ ...deal(), seller_claimable_ton: "1e6" })).toBe(false);
    expect(isEscrowDeal({ ...deal(), state: "completed" })).toBe(false);
    expect(isEscrowWithdrawal({ ...withdrawal(), status: "paid" })).toBe(false);

    vi.mocked(fetch).mockResolvedValueOnce(response({
      items: [{ ...listing(), network: "mainnet" }],
      total: 1,
      next_cursor: null,
    }));
    await expect(createEscrowApiClient("access-token", contract()).listMarketplaceListings())
      .rejects.toThrow(/не соответствует ожидаемому контракту/i);
  });

  it("surfaces backend API errors and preserves AbortError", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ detail: "Escrow indexer unavailable" }, 503))
      .mockRejectedValueOnce(new DOMException("Aborted", "AbortError"));

    const api = createEscrowApiClient("access-token", contract());
    await expect(api.listMarketplaceListings()).rejects.toThrow("Escrow indexer unavailable");
    await expect(api.listMarketplaceListings()).rejects.toMatchObject({ name: "AbortError" });
  });
});
