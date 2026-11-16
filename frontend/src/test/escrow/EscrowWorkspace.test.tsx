import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const tonConnectMocks = vi.hoisted(() => ({
  sendTransaction: vi.fn(async () => ({ boc: "c2lnbmVkLWJvYw==" })),
  openModal: vi.fn(),
  wallet: null as { account: { address: string; chain: string } } | null,
}));

vi.mock("@tonconnect/ui-react", () => ({
  CHAIN: { MAINNET: "-239", TESTNET: "-3" },
  TonConnectUIProvider: ({ children }: { children: ReactNode }) => children,
  useTonWallet: () => tonConnectMocks.wallet,
  useTonConnectUI: () => [tonConnectMocks],
}));

import type {
  EscrowApiClient,
  EscrowDeal,
  EscrowListingIntent,
  EscrowPage,
  EscrowRetryableOutboundAction,
  EscrowWithdrawal,
  PreparedEscrowTransaction,
} from "../../api/escrow";
import { EscrowWorkspace } from "../../escrow/EscrowWorkspace";

const sellerAddress = "0:" + "1".repeat(64);
const itemAddress = "0:" + "2".repeat(64);
const escrowAddress = "0:" + "3".repeat(64);
const factoryAddress = "0:" + "4".repeat(64);

const testWallet = {
  id: "wallet-testnet",
  address: sellerAddress,
  network: "testnet",
  is_verified: true,
  is_primary: true,
};
const ignoredMainnetWallet = {
  id: "wallet-mainnet",
  address: "0:" + "5".repeat(64),
  network: "mainnet",
  is_verified: true,
  is_primary: false,
};
const inventoryAsset = {
  id: "asset-1",
  asset_type: "ton_nft" as const,
  external_id: "nft-external-1",
  item_address: itemAddress,
  collection_address: null,
  name: "Moon Lantern",
  description: null,
  image_url: null,
  verification_status: "verified",
  eligible_for_listing: true,
};

function listing(overrides: Partial<EscrowListingIntent> = {}): EscrowListingIntent {
  return {
    id: "listing-1",
    listing_key: "listing-key-1",
    seller_id: "seller-1",
    state: "intent_only",
    network: "testnet",
    nft: {
      asset_id: "asset-1",
      title: "Moon Lantern",
      image_url: null,
      item_address: itemAddress,
      collection_address: null,
    },
    seller_wallet_address: sellerAddress,
    price_nano: "2500000000",
    fee_bps: 0,
    available_actions: ["create_deal_intent"],
    created_at: "2026-11-14T10:00:00Z",
    updated_at: "2026-11-14T10:00:00Z",
    ...overrides,
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
    escrow_address: escrowAddress,
    seller_wallet_address: sellerAddress,
    buyer_wallet_address: sellerAddress,
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
    destination_address: sellerAddress,
    transaction_hash: null,
    created_at: "2026-11-14T10:00:00Z",
    updated_at: "2026-11-14T10:00:00Z",
  };
}

function prepared(action: PreparedEscrowTransaction["action"]): PreparedEscrowTransaction {
  const isFactoryAction = action === "create_deal_escrow";
  const nftAction = action === "deposit_nft" || action === "return_nft_to_escrow";
  const destination = isFactoryAction ? factoryAddress : nftAction ? itemAddress : escrowAddress;
  return {
    action_id: "operation-" + action,
    action,
    network: "testnet",
    factory_address: isFactoryAction ? factoryAddress : null,
    escrow_address: isFactoryAction ? null : escrowAddress,
    nft_item_address: itemAddress,
    price_nano: "2500000000",
    fee_bps: 0,
    execution_reserve_nano: "20000000",
    valid_until: "2099-01-01T00:00:00Z",
    display_purpose: "Проверьте параметры операции перед отправкой.",
    messages: [{
      address: destination,
      amount_nano: "2520000000",
      payload_boc: "server-prepared-payload",
      state_init_boc: null,
    }],
  };
}

