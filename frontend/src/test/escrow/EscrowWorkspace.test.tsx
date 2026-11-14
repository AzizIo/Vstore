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
  EscrowListing,
  EscrowPage,
  EscrowWithdrawal,
  PreparedEscrowTransaction,
} from "../../api/escrow";
import { EscrowWorkspace } from "../../escrow/EscrowWorkspace";

const sellerAddress = "0:" + "1".repeat(64);
const itemAddress = "0:" + "2".repeat(64);
const escrowAddress = "0:" + "3".repeat(64);

const testWallet = {
  id: "wallet-testnet",
  address: sellerAddress,
  network: "testnet",
  is_verified: true,
  is_primary: true,
};

const ignoredMainnetWallet = {
  id: "wallet-mainnet",
  address: "0:" + "4".repeat(64),
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

function listing(overrides: Partial<EscrowListing> = {}): EscrowListing {
  return {
    id: "listing-1",
    seller_id: "seller-1",
    state: "listed",
    network: "testnet",
    nft: {
      asset_id: "asset-1",
      title: "Moon Lantern",
      image_url: null,
      item_address: itemAddress,
      collection_address: null,
    },
    contract_address: escrowAddress,
    seller_wallet_address: sellerAddress,
    price_ton: "2.5",
    platform_fee_ton: "0.1",
    created_at: "2026-11-14T10:00:00Z",
    updated_at: "2026-11-14T10:00:00Z",
    ...overrides,
  };
}

function deal(overrides: Partial<EscrowDeal> = {}): EscrowDeal {
  return {
    id: "deal-1",
    listing_id: "listing-1",
    buyer_id: "buyer-1",
    seller_id: "seller-1",
    state: "buyer_confirmation_window",
    network: "testnet",
    nft: listing().nft,
    contract_address: escrowAddress,
    seller_wallet_address: sellerAddress,
    buyer_wallet_address: sellerAddress,
    price_ton: "2.5",
    platform_fee_ton: "0.1",
    seller_claimable_ton: null,
    buyer_confirmation_deadline: "2026-11-15T10:00:00Z",
    dispute_deadline: "2026-11-16T10:00:00Z",
    created_at: "2026-11-14T10:00:00Z",
    updated_at: "2026-11-14T10:00:00Z",
    dispute: null,
    ...overrides,
  };
}

function withdrawal(): EscrowWithdrawal {
  return {
    id: "withdrawal-1",
    listing_id: "listing-1",
    deal_id: null,
    kind: "unsold_nft",
    status: "observing",
    amount_ton: null,
    destination_address: sellerAddress,
    transaction_hash: null,
    created_at: "2026-11-14T10:00:00Z",
    updated_at: "2026-11-14T10:00:00Z",
  };
}

function prepared(action: PreparedEscrowTransaction["action"]): PreparedEscrowTransaction {
  return {
    id: "operation-" + action,
    action,
    network: "testnet",
    contract_address: escrowAddress,
    nft_item_address: itemAddress,
    amount_ton: "2.5",
    fee_ton: "0.1",
    network_fee_ton: "0.02",
    valid_until: "2099-01-01T00:00:00Z",
    display_summary: "Проверьте параметры операции перед отправкой.",
    messages: [{
      address: escrowAddress,
      amount_nanotons: "2620000000",
      payload_boc: "server-prepared-payload",
      state_init_boc: null,
    }],
  };
}

function page<T>(items: T[]): EscrowPage<T> {
  return { items, total: items.length, next_cursor: null };
}

function makeApi(options: {
  marketplace?: EscrowListing[];
  sellerListings?: EscrowListing[];
  buyerDeals?: EscrowDeal[];
  sellerDeals?: EscrowDeal[];
  listMarketplaceListings?: () => Promise<EscrowPage<EscrowListing>>;
} = {}): EscrowApiClient {
  return {
    listMarketplaceListings: vi.fn(options.listMarketplaceListings ?? (() => Promise.resolve(page(options.marketplace ?? [listing()])))),
    listSellerListings: vi.fn(async () => page(options.sellerListings ?? [])),
    listBuyerDeals: vi.fn(async () => page(options.buyerDeals ?? [])),
    listSellerDeals: vi.fn(async () => page(options.sellerDeals ?? [])),
    listSellerWithdrawals: vi.fn(async () => page([withdrawal()])),
    getListing: vi.fn(async () => listing()),
    getDeal: vi.fn(async () => deal()),
    prepareNftDeposit: vi.fn(async () => prepared("nft_deposit")),
    preparePurchase: vi.fn(async () => prepared("purchase")),
    prepareBuyerConfirmation: vi.fn(async () => prepared("buyer_confirmation")),
    prepareDispute: vi.fn(async () => prepared("dispute")),
    prepareBuyerNftReturn: vi.fn(async () => prepared("buyer_nft_return")),
    prepareUnsoldNftWithdrawal: vi.fn(async () => prepared("unsold_nft_withdrawal")),
    prepareSellerProceedsWithdrawal: vi.fn(async () => prepared("seller_proceeds_withdrawal")),
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

function renderWorkspace(api: EscrowApiClient, currentUserId = "buyer-1") {
  return render(
    <EscrowWorkspace
      accessToken="session-token"
      currentUserId={currentUserId}
      api={api}
      manifestUrl="https://miniapp.example/tonconnect-manifest.json"
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
    expect(screen.getByText("Только TON testnet.")).toBeInTheDocument();
    expect(tonConnectMocks.sendTransaction).not.toHaveBeenCalled();
  });

  it("lets a buyer review the exact server-prepared purchase without signing by default", async () => {
    const api = makeApi();
    renderWorkspace(api);

    expect(await screen.findByRole("heading", { name: "Moon Lantern" })).toBeInTheDocument();
    expect(screen.getAllByText("2.5 TON").length).toBeGreaterThan(0);
    expect(screen.getAllByText("0.1 TON").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Купить за TON" }));

    expect(await screen.findByRole("dialog", { name: "Параметры TON-транзакции" })).toBeInTheDocument();
    expect(screen.getAllByText(escrowAddress).length).toBeGreaterThan(0);
    expect(screen.getAllByText(itemAddress).length).toBeGreaterThan(0);
    expect(screen.getByText("0.02 TON")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Подписать в TON Connect" })).toBeDisabled();
    expect(api.preparePurchase).toHaveBeenCalledWith({
      listing_id: "listing-1",
      buyer_wallet_id: "wallet-testnet",
    });
    expect(tonConnectMocks.sendTransaction).not.toHaveBeenCalled();
  });

  it("filters seller inventory to verified testnet wallets and prepares an NFT deposit", async () => {
    const api = makeApi({
      sellerListings: [listing({ seller_id: "seller-1" })],
    });
    renderWorkspace(api, "seller-1");
    fireEvent.click(screen.getByRole("tab", { name: "Продавец" }));

    expect(await screen.findByRole("button", { name: "Проверить условия депозита" })).toBeEnabled();
    expect(screen.getByText("Подтверждённый кошелёк · 0:11111111…11111111")).toBeInTheDocument();
    expect(screen.queryByText(ignoredMainnetWallet.address)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Проверить условия депозита" }));

    expect(await screen.findByRole("dialog", { name: "Параметры TON-транзакции" })).toBeInTheDocument();
    expect(api.prepareNftDeposit).toHaveBeenCalledWith({
      asset_id: "asset-1",
      seller_wallet_id: "wallet-testnet",
    });
    expect(tonConnectMocks.sendTransaction).not.toHaveBeenCalled();
  });

  it("shows seller claimable proceeds only from the seller-scoped Backend deal feed", async () => {
    const api = makeApi({
      sellerDeals: [deal({
        buyer_id: "buyer-2",
        seller_id: "seller-1",
        seller_claimable_ton: "5.25",
        state: "settled",
      })],
      buyerDeals: [],
    });
    renderWorkspace(api, "seller-1");
    fireEvent.click(screen.getByRole("tab", { name: "Продавец" }));

    expect(await screen.findByText("5.25 TON")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Получить выплату / Claim" }));

    expect(await screen.findByRole("dialog", { name: "Параметры TON-транзакции" })).toBeInTheDocument();
    expect(api.prepareSellerProceedsWithdrawal).toHaveBeenCalledWith({
      deal_id: "deal-1",
      seller_wallet_id: "wallet-testnet",
    });
  });

  it("shows dispute/refund states and prepares buyer NFT return before a refund", async () => {
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
    });
    const refundPending = deal({
      id: "deal-refund",
      state: "refund_pending_nft_return",
    });
    const api = makeApi({ buyerDeals: [disputed, refundPending] });
    renderWorkspace(api);

    expect(await screen.findByText("Открыт спор")).toBeInTheDocument();
    expect(screen.getByText("Покупатель не получил NFT")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Открыть сделку Moon Lantern, Ожидается возврат NFT/ }));
    expect(await screen.findByText(/необходимо сначала вернуть предмет в escrow/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Вернуть NFT в escrow" }));

    expect(await screen.findByRole("dialog", { name: "Параметры TON-транзакции" })).toBeInTheDocument();
    expect(api.prepareBuyerNftReturn).toHaveBeenCalledWith({
      deal_id: "deal-refund",
      buyer_wallet_id: "wallet-testnet",
    });
  });

  it("blocks purchase of the current user's own listing", async () => {
    const api = makeApi({
      marketplace: [listing({ seller_id: "buyer-1" })],
    });
    renderWorkspace(api, "buyer-1");

    expect(await screen.findByText("Доступных лотов пока нет")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Купить за TON" })).not.toBeInTheDocument();
  });

  it("shows API errors and allows retry without changing to a false success state", async () => {
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

  it("allows preparing a purchase but keeps signing disabled without explicit testnet opt-in", async () => {
    const api = makeApi();
    renderWorkspace(api);
    expect(await screen.findByRole("button", { name: "Купить за TON" })).toBeEnabled();
    expect(screen.getByText(/Кошелёк подключён/)).not.toBeInTheDocument();
    expect(tonConnectMocks.sendTransaction).not.toHaveBeenCalled();
  });


  it("blocks duplicate action preparation when the user taps twice", async () => {
    let resolvePrepared: ((value: PreparedEscrowTransaction) => void) | undefined;
    const api = makeApi();
    vi.mocked(api.preparePurchase).mockImplementationOnce(() => new Promise((resolve) => {
      resolvePrepared = resolve;
    }));
    renderWorkspace(api);

    fireEvent.click(await screen.findByRole("button", { name: "Купить за TON" }));
    const purchaseButton = screen.getByRole("button", { name: "Купить за TON" });
    fireEvent.click(purchaseButton);
    fireEvent.click(purchaseButton);

    expect(api.preparePurchase).toHaveBeenCalledTimes(1);
    resolvePrepared?.(prepared("purchase"));
    expect(await screen.findByRole("dialog", { name: "Параметры TON-транзакции" })).toBeInTheDocument();
  });

  it("surfaces a rejected TON Connect request without reporting payment or delivery success", async () => {
    vi.stubEnv("VITE_ESCROW_TESTNET_SIGNING_ENABLED", "true");
    tonConnectMocks.wallet = { account: { address: sellerAddress, chain: "-3" } };
    tonConnectMocks.sendTransaction.mockRejectedValueOnce({ code: 300, message: "User rejected" });
    const api = makeApi();
    render(
      <EscrowWorkspace
        accessToken="session-token"
        currentUserId="buyer-1"
        api={api}
        manifestUrl="https://miniapp.example/tonconnect-manifest.json"
        allowTestnetSigning
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Купить за TON" }));
    const signButton = await screen.findByRole("button", { name: "Подписать в TON Connect" });
    expect(signButton).toBeEnabled();
    fireEvent.click(signButton);

    expect(await screen.findByText(/Запрос кошелька отклонён/)).toBeInTheDocument();
    expect(screen.queryByText("Оплата получена")).not.toBeInTheDocument();
    expect(screen.queryByText("Сделка завершена")).not.toBeInTheDocument();
    expect(tonConnectMocks.sendTransaction).toHaveBeenCalledTimes(1);
  });

  it("locks the pending action after an ambiguous TON Connect result", async () => {
    vi.stubEnv("VITE_ESCROW_TESTNET_SIGNING_ENABLED", "true");
    tonConnectMocks.wallet = { account: { address: sellerAddress, chain: "-3" } };
    tonConnectMocks.sendTransaction.mockRejectedValueOnce(new Error("Wallet connection dropped"));
    render(
      <EscrowWorkspace
        accessToken="session-token"
        currentUserId="buyer-1"
        api={makeApi()}
        manifestUrl="https://miniapp.example/tonconnect-manifest.json"
        allowTestnetSigning
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Купить за TON" }));
    const signButton = await screen.findByRole("button", { name: "Подписать в TON Connect" });
    fireEvent.click(signButton);

    expect(await screen.findByText(/Результат запроса кошелька неизвестен/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Подписать в TON Connect" })).toBeDisabled();
    expect(tonConnectMocks.sendTransaction).toHaveBeenCalledTimes(1);
  });

  it("retains a mobile-readable layout at a narrow WebView viewport", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 320 });
    const mobileListing = listing({
      nft: {
        ...listing().nft,
        item_address: "0:" + "a".repeat(64),
      },
    });
    const api = makeApi({ marketplace: [mobileListing] });
    renderWorkspace(api);

    expect(await screen.findByRole("heading", { name: "TON Escrow" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Покупатель" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Продавец" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Обновить" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Купить за TON" })).toBeVisible();
    expect(screen.getByText(/Blockchain-транзакции могут быть необратимыми/)).toBeInTheDocument();
  });
});
