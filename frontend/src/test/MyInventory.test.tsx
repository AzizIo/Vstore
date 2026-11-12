import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MyInventory } from "../inventory/MyInventory";
import type {
  InventoryAsset,
  InventoryPage,
  InventorySyncResponse,
} from "../api/assets";

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
    render(<MyInventory accessToken="session-token" />);

    expect(await screen.findByRole("heading", { name: "My NFT inventory" })).toBeInTheDocument();
    expect(await screen.findByText("Moon Lantern NFT")).toBeInTheDocument();
    expect(inventoryApi.syncMyInventory).not.toHaveBeenCalled();
    expect(inventoryApi.fetchMyInventory).toHaveBeenCalledWith(
      "session-token",
      { limit: 24, offset: 0 },
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

    render(<MyInventory accessToken="session-token" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A verified TON wallet is required to discover NFT inventory",
    );
    expect(screen.getByText(/Connecting a wallet alone does not verify ownership/i)).toBeInTheDocument();
  });

  it("can reach later pages when the current page has no verified NFTs", async () => {
    inventoryApi.fetchMyInventory.mockReset()
      .mockResolvedValueOnce({
        ...firstPage,
        items: [],
        has_more: true,
        next_offset: 24,
      })
      .mockResolvedValueOnce({
        ...lastPage,
        items: [asset],
        offset: 24,
        next_offset: 25,
        has_more: false,
      });

    render(<MyInventory accessToken="session-token" />);

    expect(
      await screen.findByRole("heading", { name: "No verified NFTs on this page" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load more NFTs" }));

    expect(await screen.findByText("Moon Lantern NFT")).toBeInTheDocument();
    expect(inventoryApi.fetchMyInventory).toHaveBeenNthCalledWith(
      2,
      "session-token",
      { limit: 24, offset: 24, walletId: "wallet-1" },
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

    render(<MyInventory accessToken="session-token" />);

    expect(await screen.findByText("No verified NFTs found")).toBeInTheDocument();
  });

  it("does not render untrusted non-HTTPS metadata image URLs", async () => {
    inventoryApi.fetchMyInventory.mockReset().mockResolvedValue({
      ...firstPage,
      items: [secondAsset],
      has_more: false,
      next_offset: 1,
    });

    render(<MyInventory accessToken="session-token" />);

    expect(await screen.findByText("Star Sail NFT")).toBeInTheDocument();
    expect(document.querySelector(".inventory-artwork img")).not.toBeInTheDocument();
  });

  it("allows a user to re-run inventory sync", async () => {
    render(<MyInventory accessToken="session-token" />);
    await screen.findByText("Moon Lantern NFT");

    fireEvent.click(screen.getByRole("button", { name: "Sync inventory" }));

    await waitFor(() => expect(inventoryApi.syncMyInventory).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(inventoryApi.fetchMyInventory).toHaveBeenCalledTimes(2));
  });
});
