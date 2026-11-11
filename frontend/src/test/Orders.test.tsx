import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Orders } from "../orders/Orders";

const order = {
  id: "order-1",
  listing_id: "listing-1",
  buyer_id: "buyer-1",
  seller_id: "seller-1",
  status: "reserved" as const,
  price_amount: "12.5",
  price_currency: "TON" as const,
  title: "Moon Lantern",
  asset_name: "Lantern",
  asset_type: "ton_nft" as const,
  expires_at: "2026-01-01T00:15:00Z",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  events: [{
    from_status: null,
    to_status: "reserved" as const,
    actor_type: "buyer" as const,
    created_at: "2026-01-01T00:00:00Z",
  }],
};

function jsonResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

describe("orders", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input) => {
      const url = String(input);
      return url.match(/\\/api\\/orders\\/[^/?]+$/) ? jsonResponse(order) : jsonResponse({ items: [order] });
    }));
  });

  it("shows loading, pending-payment status, and a clear no-payment notice", async () => {
    let resolveRequest: ((value: Response) => void) | undefined;
    vi.mocked(fetch).mockReturnValueOnce(new Promise((resolve) => {
      resolveRequest = resolve;
    }));
    render(<Orders accessToken="private-token" />);
    expect(screen.getByText("Loading orders...")).toBeInTheDocument();

    resolveRequest?.(jsonResponse({ items: [order] }));

    expect(await screen.findByText("Moon Lantern")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Open order Moon Lantern/ }));
    expect(await screen.findByRole("heading", { name: "Lifecycle" })).toBeInTheDocument();
    expect(screen.getByText(/Payments are not enabled/)).toBeInTheDocument();
  });

  it("cancels a pending buyer order and updates its displayed state", async () => {
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      if (String(input).endsWith("/cancel")) {
        expect(init?.method).toBe("POST");
        return jsonResponse({
          ...order,
          status: "cancelled",
          events: [
            ...order.events,
            { from_status: "reserved", to_status: "cancelled", actor_type: "buyer", created_at: order.updated_at },
          ],
        });
      }
      if (String(input).endsWith(`/api/orders/${order.id}`)) return jsonResponse(order);
      return jsonResponse({ items: [order] });
    });
    render(<Orders accessToken="private-token" />);
    fireEvent.click(await screen.findByRole("button", { name: /Open order Moon Lantern/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel order" }));
    expect(await screen.findByText("Cancel this reservation?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm cancellation" }));

    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel order" })).not.toBeInTheDocument();
  });

  it("shows seller sales without a buyer cancellation action", async () => {
    render(<Orders accessToken="private-token" />);
    await screen.findByText("Moon Lantern");
    fireEvent.click(screen.getByRole("tab", { name: /Sales/ }));

    await waitFor(() => {
      expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).toContain("role=seller");
    });
    expect(screen.queryByRole("button", { name: "Cancel order" })).not.toBeInTheDocument();
  });

  it("renders API errors and an empty state", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: "Orders offline" }, 503));
    const { rerender } = render(<Orders accessToken="private-token" />);
    expect(await screen.findByText("Orders offline")).toBeInTheDocument();

    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ items: [] }));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No purchases yet")).toBeInTheDocument();
    rerender(<Orders accessToken="private-token" />);
  });
});


  it("opens an order deep link and selects the seller view for the recipient", async () => {
    const linkedOrder = { ...order, buyer_id: "buyer-other", seller_id: "seller-current" };
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith(`/api/orders/${order.id}`)) return jsonResponse(linkedOrder);
      if (url.includes("/api/orders?role=seller")) return jsonResponse({ items: [linkedOrder] });
      return jsonResponse({ items: [order] });
    });

    render(
      <Orders
        accessToken="private-token"
        userId="seller-current"
        initialOrderId={order.id}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Lifecycle" })).toBeInTheDocument();
    expect(screen.getByText("Seller · Sale")).toBeInTheDocument();
    expect(screen.getByText("Moon Lantern")).toBeInTheDocument();
    await waitFor(() => {
      expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes("/api/orders?role=seller"))).toBe(true);
    });
  });


describe("order workspace interactions", () => {
  beforeEach(() => {
    const orders = [
      order,
      { ...order, id: "order-2", title: "Golden Gift", status: "completed" as const, price_amount: "30", created_at: "2026-01-02T00:00:00Z" },
      { ...order, id: "order-3", title: "Silver Gift", status: "expired" as const, price_amount: "5", created_at: "2026-01-03T00:00:00Z" },
    ];
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input) => {
      const url = String(input);
      const match = url.match(/\\/api\\/orders\\/([^/?]+)$/);
      if (match) return jsonResponse(orders.find((item) => item.id === decodeURIComponent(match[1])) ?? order);
      return jsonResponse({ items: orders });
    }));
  });

  it("searches titles and IDs and filters by lifecycle state", async () => {
    render(<Orders accessToken="token" onCatalog={vi.fn()} />);
    expect(await screen.findByText("Golden Gift")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Active/ }));
    expect(screen.getByText("Moon Lantern")).toBeInTheDocument();
    expect(screen.queryByText("Golden Gift")).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox", { name: "Search orders by asset title or order ID" }), {
      target: { value: "order-1" },
    });
    expect(screen.getByText("Moon Lantern")).toBeInTheDocument();
    expect(screen.queryByText("Silver Gift")).not.toBeInTheDocument();
  });

  it("opens order details, displays lifecycle facts and countdown, and returns to the workspace", async () => {
    render(<Orders accessToken="token" userId="buyer-1" />);
    fireEvent.click(await screen.findByRole("button", { name: /Open order Moon Lantern/ }));
    expect(await screen.findByRole("heading", { name: "Lifecycle" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Event timeline" })).toBeInTheDocument();
    expect(screen.getByText("Order ID")).toBeInTheDocument();
    expect(screen.getByText(/remaining|Reservation expired/)).toBeInTheDocument();
    expect(screen.getByText(/Payments are not enabled/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "← Back to orders" }));
    expect(await screen.findByRole("heading", { name: "Order workspace" })).toBeInTheDocument();
  });

  it("sorts orders by price and offers a catalog action when empty", async () => {
    render(<Orders accessToken="token" onCatalog={vi.fn()} />);
    await screen.findByText("Golden Gift");
    fireEvent.change(screen.getByRole("combobox", { name: "Sort orders" }), { target: { value: "price" } });
    const cards = screen.getAllByRole("button", { name: /Open order/ });
    expect(cards[0]).toHaveAccessibleName(/Golden Gift/);

    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ items: [] }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("No purchases yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explore catalog" })).toBeInTheDocument();
  });
});
