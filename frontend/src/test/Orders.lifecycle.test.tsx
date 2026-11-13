import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("@tonconnect/ui-react", () => ({
  CHAIN: { MAINNET: "-239", TESTNET: "-3" },
  TonConnectUIProvider: ({ children }: { children: ReactNode }) => children,
  useTonWallet: () => null,
  useTonConnectUI: () => [{ sendTransaction: vi.fn(), openModal: vi.fn() }],
}));

import type { MarketplaceOrder, OrderStatus } from "../api/orders";
import { Orders } from "../orders/Orders";

const baseOrder: MarketplaceOrder = {
  id: "order-lifecycle-1",
  listing_id: "listing-lifecycle-1",
  buyer_id: "buyer-lifecycle-1",
  seller_id: "seller-lifecycle-1",
  status: "reserved",
  price_amount: "12.5",
  price_currency: "TON",
  title: "Moon Lantern",
  asset_name: "Lantern",
  asset_type: "ton_nft",
  expires_at: "2030-01-01T00:15:00Z",
  created_at: "2030-01-01T00:00:00Z",
  updated_at: "2030-01-01T00:00:00Z",
  events: [{
    from_status: null,
    to_status: "reserved",
    actor_type: "buyer",
    created_at: "2030-01-01T00:00:00Z",
  }],
};

function orderForStatus(status: OrderStatus): MarketplaceOrder {
  const transition = {
    reserved: { from_status: null, actor_type: "buyer" },
    awaiting_transfer: { from_status: "reserved", actor_type: "seller" },
    observing_transfer: { from_status: "awaiting_transfer", actor_type: "system" },
    completed: { from_status: "observing_transfer", actor_type: "system" },
    cancelled: { from_status: "reserved", actor_type: "buyer" },
    expired: { from_status: "reserved", actor_type: "system" },
  }[status] as {
    from_status: OrderStatus | null;
    actor_type: "buyer" | "seller" | "system";
  };

  return {
    ...baseOrder,
    status,
    events: [{
      from_status: transition.from_status,
      to_status: status,
      actor_type: transition.actor_type,
      created_at: baseOrder.updated_at,
    }],
  };
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response;
}

const lifecycleCases: Array<{
  status: OrderStatus;
  label: string;
  explanation: RegExp;
  canCancel: boolean;
}> = [
  {
    status: "reserved",
    label: "Ожидает передачи",
    explanation: /Продавец ещё не начал передачу NFT/,
    canCancel: true,
  },
  {
    status: "awaiting_transfer",
    label: "Ожидает перевода",
    explanation: /Продавец готовит прямую передачу NFT покупателю/,
    canCancel: false,
  },
  {
    status: "observing_transfer",
    label: "Проверяем перевод",
    explanation: /Проверяем перевод по данным блокчейна/,
    canCancel: false,
  },
  {
    status: "completed",
    label: "Завершён",
    explanation: /Сервер подтвердил передачу нужного NFT покупателю/,
    canCancel: false,
  },
  {
    status: "cancelled",
    label: "Отменено",
    explanation: /Резерв отменён/,
    canCancel: false,
  },
  {
    status: "expired",
    label: "Срок истёк",
    explanation: /reservation expired before completion/,
    canCancel: false,
  },
];

describe("delivery lifecycle order UI contract", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each(lifecycleCases)(
    "renders $status with an honest status label and only the permitted cancellation action",
    async ({ status, label, explanation, canCancel }) => {
      const testOrder = orderForStatus(status);
      vi.mocked(fetch).mockImplementation(async (input) => {
        const url = String(input);
        return url.endsWith(`/api/orders/${testOrder.id}`)
          ? jsonResponse(testOrder)
          : jsonResponse({ items: [testOrder] });
      });

      render(<Orders accessToken="lifecycle-test-token" />);

      expect(
        await screen.findByText(label, { selector: ".order-status" }),
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /Открыть заказ Moon Lantern/ }));
      expect(await screen.findByRole("heading", { name: "Статус заказа" })).toBeInTheDocument();
      expect(await screen.findByText(explanation, { selector: ".order-guidance" })).toBeInTheDocument();

      if (canCancel) {
        expect(screen.getByRole("button", { name: "Отменить заказ" })).toBeInTheDocument();
        expect(screen.getByText(/Оплата в VILTARA SHOP пока не подключена/)).toBeInTheDocument();
      } else {
        expect(screen.queryByRole("button", { name: "Отменить заказ" })).not.toBeInTheDocument();
      }
    },
  );
});
