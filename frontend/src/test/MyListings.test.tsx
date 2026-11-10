import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MyListings } from "../listings/MyListings";
import type { Listing } from "../api/listings";

const mocks = vi.hoisted(() => ({
  session: {
    status: "authenticated",
    accessToken: "seller-token",
    user: { id: "seller-1", telegram_id: 12345, first_name: "Seller" },
  },
  fetchMyListings: vi.fn(),
  publishListing: vi.fn(),
  updateListing: vi.fn(),
  cancelListing: vi.fn(),
}));

vi.mock("../auth/SessionProvider", () => ({
  useSession: () => mocks.session,
}));

vi.mock("../api/listings", () => ({
  fetchMyListings: mocks.fetchMyListings,
  publishListing: mocks.publishListing,
  updateListing: mocks.updateListing,
  cancelListing: mocks.cancelListing,
}));

vi.mock("../listings/CreateListing", () => ({
  CreateListing: () => <div>Create listing form</div>,
}));

const draft: Listing = {
  id: "listing-draft",
  status: "draft",
  title: "My NFT draft",
  description: "Private draft description",
  created_at: "2026-01-01T00:00:00Z",
  asset: {
    id: "asset-1",
    asset_type: "ton_nft",
    external_id: "nft-001",
    item_address: "0:1111111111111111111111111111111111111111111111111111111111111111",
    name: "Lantern NFT",
    description: null,
    image_url: null,
    verification_status: "verified",
  },
  seller: { id: "seller-1", username: "seller", first_name: "Seller" },
};

describe("seller listing management", () => {
  beforeEach(() => {
    mocks.session.status = "authenticated";
    mocks.fetchMyListings.mockReset().mockResolvedValue([draft]);
    mocks.publishListing.mockReset().mockResolvedValue({ ...draft, status: "active" });
    mocks.updateListing.mockReset().mockResolvedValue({
      ...draft,
      title: "Edited NFT",
      description: null,
    });
    mocks.cancelListing.mockReset().mockResolvedValue({ ...draft, status: "cancelled" });
  });

  async function openDraft() {
    render(<MyListings />);
    fireEvent.click(await screen.findByRole("button", { name: /My NFT draft/ }));
    expect(await screen.findByRole("heading", { name: "My NFT draft" })).toBeInTheDocument();
  }

  it("saves an optional expiration date through the listing API", async () => {
    await openDraft();

    fireEvent.change(screen.getByLabelText("Listing expiration"), {
      target: { value: "2030-05-02T12:30" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("Listing details saved.")).toBeInTheDocument();
    expect(mocks.updateListing).toHaveBeenCalledWith(
      draft.id,
      "seller-token",
      expect.objectContaining({
        expires_at: new Date("2030-05-02T12:30").toISOString(),
      }),
    );
  });

  it("displays the no-expiry state when a listing has no expiration", async () => {
    render(<MyListings />);

    fireEvent.click(await screen.findByRole("button", { name: /My NFT draft/ }));
    expect(await screen.findByText("No expiry")).toBeInTheDocument();
  });

  it("requires an explicit confirmation before publication and reports the result", async () => {
    await openDraft();

    fireEvent.click(screen.getByRole("button", { name: "Publish listing" }));
    expect(screen.getByRole("group", { name: "Confirm listing publication" })).toBeInTheDocument();
    expect(mocks.publishListing).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirm publish" }));

    expect(await screen.findByText("Listing published and is now visible in the marketplace.")).toBeInTheDocument();
    expect(mocks.publishListing).toHaveBeenCalledWith(draft.id, "seller-token");
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("saves only the permitted editable listing fields", async () => {
    await openDraft();

    fireEvent.change(screen.getByRole("textbox", { name: "Listing title" }), {
      target: { value: "Edited NFT" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Listing description" }), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("Listing details saved.")).toBeInTheDocument();
    expect(mocks.updateListing).toHaveBeenCalledWith(draft.id, "seller-token", {
      title: "Edited NFT",
      description: null,
    });
  });

  it("requires confirmation before cancelling a draft", async () => {
    await openDraft();

    fireEvent.click(screen.getByRole("button", { name: "Cancel draft" }));
    expect(screen.getByRole("group", { name: "Confirm listing cancellation" })).toBeInTheDocument();
    expect(mocks.cancelListing).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText("Draft cancelled.")).toBeInTheDocument();
    expect(mocks.cancelListing).toHaveBeenCalledWith(draft.id, "seller-token");
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
  });

  it("does not offer listing mutations while an order has reserved it", async () => {
    const reserved = { ...draft, status: "reserved" };
    mocks.fetchMyListings.mockResolvedValue([reserved]);
    render(<MyListings />);
    fireEvent.click(await screen.findByRole("button", { name: /My NFT draft/ }));

    expect(await screen.findByText(/reserved by a pending order/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Publish listing" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unpublish listing" })).not.toBeInTheDocument();
  });

  it("shows provider errors without changing the listing status", async () => {
    mocks.publishListing.mockRejectedValue(new Error("TON provider unavailable"));
    await openDraft();

    fireEvent.click(screen.getByRole("button", { name: "Publish listing" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm publish" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("TON provider unavailable");
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });
});
