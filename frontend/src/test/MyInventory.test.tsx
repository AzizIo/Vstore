import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MyInventory } from "../inventory/MyInventory";
import type {
  InventoryAsset,
  InventoryPage,
  InventorySyncResponse,
} from "../api/assets";
import type { WalletRecord } from "../wallet/api";

const inventoryApi = vi.hoisted(() => ({
  fetchMyInventory: vi.fn(),
  syncMyInventory: vi.fn(),
}));
vi.mock("../api/assets", () => inventoryApi);

const asset: InventoryAsset = {
  id: "asset-1",
  asset_type: "ton_nft",
  external_id: "0:" + "11".repeat(32),
  item_address: "0:" + "11".repeat(32),
  collection_address: "0:" + "22".repeat(32),
  name: "Moon Lantern NFT",
  description: "Collectible",
  image_url: "https://cdn.example.test/lantern.png",
  verification_status: "verified",
  eligible_for_listing: true,
};

const selectedWallet: WalletRecord = {
  id: "wallet-1",
  address: "0:" + "aa".repeat(32),
  network: "mainnet",
  is_verified: true,
  is_primary: false,
};

const primaryWallet: WalletRecord = {
  id: "wallet-2",
  address: "0:" + "bb".repeat(32),
  network: "mainnet",
  is_verified: true,
  is_primary: true,
};

const primaryWalletAsset: InventoryAsset = {
  ...asset,
  id: "asset-wallet-2",
  external_id: "0:" + "55".repeat(32),
  item_address: "0:" + "55".repeat(32),
  name: "Wallet B NFT",
};

const primaryWalletNextAsset: InventoryAsset = {
  ...asset,
  id: "asset-wallet-2-next",
  external_id: "0:" + "66".repeat(32),
  item_address: "0:" + "66".repeat(32),
  name: "Wallet B second NFT",
};

const secondAsset: InventoryAsset = {
  ...asset,
  id: "asset-2",
  external_id: "0:" + "33".repeat(32),
  item_address: "0:" + "33".repeat(32),
  name: "Star Sail NFT",
  image_url: "javascript:alert(1)",
};

const syncResponse: InventorySyncResponse = {
  wallet_id: "wallet-1",
  synced_at: "2026-11-11T10:00:00Z",
  discovered_count: 25,
  verified_count: 24,
  stale_count: 1,
  invalid_count: 0,
  unsupported_count: 0,
  cancelled_listing_count: 1,
};

const firstPage: InventoryPage = {
  items: [asset],
  wallet_id: "wallet-1",
  limit: 24,
  offset: 0,
  next_offset: 24,
  has_more: true,
};

const lastPage: InventoryPage = {
  items: [asset, secondAsset],
  wallet_id: "wallet-1",
  limit: 24,
  offset: 24,
  next_offset: 26,
  has_more: false,
};

