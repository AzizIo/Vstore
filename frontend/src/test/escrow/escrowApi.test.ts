import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createEscrowApiClient,
  isEscrowDeal,
  isEscrowListingIntent,
  isEscrowWithdrawal,
  type EscrowDeal,
  type EscrowHttpContract,
  type EscrowListingIntent,
  type EscrowWithdrawal,
  type PreparedEscrowTransaction,
} from "../../api/escrow";

const item = "0:" + "1".repeat(64);
const escrow = "0:" + "2".repeat(64);
const factory = "0:" + "3".repeat(64);

function listing(): EscrowListingIntent {
  return {
    id: "listing-1",
    listing_key: "listing-key-1",
    seller_id: "seller-1",
    state: "intent_only",
    network: "testnet",
    nft: {
      asset_id: "asset-1",
      title: "Test NFT",
      image_url: null,
      item_address: item,
      collection_address: null,
    },
    seller_wallet_address: "0:" + "4".repeat(64),
    price_nano: "2500000000",
    fee_bps: 0,
    available_actions: ["create_deal_intent"],
    created_at: "2026-11-14T10:00:00Z",
    updated_at: "2026-11-14T10:00:00Z",
  };
}

function deal(overrides: Partial<EscrowDeal> = {}): EscrowDeal {
  return {
    id: "deal-1",
    listing_id: "listing-1",
    listing_key: "listing-key-1",
    buyer_id: "buyer-1",
    seller_id: "seller-1",
    state: "funded_review",
    network: "testnet",
    nft: listing().nft,
    escrow_address: escrow,
    seller_wallet_address: "0:" + "4".repeat(64),
    buyer_wallet_address: "0:" + "5".repeat(64),
    price_nano: "2500000000",
    fee_bps: 0,
    buyer_review_deadline: "2026-11-15T10:00:00Z",
    dispute_deadline: "2026-11-16T10:00:00Z",
    available_actions: ["accept_deal", "open_dispute"],
    created_at: "2026-11-14T10:00:00Z",
    updated_at: "2026-11-14T10:00:00Z",
    dispute: null,
    ...overrides,
  };
}

function withdrawal(): EscrowWithdrawal {
  return {
    id: "withdrawal-1",
    deal_id: "deal-1",
    kind: "unsold_nft",
    status: "observing",
    destination_address: "0:" + "4".repeat(64),
    transaction_hash: null,
    created_at: "2026-11-14T10:00:00Z",
    updated_at: "2026-11-14T10:00:00Z",
  };
}

