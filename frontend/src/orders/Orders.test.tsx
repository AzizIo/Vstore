import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Orders } from "./Orders";
import { cancelOrder, fetchOrder, fetchOrders } from "../api/orders";
import type { MarketplaceOrder } from "../api/orders";

vi.mock("../api/orders", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/orders")>();
  return { ...actual, cancelOrder: vi.fn(), fetchOrder: vi.fn(), fetchOrders: vi.fn() };
});

const order: MarketplaceOrder = {
  id: "order-123456",
  listing_id: "listing-1",
  buyer_id: "buyer-1",
  seller_id: "seller-1",
  status: "reserved",
  price_amount: "2.5",
  price_currency: "TON",
  title: "Moonlight #42",
  asset_name: "Moonlight",
  asset_type: "ton_nft",
  expires_at: "2099-01-01T00:00:00Z",
  created_at: "2026-11-10T10:00:00Z",
  updated_at: "2026-11-10T10:00:00Z",
  events: [{ from_status: null, to_status: "reserved", actor_type: "system", created_at: "2026-11-10T10:00:00Z" }],
};

describe("Order workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchOrders).mockResolvedValue([order]);
    vi.mocked(fetchOrder).mockResolvedValue(order);
    vi.mocked(cancelOrder).mockResolvedValue({ ...order, status: "cancelled" });
  });

  it("switches between purchases and sales and filters by title", async () => {
    render(<Orders accessToken="token" userId="buyer-1" />);
    expect(await screen.findByRole("button", { name: /Moonlight #42/i })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: /search by asset title/i }), { target: { value: "does-not-exist" } });
    expect(screen.getByText("No matching orders")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Sales/i }));
    await waitFor(() => expect(fetchOrders).toHaveBeenLastCalledWith("seller", "token", expect.any(AbortSignal)));
  });

  it("opens details with lifecycle, dates, and expiry countdown", async () => {
    render(<Orders accessToken="token" userId="buyer-1" />);
    fireEvent.click(await screen.findByRole("button", { name: /Open order Moonlight #42/i }));
    expect(await screen.findByRole("heading", { name: "Lifecycle" })).toBeInTheDocument();
    expect(screen.getAllByText(/Payments are not enabled/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/remaining/)).toBeInTheDocument();
    expect(screen.getByText("order-123456")).toBeInTheDocument();
    expect(fetchOrder).toHaveBeenCalledWith("order-123456", "token");
  });

  it("requires explicit confirmation before cancelling a reserved buyer order", async () => {
    render(<Orders accessToken="token" userId="buyer-1" />);
    fireEvent.click(await screen.findByRole("button", { name: /Open order Moonlight #42/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel order" }));
    expect(cancelOrder).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm cancel" }));
    await waitFor(() => expect(cancelOrder).toHaveBeenCalledWith("order-123456", "token"));
    expect(await screen.findByText("Cancelled", { selector: ".order-status" })).toBeInTheDocument();
  });
});