describe("My NFT inventory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    inventoryApi.syncMyInventory.mockResolvedValue(syncResponse);
    inventoryApi.fetchMyInventory
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValue(lastPage);
  });

  it("syncs server-side, displays verified inventory and supports pagination", async () => {
    render(<MyInventory accessToken="session-token" selectedWallet={selectedWallet} />);

    expect(await screen.findByRole("heading", { name: "My NFT inventory" })).toBeInTheDocument();
    expect(await screen.findByText("Moon Lantern NFT")).toBeInTheDocument();
    expect(inventoryApi.syncMyInventory).not.toHaveBeenCalled();
    expect(inventoryApi.fetchMyInventory).toHaveBeenCalledWith(
      "session-token",
      { limit: 24, offset: 0, walletId: selectedWallet.id },
      expect.any(AbortSignal),
    );

    fireEvent.click(screen.getByRole("button", { name: "Sync inventory" }));
    await waitFor(() => expect(inventoryApi.syncMyInventory).toHaveBeenCalledWith(
      "session-token",
      "wallet-1",
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText(/24 verified/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load more NFTs" }));
    expect(await screen.findByText("Star Sail NFT")).toBeInTheDocument();
    expect(screen.getAllByText("Moon Lantern NFT")).toHaveLength(1);
    expect(screen.getAllByText("Item address")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Load more NFTs" })).not.toBeInTheDocument();
  });

  it("asks the user to verify a wallet when the backend reports no verified wallet", async () => {
    inventoryApi.fetchMyInventory.mockReset().mockRejectedValueOnce(
      new Error("A verified TON wallet is required to discover NFT inventory"),
    );

    render(<MyInventory accessToken="session-token" selectedWallet={selectedWallet} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A verified TON wallet is required to discover NFT inventory",
    );
    expect(screen.getByText(/Connecting a wallet alone does not verify ownership/i)).toBeInTheDocument();
  });

  it("does not request inventory until a verified wallet is selected", async () => {
    render(<MyInventory accessToken="session-token" selectedWallet={null} />);

    expect(await screen.findByRole("heading", { name: "Connect and verify a wallet" })).toBeInTheDocument();
    expect(inventoryApi.fetchMyInventory).not.toHaveBeenCalled();
    expect(inventoryApi.syncMyInventory).not.toHaveBeenCalled();
  });

  it("discards in-flight pages when switching from a selected wallet to another wallet", async () => {
    let resolveWalletOnePage!: (page: InventoryPage) => void;
    inventoryApi.fetchMyInventory.mockReset().mockImplementation(
      (_token: string, request: { offset?: number; walletId?: string }) => {
        if (request.walletId === selectedWallet.id && request.offset === 0) {
          return Promise.resolve({
            ...firstPage,
            wallet_id: selectedWallet.id,
            items: [asset],
            next_offset: 24,
            has_more: true,
          });
        }
        if (request.walletId === selectedWallet.id && request.offset === 24) {
          return new Promise<InventoryPage>((resolve) => {
            resolveWalletOnePage = resolve;
          });
        }
        if (request.walletId === primaryWallet.id && request.offset === 0) {
          return Promise.resolve({
            ...firstPage,
            wallet_id: primaryWallet.id,
            items: [primaryWalletAsset],
            next_offset: 48,
            has_more: true,
          });
        }
        if (request.walletId === primaryWallet.id && request.offset === 48) {
          return Promise.resolve({
            ...lastPage,
            wallet_id: primaryWallet.id,
            offset: 48,
            next_offset: 49,
            items: [primaryWalletNextAsset],
            has_more: false,
          });
        }
        throw new Error("Unexpected wallet inventory request");
      },
    );

    const view = render(
      <MyInventory accessToken="session-token" selectedWallet={selectedWallet} />,
    );
    expect(await screen.findByText("Moon Lantern NFT")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load more NFTs" }));
    await waitFor(() => expect(inventoryApi.fetchMyInventory).toHaveBeenCalledTimes(2));

    view.rerender(
      <MyInventory accessToken="session-token" selectedWallet={primaryWallet} />,
    );
    expect(await screen.findByText("Wallet B NFT")).toBeInTheDocument();
    expect(screen.queryByText("Moon Lantern NFT")).not.toBeInTheDocument();

    resolveWalletOnePage({
      ...lastPage,
      wallet_id: selectedWallet.id,
      offset: 24,
      next_offset: 26,
      items: [secondAsset],
      has_more: false,
    });
    await waitFor(() => expect(screen.queryByText("Star Sail NFT")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Load more NFTs" }));
    expect(await screen.findByText("Wallet B second NFT")).toBeInTheDocument();
    expect(inventoryApi.fetchMyInventory).toHaveBeenLastCalledWith(
      "session-token",
      { limit: 24, offset: 48, walletId: primaryWallet.id },
      expect.any(AbortSignal),
    );
  });

  it("continues through consecutive empty verified pages for the selected wallet", async () => {
    inventoryApi.fetchMyInventory.mockReset()
      .mockResolvedValueOnce({
        ...firstPage,
        items: [],
        offset: 0,
        next_offset: 24,
        has_more: true,
      })
      .mockResolvedValueOnce({
        ...firstPage,
        items: [],
        offset: 24,
        next_offset: 48,
        has_more: true,
      })
      .mockResolvedValueOnce({
        ...lastPage,
        items: [asset],
        offset: 48,
        next_offset: 49,
        has_more: false,
      });

    render(
      <MyInventory accessToken="session-token" selectedWallet={selectedWallet} />,
    );

    expect(
      await screen.findByRole("heading", { name: "No verified NFTs on this page" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load more NFTs" }));

    expect(
      await screen.findByRole("heading", { name: "No verified NFTs on this page" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Moon Lantern NFT")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load more NFTs" }));

    expect(await screen.findByText("Moon Lantern NFT")).toBeInTheDocument();
    expect(inventoryApi.fetchMyInventory).toHaveBeenNthCalledWith(
      2,
      "session-token",
      { limit: 24, offset: 24, walletId: selectedWallet.id },
      expect.any(AbortSignal),
    );
    expect(inventoryApi.fetchMyInventory).toHaveBeenNthCalledWith(
      3,
      "session-token",
      { limit: 24, offset: 48, walletId: selectedWallet.id },
      expect.any(AbortSignal),
    );
    expect(screen.queryByText("No verified NFTs found")).not.toBeInTheDocument();
  });

  it("shows empty inventory after a successful sync", async () => {
    inventoryApi.fetchMyInventory.mockReset().mockResolvedValue({
      ...firstPage,
      items: [],
      has_more: false,
      next_offset: 0,
    });

    render(<MyInventory accessToken="session-token" selectedWallet={selectedWallet} />);

    expect(await screen.findByText("No verified NFTs found")).toBeInTheDocument();
  });

  it("does not render untrusted non-HTTPS metadata image URLs", async () => {
    inventoryApi.fetchMyInventory.mockReset().mockResolvedValue({
      ...firstPage,
      items: [secondAsset],
      has_more: false,
      next_offset: 1,
    });

    render(<MyInventory accessToken="session-token" selectedWallet={selectedWallet} />);

    expect(await screen.findByText("Star Sail NFT")).toBeInTheDocument();
    expect(document.querySelector(".inventory-artwork img")).not.toBeInTheDocument();
  });

  it("allows a user to re-run inventory sync", async () => {
    render(<MyInventory accessToken="session-token" selectedWallet={selectedWallet} />);
    await screen.findByText("Moon Lantern NFT");

    fireEvent.click(screen.getByRole("button", { name: "Sync inventory" }));

    await waitFor(() => expect(inventoryApi.syncMyInventory).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(inventoryApi.fetchMyInventory).toHaveBeenCalledTimes(2));
  });
});
