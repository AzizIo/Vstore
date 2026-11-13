import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

vi.mock("@tonconnect/ui-react", () => ({
  CHAIN: { MAINNET: "-239", TESTNET: "-3" },
  TonConnectUIProvider: ({ children }: { children: ReactNode }) => children,
  useTonWallet: () => null,
  useTonConnectUI: () => [{ sendTransaction: vi.fn(), openModal: vi.fn() }],
}));

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
      return url.match(/\/api\/orders\/[^/?]+$/) ? jsonResponse(order) : jsonResponse({ items: [order] });
    }));
  });

  it("shows loading, pending-payment status, and a clear no-payment notice", async () => {
    let resolveRequest: ((value: Response) => void) | undefined;
    vi.mocked(fetch).mockReturnValueOnce(new Promise((resolve) => {
      resolveRequest = resolve;
    }));
    render(<Orders accessToken="private-token" />);
    expect(screen.getByText("Загружаем заказы…")).toBeInTheDocument();

    resolveRequest?.(jsonResponse({ items: [order] }));

    expect(await screen.findByText("Moon Lantern")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Открыть заказ Moon Lantern/ }));
    expect(await screen.findByRole("heading", { name: "Статус заказа" })).toBeInTheDocument();
    expect(screen.getByText(/Оплата в VILTARA SHOP пока не подключена/)).toBeInTheDocument();
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
    fireEvent.click(await screen.findByRole("button", { name: /Открыть заказ Moon Lantern/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Отменить заказ" }));
    expect(await screen.findByText("Отменить этот резерв?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить отмену" }));

    await waitFor(() => expect(screen.getAllByText("Отменено").length).toBeGreaterThan(0));
    expect(screen.queryByRole("button", { name: "Отменить заказ" })).not.toBeInTheDocument();
  });

  it("shows seller sales without a buyer cancellation action", async () => {
    render(<Orders accessToken="private-token" />);
    await screen.findByText("Moon Lantern");
    fireEvent.click(screen.getByRole("tab", { name: /Продажи/ }));

    await waitFor(() => {
      expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).toContain("role=seller");
    });
    expect(screen.queryByRole("button", { name: "Отменить заказ" })).not.toBeInTheDocument();
  });

  it("renders API errors and an empty state", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: "Не удалось загрузить заказы" }, 503));
    const { rerender } = render(<Orders accessToken="private-token" />);
    expect(await screen.findByText("Не удалось загрузить заказы")).toBeInTheDocument();

    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ items: [] }));
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Пока нет покупок")).toBeInTheDocument();
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

    expect(await screen.findByRole("heading", { name: "Статус заказа" })).toBeInTheDocument();
    expect(screen.getByText("Продавец · Продажа")).toBeInTheDocument();
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
      const match = url.match(/\/api\/orders\/([^/?]+)$/);
      if (match) return jsonResponse(orders.find((item) => item.id === decodeURIComponent(match[1])) ?? order);
      return jsonResponse({ items: orders });
    }));
  });

  it("searches titles and IDs and filters by lifecycle state", async () => {
    render(<Orders accessToken="token" onCatalog={vi.fn()} />);
    expect(await screen.findByText("Golden Gift")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Активные/ }));
    expect(screen.getByText("Moon Lantern")).toBeInTheDocument();
    expect(screen.queryByText("Golden Gift")).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox", { name: "Поиск по названию актива или ID заказа" }), {
      target: { value: "order-1" },
    });
    expect(screen.getByText("Moon Lantern")).toBeInTheDocument();
    expect(screen.queryByText("Silver Gift")).not.toBeInTheDocument();
  });

  it("ignores stale detail responses when the user opens another order", async () => {
    const firstOrder = { ...order, id: "order-1", title: "Moon Lantern" };
    const secondOrder = { ...order, id: "order-2", title: "Golden Gift" };
    let resolveFirst: ((value: Response) => void) | undefined;
    let resolveSecond: ((value: Response) => void) | undefined;

    vi.mocked(fetch).mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/orders/order-1")) {
        return new Promise((resolve) => { resolveFirst = resolve; });
      }
      if (url.endsWith("/api/orders/order-2")) {
        return new Promise((resolve) => { resolveSecond = resolve; });
      }
      return Promise.resolve(jsonResponse({ items: [firstOrder, secondOrder] }));
    });

    render(<Orders accessToken="token" userId="buyer-1" />);
    fireEvent.click(await screen.findByRole("button", { name: /Открыть заказ Moon Lantern/ }));
    fireEvent.click(screen.getByRole("button", { name: /Открыть заказ Golden Gift/ }));

    resolveSecond?.(jsonResponse(secondOrder));
    expect(await screen.findByRole("heading", { name: "Golden Gift" })).toBeInTheDocument();

    resolveFirst?.(jsonResponse(firstOrder));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Golden Gift" })).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Moon Lantern" })).not.toBeInTheDocument();
    });
  });

  it("opens order details, displays lifecycle facts and countdown, and returns to the workspace", async () => {
    render(<Orders accessToken="token" userId="buyer-1" />);
    fireEvent.click(await screen.findByRole("button", { name: /Открыть заказ Moon Lantern/ }));
    expect(await screen.findByRole("heading", { name: "Статус заказа" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "История событий" })).toBeInTheDocument();
    expect(screen.getByText("ID заказа")).toBeInTheDocument();
    expect(screen.getByText(/осталось|Срок резерва истёк/)).toBeInTheDocument();
    expect(screen.getByText(/Оплата в VILTARA SHOP пока не подключена/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "← Назад к заказам" }));
    expect(await screen.findByRole("heading", { name: "Заказы" })).toBeInTheDocument();
  });

  it("sorts orders by price and offers a catalog action when empty", async () => {
    render(<Orders accessToken="token" onCatalog={vi.fn()} />);
    await screen.findByText("Golden Gift");
    fireEvent.change(screen.getByRole("combobox", { name: "Сортировка заказов" }), { target: { value: "price" } });
    const cards = screen.getAllByRole("button", { name: /Открыть заказ/ });
    expect(cards[0]).toHaveAccessibleName(/Golden Gift/);

    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ items: [] }));
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(await screen.findByText("Пока нет покупок")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Перейти в каталог" })).toBeInTheDocument();
  });
});
