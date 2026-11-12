import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SellerOverview } from "../overview/SellerOverview";
import type { SellerOverview as OverviewData } from "../api/overview";

const overviewApi = vi.hoisted(() => ({ fetchSellerOverview: vi.fn() }));
vi.mock("../api/overview", () => overviewApi);

const data: OverviewData = {
  listings: { draft: 1, active: 3, reserved: 2, sold: 0, cancelled: 1, expired: 0, suspended: 1, total: 8 },
  orders_as_seller: { reserved: 2, awaiting_transfer: 1, observing_transfer: 0, completed: 1, cancelled: 0, expired: 0, total: 4 },
  orders_as_buyer: { reserved: 0, awaiting_transfer: 0, observing_transfer: 0, completed: 1, cancelled: 0, expired: 0, total: 1 },
  reserved_order_snapshot_values: { TON: "12.500000000", XTR: "40.00" },
  completed_order_snapshot_values: { TON: "3.25" },
  recent_activity: [
    {
      id: "order-1", kind: "order", role: "seller", listing_id: "listing-1",
      title: "Moon Lantern", status: "reserved", created_at: "2026-11-12T08:00:00Z",
      price_amount: "12.5", price_currency: "TON",
    },
    {
      id: "listing-2", kind: "listing", role: null, listing_id: "listing-2",
      title: "Star Sail", status: "active", created_at: "2026-11-11T08:00:00Z",
      price_amount: "40", price_currency: "XTR",
    },
    {
      id: "listing-suspended", kind: "listing", role: null, listing_id: "listing-suspended",
      title: "Suspended listing", status: "suspended", created_at: "2026-11-10T08:00:00Z",
      price_amount: "2", price_currency: "TON",
    },
  ],
};

describe("Seller overview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    overviewApi.fetchSellerOverview.mockResolvedValue(data);
  });

  it("loads private seller metrics and keeps snapshot totals separated by currency", async () => {
    render(
      <SellerOverview
        accessToken="seller-token"
        onOpenOrders={vi.fn()}
        onOpenListing={vi.fn()}
        onManageListings={vi.fn()}
      />,
    );

    expect(screen.getByText("Loading seller overview…")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Seller overview" })).toBeInTheDocument();
    expect(overviewApi.fetchSellerOverview).toHaveBeenCalledWith("seller-token", expect.any(AbortSignal));
    expect(screen.getByText("12.500000000 TON · 40.00 XTR")).toBeInTheDocument();
    expect(screen.getByText("3.25 TON")).toBeInTheDocument();
    expect(screen.getByText(/Reservations are not payments/)).toBeInTheDocument();
    expect(screen.getByText("Active listings")).toBeInTheDocument();
    expect(screen.getByText("Suspended")).toBeInTheDocument();
    expect(screen.getByText("Completed transfers")).toBeInTheDocument();
  });

  it("opens the selected order and listing from recent activity", async () => {
    const onOpenOrders = vi.fn();
    const onOpenListing = vi.fn();
    const onManageListings = vi.fn();
    render(
      <SellerOverview
        accessToken="seller-token"
        onOpenOrders={onOpenOrders}
        onOpenListing={onOpenListing}
        onManageListings={onManageListings}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /Moon Lantern/ }));
    expect(onOpenOrders).toHaveBeenCalledWith("order-1");
    fireEvent.click(screen.getByRole("button", { name: /Star Sail/ }));
    expect(onOpenListing).toHaveBeenCalledWith("listing-2");
    fireEvent.click(screen.getByRole("button", { name: "Manage listings ↗" }));
    expect(onManageListings).toHaveBeenCalledOnce();
  });

  it("renders empty activity and retries after API failure", async () => {
    overviewApi.fetchSellerOverview
      .mockRejectedValueOnce(new Error("Overview offline"))
      .mockResolvedValueOnce({ ...data, recent_activity: [] });

    render(
      <SellerOverview
        accessToken="seller-token"
        onOpenOrders={vi.fn()}
        onOpenListing={vi.fn()}
        onManageListings={vi.fn()}
      />,
    );

    expect(await screen.findByText("Overview offline")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No activity yet")).toBeInTheDocument();
    await waitFor(() => expect(overviewApi.fetchSellerOverview).toHaveBeenCalledTimes(2));
  });
});
