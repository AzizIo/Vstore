import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CreateListing } from "../listings/CreateListing";
import type { InventoryAsset } from "../api/assets";
import type { Listing } from "../api/listings";

const apiMocks = vi.hoisted(() => ({
  fetchMyInventory: vi.fn(),
  createListingDraft: vi.fn(),
}));

vi.mock("../api/assets", () => apiMocks);

const nft: InventoryAsset = {
  id: "asset-id",
  asset_type: "ton_nft",
  external_id: "0:" + "11".repeat(32),
  item_address: "0:" + "11".repeat(32),
  name: "Verified collectible",
  description: null,
  image_url: null,
  verification_status: "verified",
  eligible_for_listing: true,
};
const inventoryPage = {
  items: [nft], wallet_id: "wallet-id", limit: 24, offset: 0, next_offset: 1, has_more: false,
};
const draft: Listing = {
  id: "draft-id", status: "draft",
  title: "My collectible", description: null, created_at: "2026-01-01T00:00:00Z",
  asset: {
    id: nft.id, asset_type: "ton_nft", external_id: nft.external_id,
    item_address: nft.item_address, name: nft.name, description: null,
    image_url: null, verification_status: "verified",
  },
  seller: { id: "seller-id", username: null, first_name: "Seller" },
};

function renderCreateListing(onDraftCreated = vi.fn(), onCancel = vi.fn()) {
  return {
    onDraftCreated,
    onCancel,
    ...render(
      <CreateListing accessToken="memory-session-token" onCancel={onCancel} onDraftCreated={onDraftCreated} />,
    ),
  };
}

describe("CreateListing seller flow", () => {
  beforeEach(() => {
    apiMocks.fetchMyInventory.mockReset();
    apiMocks.createListingDraft.mockReset();
    apiMocks.fetchMyInventory.mockResolvedValue(inventoryPage);
    apiMocks.createListingDraft.mockResolvedValue(draft);
  });

  it("loads inventory, selects a verified NFT, and submits an unpublished draft", async () => {
    const onDraftCreated = vi.fn();
    renderCreateListing(onDraftCreated);

    expect(await screen.findByText("Verified collectible")).toBeInTheDocument();
    expect(apiMocks.fetchMyInventory).toHaveBeenCalledWith(
      "memory-session-token",
      { limit: 24, offset: 0 },
      expect.any(AbortSignal),
    );
    fireEvent.click(screen.getByRole("button", { name: /Verified collectible/ }));
    fireEvent.change(screen.getByRole("textbox", { name: "Title Optional" }), { target: { value: "My collectible" } });
    fireEvent.click(screen.getByRole("button", { name: "Create private draft" }));

    expect(await screen.findByText("Draft — not published")).toBeInTheDocument();
    expect(apiMocks.createListingDraft).toHaveBeenCalledWith(
      "memory-session-token",
      {
        asset_id: "asset-id",
        title: "My collectible",
      },
      expect.any(AbortSignal),
    );
    expect(onDraftCreated).toHaveBeenCalledWith(draft);
  });

  it("submits an optional expiry date as an ISO timestamp", async () => {
    renderCreateListing();

    fireEvent.click(await screen.findByRole("button", { name: /Verified collectible/ }));
    fireEvent.change(screen.getByLabelText("Listing expiration"), {
      target: { value: "2030-05-02T12:30" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create private draft" }));

    expect(await screen.findByText("Draft — not published")).toBeInTheDocument();
    expect(apiMocks.createListingDraft).toHaveBeenCalledWith(
      "memory-session-token",
      expect.objectContaining({
        asset_id: "asset-id",
        expires_at: new Date("2030-05-02T12:30").toISOString(),
      }),
      expect.any(AbortSignal),
    );
  });

  it("offers wallet navigation when no verified wallet is linked", async () => {
    apiMocks.fetchMyInventory.mockRejectedValue(
      new Error("A verified TON wallet is required to discover NFT inventory"),
    );
    renderCreateListing();

    expect(await screen.findByText("Verify a wallet first")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open wallet connection" })).toHaveAttribute("href", "#wallet-connect");
    expect(screen.getByText(/Connecting a wallet alone does not prove ownership/)).toBeInTheDocument();
  });

  it("shows an empty inventory state without enabling a draft", async () => {
    apiMocks.fetchMyInventory.mockResolvedValue({ ...inventoryPage, items: [], has_more: false });
    renderCreateListing();

    expect(await screen.findByText("No eligible TON NFTs found")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Create private draft/ })).not.toBeInTheDocument();
  });

  it("retries inventory failures", async () => {
    apiMocks.fetchMyInventory
      .mockRejectedValueOnce(new Error("TON NFT inventory provider is temporarily unavailable"))
      .mockResolvedValueOnce(inventoryPage);
    renderCreateListing();

    expect(await screen.findByText("Inventory unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Verified collectible")).toBeInTheDocument();
    expect(apiMocks.fetchMyInventory).toHaveBeenCalledTimes(2);
  });

  it("loads the provider cursor and appends the next inventory page", async () => {
    apiMocks.fetchMyInventory
      .mockResolvedValueOnce({ ...inventoryPage, has_more: true, next_offset: 24 })
      .mockResolvedValueOnce({
        ...inventoryPage,
        items: [{ ...nft, id: "asset-id-2", name: "Second verified NFT" }],
        offset: 24,
        next_offset: 25,
        has_more: false,
      });
    renderCreateListing();

    expect(await screen.findByText("Verified collectible")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load more NFTs" }));
    expect(await screen.findByText("Second verified NFT")).toBeInTheDocument();
    expect(apiMocks.fetchMyInventory).toHaveBeenLastCalledWith(
      "memory-session-token",
      { limit: 24, offset: 24, walletId: "wallet-id" },
      expect.any(AbortSignal),
    );
  });

  it("keeps the form open and explains draft failures", async () => {
    apiMocks.createListingDraft.mockRejectedValue(new Error("NFT ownership could not be freshly verified"));
    renderCreateListing();

    fireEvent.click(await screen.findByRole("button", { name: /Verified collectible/ }));
    fireEvent.click(screen.getByRole("button", { name: "Create private draft" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("NFT ownership could not be freshly verified");
    expect(screen.getByRole("button", { name: "Create private draft" })).toBeInTheDocument();
  });
});
