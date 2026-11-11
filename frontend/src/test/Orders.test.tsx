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
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ items: [order] })));
  });

  it("shows loading, pending-payment status, and a clear no-payment notice", async () => {
    let resolveRequest: ((value: Response) => void) | undefined;
    vi.mocked(fetch).mockReturnValueOnce(new Promise((resolve) => {
      resolveRequest = resolve;
    }));
    render(<Orders accessToken="private-token" />);
    expect(screen.getByText("Loading orders...")).toBeInTheDocument();

    resolveRequest?.(jsonResponse({ items: [order] }));

    expect(await screen.findByText("Reservation pending")).toBeInTheDocument();
    expect(screen.getByText(/Payment processing is not enabled/)).toBeInTheDocument();
    expect(screen.getByText("Moon Lantern")).toBeInTheDocument();
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
      return jsonResponse({ items: [order] });
    });
    render(<Orders accessToken="private-token" />);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel order" }));

    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel order" })).not.toBeInTheDocument();
  });

  it("shows seller sales without a buyer cancellation action", async () => {
    render(<Orders accessToken="private-token" />);
    await screen.findByText("Moon Lantern");
    fireEvent.change(screen.getByRole("combobox", { name: "Order role" }), {
      target: { value: "seller" },
    });

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

    expect(await screen.findByText("OPENED FROM TELEGRAM NOTIFICATION")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Order role" })).toHaveValue("seller");
    expect(screen.getByText("Moon Lantern")).toBeInTheDocument();
    await waitFor(() => {
      expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes("/api/orders?role=seller"))).toBe(true);
    });
  });