function page<T>(items: T[]): EscrowPage<T> {
  return { items, total: items.length, next_cursor: null };
}

function makeApi(options: {
  marketplace?: EscrowListingIntent[];
  sellerListings?: EscrowListingIntent[];
  buyerDeals?: EscrowDeal[];
  sellerDeals?: EscrowDeal[];
  retryableOutboundActions?: EscrowRetryableOutboundAction[];
  listMarketplaceListings?: () => Promise<EscrowPage<EscrowListingIntent>>;
} = {}): EscrowApiClient {
  return {
    listMarketplaceListings: vi.fn(options.listMarketplaceListings ?? (() => Promise.resolve(page(options.marketplace ?? [listing()])))),
    listSellerListings: vi.fn(async () => page(options.sellerListings ?? [])),
    listBuyerDeals: vi.fn(async () => page(options.buyerDeals ?? [])),
    listSellerDeals: vi.fn(async () => page(options.sellerDeals ?? [])),
    listSellerWithdrawals: vi.fn(async () => page([withdrawal()])),
    getListing: vi.fn(async () => listing()),
    getDeal: vi.fn(async () => deal()),
    createListingIntent: vi.fn(async () => listing()),
    createBuyerDealIntent: vi.fn(async () => deal({ state: "intent_created", available_actions: [] })),
    prepareDealEscrow: vi.fn(async () => prepared("create_deal_escrow")),
    prepareNftDeposit: vi.fn(async () => prepared("deposit_nft")),
    prepareBuyerFunding: vi.fn(async () => prepared("fund_deal")),
    prepareBuyerAcceptance: vi.fn(async () => prepared("accept_deal")),
    prepareDispute: vi.fn(async () => prepared("open_dispute")),
    prepareBuyerNftReturn: vi.fn(async () => prepared("return_nft_to_escrow")),
    prepareUnsoldNftWithdrawal: vi.fn(async () => prepared("withdraw_unsold_nft")),
    listRetryableOutboundActions: vi.fn(async () => options.retryableOutboundActions ?? []),
    prepareFailedOutboundRetry: vi.fn(async () => prepared("retry_failed_outbound_action")),
    submitWalletReference: vi.fn(async () => undefined),
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function installInventoryApi() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/wallets/me")) {
      return jsonResponse([testWallet, ignoredMainnetWallet]);
    }
    if (url.includes("/api/assets/me?")) {
      return jsonResponse({
        items: [inventoryAsset],
        wallet_id: "wallet-testnet",
        limit: 24,
        offset: 0,
        next_offset: 0,
        has_more: false,
      });
    }
    throw new Error("Unexpected fetch in escrow workspace test: " + url);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderWorkspace(api: EscrowApiClient, currentUserId = "buyer-1", allowTestnetSigning = false) {
  return render(
    <EscrowWorkspace
      accessToken="session-token"
      currentUserId={currentUserId}
      api={api}
      manifestUrl="https://miniapp.example/tonconnect-manifest.json"
      allowTestnetSigning={allowTestnetSigning}
    />,
  );
}

describe("TON Escrow workspace", () => {
  beforeEach(() => {
    tonConnectMocks.sendTransaction.mockReset();
    tonConnectMocks.sendTransaction.mockResolvedValue({ boc: "c2lnbmVkLWJvYw==" });
    tonConnectMocks.openModal.mockClear();
    tonConnectMocks.wallet = null;
    installInventoryApi();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    tonConnectMocks.wallet = null;
  });

  it("shows an explicit unavailable state when the future Backend API is not configured", async () => {
    render(
      <EscrowWorkspace
        accessToken="session-token"
        currentUserId="buyer-1"
        manifestUrl="https://miniapp.example/tonconnect-manifest.json"
      />,
    );

    expect(await screen.findByText(/Escrow Backend API пока не подключён/)).toBeInTheDocument();
    expect(screen.getByText(/Listing intent, отдельная сделка/)).toBeInTheDocument();
    expect(tonConnectMocks.sendTransaction).not.toHaveBeenCalled();
  });

  it("lets a buyer create a deal intent without pretending TON has been paid", async () => {
    const api = makeApi();
    renderWorkspace(api);

    expect(await screen.findByRole("heading", { name: "Moon Lantern" })).toBeInTheDocument();
    expect(screen.getAllByText("2.5 TON").length).toBeGreaterThan(0);
    expect(screen.getByText(/Это ещё не оплата/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Создать сделку" }));

    expect(await screen.findByText(/Deal intent создан/)).toBeInTheDocument();
    expect(api.createBuyerDealIntent).toHaveBeenCalledWith({
      listing_id: "listing-1",
      buyer_wallet_id: "wallet-testnet",
    });
    expect(api.prepareBuyerFunding).not.toHaveBeenCalled();
    expect(tonConnectMocks.sendTransaction).not.toHaveBeenCalled();
  });

  it("shows the exact prepared TON funding details but keeps signing disabled by default", async () => {
    const api = makeApi({
      buyerDeals: [deal({
        state: "awaiting_buyer_funds",
        available_actions: ["fund_deal"],
      })],
    });
    renderWorkspace(api);

    fireEvent.click(await screen.findByRole("button", { name: /Открыть сделку Moon Lantern/ }));
    fireEvent.click(screen.getByRole("button", { name: "Внести TON" }));

    expect(await screen.findByRole("dialog", { name: /Внести TON/ })).toBeInTheDocument();
    expect(screen.getAllByText(escrowAddress).length).toBeGreaterThan(0);
    expect(screen.getAllByText(itemAddress).length).toBeGreaterThan(0);
    expect(screen.getByText(/20\.0?\d* TON|0\.02 TON/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Подписать в TON Connect" })).toBeDisabled();
    expect(api.prepareBuyerFunding).toHaveBeenCalledWith({
      deal_id: "deal-1",
      wallet_id: "wallet-testnet",
    });
    expect(tonConnectMocks.sendTransaction).not.toHaveBeenCalled();
  });

  it("allows buyer acceptance only when Backend exposes accept_deal", async () => {
    const api = makeApi({
      buyerDeals: [deal({ state: "funded_review", available_actions: ["accept_deal"] })],
    });
    renderWorkspace(api);

    fireEvent.click(await screen.findByRole("button", { name: /Открыть сделку Moon Lantern/ }));
    fireEvent.click(screen.getByRole("button", { name: "Принять условия и передать NFT" }));

    expect(await screen.findByRole("dialog", { name: /Принять условия/ })).toBeInTheDocument();
    expect(api.prepareBuyerAcceptance).toHaveBeenCalledWith({
      deal_id: "deal-1",
      wallet_id: "wallet-testnet",
    });
  });

  it("opens a dispute only when Backend exposes open_dispute", async () => {
    const api = makeApi({
      buyerDeals: [deal({ state: "delivered_dispute_window", available_actions: ["open_dispute"] })],
    });
    renderWorkspace(api);

    fireEvent.click(await screen.findByRole("button", { name: /Открыть сделку Moon Lantern/ }));
    fireEvent.change(screen.getByLabelText("Причина спора"), { target: { value: "NFT не совпадает с описанием" } });
    fireEvent.click(screen.getByRole("button", { name: "Открыть спор" }));

    expect(await screen.findByRole("dialog", { name: /Открыть спор/ })).toBeInTheDocument();
    expect(api.prepareDispute).toHaveBeenCalledWith({
      deal_id: "deal-1",
      reason: "NFT не совпадает с описанием",
    });
  });

  it("shows a seller dispute and prepares a buyer NFT return only when Backend allows it", async () => {
    const disputed = deal({
      id: "deal-disputed",
      state: "disputed",
      dispute: {
        id: "dispute-1",
        status: "under_review",
        reason_code: "nft_not_received",
        summary: "Покупатель не получил NFT",
        opened_at: "2026-11-14T10:00:00Z",
        resolved_at: null,
        resolution_note: null,
      },
      available_actions: [],
    });
    const returnPending = deal({
      id: "deal-return",
      state: "nft_return_pending",
      available_actions: ["return_nft_to_escrow"],
    });
    const api = makeApi({ buyerDeals: [disputed, returnPending] });
    renderWorkspace(api);

    expect(await screen.findAllByText("Открыт спор")).not.toHaveLength(0);
    expect(screen.getByText("Покупатель не получил NFT")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Открыть сделку Moon Lantern, Возврат NFT/ }));
    expect(await screen.findByText(/вернуть именно этот NFT в escrow/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Вернуть NFT в escrow" }));

    expect(await screen.findByRole("dialog", { name: /Вернуть NFT в escrow/ })).toBeInTheDocument();
    expect(api.prepareBuyerNftReturn).toHaveBeenCalledWith({
      deal_id: "deal-return",
      wallet_id: "wallet-testnet",
    });
  });

  it("creates a seller listing intent from verified testnet inventory and nanotons price", async () => {
    const api = makeApi();
    renderWorkspace(api, "seller-1");
    fireEvent.click(screen.getByRole("tab", { name: "Продавец" }));

    expect(await screen.findByLabelText("Цена предложения · TON testnet")).toBeInTheDocument();
    expect(screen.queryByText(ignoredMainnetWallet.address)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Цена предложения · TON testnet"), { target: { value: "2.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Создать listing intent" }));

    expect(await screen.findByText(/Listing intent создан/)).toBeInTheDocument();
    expect(api.createListingIntent).toHaveBeenCalledWith({
      asset_id: "asset-1",
      seller_wallet_id: "wallet-testnet",
      price_nano: "2500000000",
    });
    expect(tonConnectMocks.sendTransaction).not.toHaveBeenCalled();
  });

  it("does not create a listing intent for zero or malformed prices", async () => {
    const api = makeApi();
    renderWorkspace(api, "seller-1");
    fireEvent.click(screen.getByRole("tab", { name: "Продавец" }));

    const priceInput = await screen.findByLabelText("Цена предложения · TON testnet");
    fireEvent.change(priceInput, { target: { value: "0" } });
    expect(screen.getByRole("button", { name: "Создать listing intent" })).toBeDisabled();
    fireEvent.change(priceInput, { target: { value: "2,5" } });
    expect(screen.getByRole("button", { name: "Создать listing intent" })).toBeDisabled();
    fireEvent.change(priceInput, { target: { value: "2.5" } });
    expect(screen.getByRole("button", { name: "Создать listing intent" })).toBeEnabled();
    expect(api.createListingIntent).not.toHaveBeenCalled();
  });

  it("lets the seller prepare DealEscrow only when the incoming deal action allows it", async () => {
    const incoming = deal({
      buyer_id: "buyer-2",
      seller_id: "seller-1",
      state: "intent_created",
      available_actions: ["create_deal_escrow"],
    });
    const api = makeApi({ sellerDeals: [incoming] });
    renderWorkspace(api, "seller-1");
    fireEvent.click(screen.getByRole("tab", { name: "Продавец" }));

    fireEvent.click(await screen.findByRole("button", { name: "Создать DealEscrow" }));
    expect(await screen.findByRole("dialog", { name: /Создать DealEscrow/ })).toBeInTheDocument();
    expect(api.prepareDealEscrow).toHaveBeenCalledWith({
      deal_id: "deal-1",
      wallet_id: "wallet-testnet",
    });
  });

  it("lets the seller deposit NFT after the deal reaches awaiting_nft", async () => {
    const incoming = deal({
      buyer_id: "buyer-2",
      seller_id: "seller-1",
      state: "awaiting_nft",
      available_actions: ["deposit_nft"],
    });
    const api = makeApi({ sellerDeals: [incoming] });
    renderWorkspace(api, "seller-1");
    fireEvent.click(screen.getByRole("tab", { name: "Продавец" }));

    fireEvent.click(await screen.findByRole("button", { name: "Внести NFT в DealEscrow" }));
    expect(await screen.findByRole("dialog", { name: /Внести NFT/ })).toBeInTheDocument();
    expect(api.prepareNftDeposit).toHaveBeenCalledWith({
      deal_id: "deal-1",
      wallet_id: "wallet-testnet",
    });
  });

  it("lets the seller return an unsold NFT only when Backend exposes that action", async () => {
    const incoming = deal({
      buyer_id: "buyer-2",
      seller_id: "seller-1",
      state: "awaiting_buyer_funds",
      available_actions: ["withdraw_unsold_nft"],
    });
    const api = makeApi({ sellerDeals: [incoming] });
    renderWorkspace(api, "seller-1");
    fireEvent.click(screen.getByRole("tab", { name: "Продавец" }));

    const withdrawalButtons = await screen.findAllByRole("button", { name: "Вернуть непроданный NFT" });
    expect(withdrawalButtons.length).toBeGreaterThan(0);
    fireEvent.click(withdrawalButtons[0]);
    expect(await screen.findByRole("dialog", { name: /Вернуть непроданный NFT/ })).toBeInTheDocument();
    expect(api.prepareUnsoldNftWithdrawal).toHaveBeenCalledWith({
      deal_id: "deal-1",
      wallet_id: "wallet-testnet",
    });
  });

  it("shows a buyer refund as pending until observer finality and offers no manual refund button", async () => {
    const api = makeApi({
      buyerDeals: [deal({
        state: "buyer_refund_pending",
        available_actions: [],
      })],
    });
    renderWorkspace(api);

    fireEvent.click(await screen.findByRole("button", { name: /Открыть сделку Moon Lantern/ }));
    expect(await screen.findAllByText(/Контракт инициировал refund/)).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: /refund|вернуть деньги/i })).not.toBeInTheDocument();
  });

  it("shows dispute information in the seller participant feed", async () => {
    const api = makeApi({
      sellerDeals: [deal({
        buyer_id: "buyer-2",
        seller_id: "seller-1",
        state: "disputed",
        dispute: {
          id: "dispute-seller-1",
          status: "under_review",
          reason_code: "transfer_mismatch",
          summary: "Нужно проверить соответствие NFT",
          opened_at: "2026-11-14T10:00:00Z",
          resolved_at: null,
          resolution_note: null,
        },
        available_actions: [],
      })],
    });
    renderWorkspace(api, "seller-1");
    fireEvent.click(screen.getByRole("tab", { name: "Продавец" }));

    expect(await screen.findByText("Нужно проверить соответствие NFT")).toBeInTheDocument();
    expect(screen.getByText("Спор · На рассмотрении")).toBeInTheDocument();
  });

  it("shows payout as pending and never exposes a manual seller claim", async () => {
    const incoming = deal({
      buyer_id: "buyer-2",
      seller_id: "seller-1",
      state: "seller_payout_pending",
      available_actions: [],
    });
    const api = makeApi({ sellerDeals: [incoming] });
    renderWorkspace(api, "seller-1");
    fireEvent.click(screen.getByRole("tab", { name: "Продавец" }));

    expect(await screen.findByText(/Контракт инициировал seller payout/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /claim|получить выплату/i })).not.toBeInTheDocument();
  });

  it("blocks a buyer from creating a deal on their own listing", async () => {
    const api = makeApi({ marketplace: [listing({ seller_id: "buyer-1" })] });
    renderWorkspace(api, "buyer-1");

    expect(await screen.findByText("Предложений пока нет")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Создать сделку" })).not.toBeInTheDocument();
  });

  it("shows API errors and allows retry without reporting a false success", async () => {
    const api = makeApi({
      listMarketplaceListings: vi.fn()
        .mockRejectedValueOnce(new Error("Indexer temporarily unavailable"))
        .mockResolvedValue(page([listing()])),
    });
    renderWorkspace(api);

    expect(await screen.findByText("Indexer temporarily unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByRole("heading", { name: "Moon Lantern" })).toBeInTheDocument();
    expect(tonConnectMocks.sendTransaction).not.toHaveBeenCalled();
  });

  it("blocks duplicate action preparation when the user taps twice", async () => {
    let resolvePrepared: ((value: PreparedEscrowTransaction) => void) | undefined;
    const api = makeApi({
      buyerDeals: [deal({ state: "awaiting_buyer_funds", available_actions: ["fund_deal"] })],
    });
    vi.mocked(api.prepareBuyerFunding).mockImplementationOnce(() => new Promise((resolve) => {
      resolvePrepared = resolve;
    }));
    renderWorkspace(api);

    fireEvent.click(await screen.findByRole("button", { name: /Открыть сделку Moon Lantern/ }));
    const fundButton = screen.getByRole("button", { name: "Внести TON" });
    fireEvent.click(fundButton);
    fireEvent.click(fundButton);
    expect(api.prepareBuyerFunding).toHaveBeenCalledTimes(1);
    resolvePrepared?.(prepared("fund_deal"));
    expect(await screen.findByRole("dialog", { name: /Внести TON/ })).toBeInTheDocument();
  });

  it("surfaces a rejected TON Connect request without reporting payment or delivery success", async () => {
    vi.stubEnv("VITE_ESCROW_TESTNET_SIGNING_ENABLED", "true");
    tonConnectMocks.wallet = { account: { address: sellerAddress, chain: "-3" } };
    tonConnectMocks.sendTransaction.mockRejectedValueOnce({ code: 300, message: "User rejected" });
    const api = makeApi({
      buyerDeals: [deal({ state: "awaiting_buyer_funds", available_actions: ["fund_deal"] })],
    });
    renderWorkspace(api, "buyer-1", true);

    fireEvent.click(await screen.findByRole("button", { name: /Открыть сделку Moon Lantern/ }));
    fireEvent.click(screen.getByRole("button", { name: "Внести TON" }));
    fireEvent.click(await screen.findByRole("button", { name: "Подписать в TON Connect" }));

    expect(await screen.findByText(/Запрос кошелька отклонён/)).toBeInTheDocument();
    expect(screen.queryByText("Оплата получена")).not.toBeInTheDocument();
    expect(screen.queryByText("Сделка завершена")).not.toBeInTheDocument();
    expect(tonConnectMocks.sendTransaction).toHaveBeenCalledTimes(1);
  });

  it("locks the action after an ambiguous TON Connect result", async () => {
    vi.stubEnv("VITE_ESCROW_TESTNET_SIGNING_ENABLED", "true");
    tonConnectMocks.wallet = { account: { address: sellerAddress, chain: "-3" } };
    tonConnectMocks.sendTransaction.mockRejectedValueOnce(new Error("Wallet connection dropped"));
    const api = makeApi({
      buyerDeals: [deal({ state: "awaiting_buyer_funds", available_actions: ["fund_deal"] })],
    });
    renderWorkspace(api, "buyer-1", true);

    fireEvent.click(await screen.findByRole("button", { name: /Открыть сделку Moon Lantern/ }));
    fireEvent.click(screen.getByRole("button", { name: "Внести TON" }));
    fireEvent.click(await screen.findByRole("button", { name: "Подписать в TON Connect" }));

    expect(await screen.findByText(/Результат запроса кошелька неизвестен/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Подписать в TON Connect" })).toBeDisabled();
    expect(tonConnectMocks.sendTransaction).toHaveBeenCalledTimes(1);
  });

  it("retains a mobile-readable layout at a 320px WebView viewport", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 320 });
    const api = makeApi();
    renderWorkspace(api);

    expect(await screen.findByRole("heading", { name: "TON Escrow" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Покупатель" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Продавец" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Обновить" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Создать сделку" })).toBeVisible();
    expect(screen.getAllByText(/TON testnet/i).length).toBeGreaterThan(0);
  });
});


  it("shows proof-backed retry only for the exact verified recipient wallet", async () => {
    const outbound: EscrowRetryableOutboundAction = {
      query_id: "42",
      slot: "first",
      kind: 6,
      recipient_address: sellerAddress,
      amount_nanotons: "90000000",
      retry_window_seconds: 0,
      proof_masterchain_seqno: 700,
      proof_masterchain_block_hash: "aa".repeat(32),
      proof_state_data_hash: "bb".repeat(32),
      proof_provider_id: "pytoniq-trust0-testnet-v1",
    };
    const api = makeApi({
      buyerDeals: [deal({ state: "refunded", available_actions: [] })],
      retryableOutboundActions: [outbound],
    });
    renderWorkspace(api);

    fireEvent.click(await screen.findByRole("button", { name: /Открыть сделку Moon Lantern/ }));
    const retryButton = await screen.findByRole("button", { name: /Повторить отправку · query 42/ });
    expect(retryButton).toBeEnabled();
    expect(screen.getByText(/актуального proof-read состояния TON testnet/)).toBeInTheDocument();
    expect(screen.getByText(/Окно повтора: 0 сек/)).toBeInTheDocument();
    expect(screen.getByText(/Proof: pytoniq-trust0-testnet-v1/)).toBeInTheDocument();

    fireEvent.click(retryButton);
    expect(api.prepareFailedOutboundRetry).toHaveBeenCalledWith({
      deal_id: "deal-1",
      query_id: "42",
    });
    expect(await screen.findByRole("dialog", { name: /Повторить неудавшуюся отправку/ }))
      .toBeInTheDocument();
    expect(retryButton).toBeDisabled();
    expect(tonConnectMocks.sendTransaction).not.toHaveBeenCalled();
  });

  it("disables retry when the proved recipient has no matching verified testnet wallet", async () => {
    const api = makeApi({
      buyerDeals: [deal({ state: "refunded", available_actions: [] })],
      retryableOutboundActions: [{
        query_id: "43",
        slot: "second",
        kind: 4,
        recipient_address: "0:" + "9".repeat(64),
        amount_nanotons: "90000000",
        retry_window_seconds: 1800,
        proof_masterchain_seqno: 701,
        proof_masterchain_block_hash: "aa".repeat(32),
        proof_state_data_hash: "bb".repeat(32),
        proof_provider_id: "pytoniq-trust0-testnet-v1",
      }],
    });
    renderWorkspace(api);

    fireEvent.click(await screen.findByRole("button", { name: /Открыть сделку Moon Lantern/ }));
    expect(await screen.findByRole("button", { name: /Повторить отправку · query 43/ }))
      .toBeDisabled();
    expect(screen.getByText(/совпадающего с получателем/)).toBeInTheDocument();
    expect(api.prepareFailedOutboundRetry).not.toHaveBeenCalled();
  });


  it("explains that execution-reserve retry carries the contract balance rather than a fixed amount", async () => {
    const api = makeApi({
      buyerDeals: [deal({ state: "refunded", available_actions: [] })],
      retryableOutboundActions: [{
        query_id: "44",
        slot: "second",
        kind: 7,
        recipient_address: sellerAddress,
        amount_nanotons: "0",
        retry_window_seconds: 0,
        proof_masterchain_seqno: 702,
        proof_masterchain_block_hash: "aa".repeat(32),
        proof_state_data_hash: "bb".repeat(32),
        proof_provider_id: "pytoniq-trust0-testnet-v1",
      }],
    });
    renderWorkspace(api);

    fireEvent.click(await screen.findByRole("button", { name: /Открыть сделку Moon Lantern/ }));
    expect(await screen.findByText(/Сумма определяется контрактом: перевод остатка баланса/))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Повторить отправку · query 44/ }))
      .toBeEnabled();
  });