function prepared(action: PreparedEscrowTransaction["action"] = "fund_deal") {
  const isFactoryAction = action === "create_deal_escrow";
  const destination = isFactoryAction ? factory
    : action === "deposit_nft" || action === "return_nft_to_escrow" ? item
      : escrow;
  return {
    action_id: "operation-1",
    action,
    network: "testnet",
    factory_address: isFactoryAction ? factory : null,
    escrow_address: isFactoryAction ? null : escrow,
    nft_item_address: item,
    price_nano: "2500000000",
    fee_bps: 0,
    execution_reserve_nano: "20000000",
    valid_until: "2099-01-01T00:00:00Z",
    display_purpose: "Проверьте параметры операции",
    messages: [{
      address: destination,
      amount_nano: "2520000000",
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
    createListingIntent: (input) => operation("/test/escrow/listing-intents", input),
    createBuyerDealIntent: (input) => operation("/test/escrow/deal-intents", input),
    prepareDealEscrow: (input) => operation("/test/escrow/prepare-deal-escrow", input),
    prepareNftDeposit: (input) => operation("/test/escrow/prepare-nft-deposit", input),
    prepareBuyerFunding: (input) => operation("/test/escrow/prepare-buyer-funding", input),
    prepareBuyerAcceptance: (input) => operation("/test/escrow/prepare-buyer-acceptance", input),
    prepareDispute: (input) => operation("/test/escrow/prepare-dispute", input),
    prepareBuyerNftReturn: (input) => operation("/test/escrow/prepare-nft-return", input),
    prepareUnsoldNftWithdrawal: (input) => operation("/test/escrow/prepare-unsold-withdrawal", input),
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
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("validates listing intents, buyer/seller deals and unsold NFT withdrawals", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ items: [listing()], total: 1, next_cursor: null }))
      .mockResolvedValueOnce(response({ items: [deal()], total: 1, next_cursor: null }))
      .mockResolvedValueOnce(response({ items: [deal({ buyer_id: "buyer-2" })], total: 1, next_cursor: null }))
      .mockResolvedValueOnce(response({ items: [withdrawal()], total: 1, next_cursor: null }));

    const api = createEscrowApiClient("access-token", contract());

    await expect(api.listMarketplaceListings()).resolves.toMatchObject({ total: 1 });
    await expect(api.listBuyerDeals()).resolves.toMatchObject({ items: [{ state: "funded_review" }] });
    await expect(api.listSellerDeals()).resolves.toMatchObject({ items: [{ seller_id: "seller-1" }] });
    await expect(api.listSellerWithdrawals()).resolves.toMatchObject({ items: [{ kind: "unsold_nft" }] });

    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/test/escrow/listings");
    expect((vi.mocked(fetch).mock.calls[0][1] as RequestInit).headers).toMatchObject({
      Authorization: "Bearer access-token",
    });
  });

  it("serializes listing and buyer deal intents through injected API routes", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response(listing()))
      .mockResolvedValueOnce(response(deal({ state: "intent_created", available_actions: [] })));

    const api = createEscrowApiClient("access-token", contract());
    await api.createListingIntent({
      asset_id: "asset-1",
      seller_wallet_id: "wallet-seller",
      price_nano: "2500000000",
    });
    await api.createBuyerDealIntent({
      listing_id: "listing-1",
      buyer_wallet_id: "wallet-buyer",
    });

    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/test/escrow/listing-intents");
    expect(JSON.parse(String((vi.mocked(fetch).mock.calls[0][1] as RequestInit).body))).toEqual({
      asset_id: "asset-1",
      seller_wallet_id: "wallet-seller",
      price_nano: "2500000000",
    });
    expect(vi.mocked(fetch).mock.calls[1][0]).toBe("/test/escrow/deal-intents");
  });

  it("uses the injected path and request body for a prepared TON action", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response(prepared("fund_deal")));
    const api = createEscrowApiClient("access-token", contract());

    await api.prepareBuyerFunding({ deal_id: "deal-1", wallet_id: "wallet-buyer" });

    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/test/escrow/prepare-buyer-funding");
    expect(JSON.parse(String(init.body))).toEqual({ deal_id: "deal-1", wallet_id: "wallet-buyer" });
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

  it("rejects unknown states, mainnet data, nonzero PoC fees and malformed nanotons", () => {
    expect(isEscrowListingIntent({ ...listing(), state: "listed" })).toBe(false);
    expect(isEscrowListingIntent({ ...listing(), network: "mainnet" })).toBe(false);
    expect(isEscrowListingIntent({ ...listing(), price_nano: "2.5" })).toBe(false);
    expect(isEscrowListingIntent({ ...listing(), price_nano: "0" })).toBe(false);
    expect(isEscrowListingIntent({ ...listing(), fee_bps: 50 })).toBe(false);
    expect(isEscrowListingIntent({ ...listing(), available_actions: ["buy_now"] })).toBe(false);
    expect(isEscrowDeal({ ...deal(), state: "completed" })).toBe(false);
    expect(isEscrowDeal({ ...deal(), available_actions: ["claim_payout"] })).toBe(false);
    expect(isEscrowWithdrawal({ ...withdrawal(), kind: "seller_proceeds" })).toBe(false);
  });

  it("rejects a prepared transaction with a non-testnet network or nonzero fee", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ ...prepared(), network: "mainnet" }))
      .mockResolvedValueOnce(response({ ...prepared(), fee_bps: 1 }));

    const api = createEscrowApiClient("access-token", contract());
    await expect(api.prepareBuyerFunding({ deal_id: "deal-1", wallet_id: "wallet-buyer" }))
      .rejects.toThrow(/не соответствует ожидаемому контракту/i);
    await expect(api.prepareBuyerFunding({ deal_id: "deal-1", wallet_id: "wallet-buyer" }))
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
