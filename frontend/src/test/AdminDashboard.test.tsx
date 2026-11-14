import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  fetchAdminOverview: vi.fn(),
  fetchAdminUsers: vi.fn(),
  fetchAdminUserAudit: vi.fn(),
  fetchAdminUserDetail: vi.fn(),
  fetchAdminUserListings: vi.fn(),
  fetchAdminUserOrders: vi.fn(),
  fetchAdminOrders: vi.fn(),
  fetchCombinedAdminAuditLog: vi.fn(),
  submitUserAccessDecision: vi.fn(),
}));
vi.mock("../admin/api", () => api);
vi.mock("../admin/AdminCenter", () => ({
  AdminCenter: ({ active }: { active: boolean }) =>
    <div data-testid="moderation-section">{active ? "Moderation mounted" : "Moderation inactive"}</div>,
}));

import { AdminDashboard } from "../admin/AdminDashboard";

const user = {
  id: "user-1",
  first_name: "Beta",
  last_name: "User",
  username: "beta_user",
  telegram_id: 123456789,
  registered_at: "2026-11-10T10:00:00Z",
  is_blocked: false,
  listing_count: 3,
  deal_count: 2,
  confirmed_wallet_count: 1,
};
const detail = {
  ...user,
  verified_wallets: [{ address_short: "0:abcdef…123456", network: "mainnet", is_primary: true }],
};
const overview = {
  counts: {
    total_users: 101,
    new_users_24h: 3,
    new_users_7d: 14,
    blocked_users: 2,
    unblocked_users: 99,
    total_listings: 45,
    active_listings: 20,
    listings_on_moderation: 4,
    reserved_listings: 3,
    completed_deals: 10,
    deals_in_progress: 5,
  },
  recent_registrations: [user],
  recent_platform_events: [{
    id: "event-1",
    entity_type: "user_access",
    entity_id: "user-1",
    summary: "пользователь заблокирован",
    occurred_at: "2026-11-13T10:00:00Z",
  }],
};
const userListing = {
  id: "listing-1",
  status: "active",
  title: "Moon Lantern",
  asset_name: "Lantern NFT",
  price_amount: "12.5",
  price_currency: "TON",
  created_at: "2026-11-01T10:00:00Z",
  updated_at: "2026-11-01T10:00:00Z",
  expires_at: null,
};
const userOrder = {
  id: "order-1",
  role: "buyer",
  status: "observing_transfer",
  listing_id: "listing-1",
  listing_title: "Moon Lantern",
  asset_name: "Lantern NFT",
  counterparty_name: "Seller",
  counterparty_username: "seller",
  price_amount: "12.5",
  price_currency: "TON",
  created_at: "2026-11-02T10:00:00Z",
  updated_at: "2026-11-02T10:30:00Z",
  delivery_status: "observing",
  delivery_verified_at: null,
};
const order = {
  id: "order-1",
  listing_id: "listing-1",
  listing_title: "Moon Lantern",
  asset_name: "Lantern NFT",
  buyer_id: "user-1",
  buyer_name: "Beta User",
  buyer_username: "beta_user",
  seller_id: "seller-1",
  seller_name: "Seller",
  seller_username: "seller",
  price_amount: "12.5",
  price_currency: "TON",
  status: "observing_transfer",
  created_at: "2026-11-02T10:00:00Z",
  updated_at: "2026-11-02T10:30:00Z",
  delivery_status: "observing",
  delivery_verified_at: null,
};
const auditEntry = {
  id: "audit-1",
  target_type: "user",
  target_id: "user-1",
  actor_id: "admin-1",
  action: "blocked",
  reason_code: null,
  reason: "Policy review confirmed",
  before_snapshot: { is_blocked: false },
  after_snapshot: { is_blocked: true },
  request_id: null,
  idempotency_key: "block-user-1",
  occurred_at: "2026-11-13T10:00:00Z",
};

function page<T>(items: T[]) {
  return { items, total: items.length, limit: 25, offset: 0 };
}

describe("AdminDashboard", () => {
  beforeEach(() => {
    api.fetchAdminOverview.mockReset().mockResolvedValue(overview);
    api.fetchAdminUsers.mockReset().mockResolvedValue(page([user]));
    api.fetchAdminUserAudit.mockReset().mockResolvedValue(page([auditEntry]));
    api.fetchAdminUserDetail.mockReset().mockResolvedValue(detail);
    api.fetchAdminUserListings.mockReset().mockResolvedValue(page([userListing]));
    api.fetchAdminUserOrders.mockReset().mockResolvedValue(page([userOrder]));
    api.fetchAdminOrders.mockReset().mockResolvedValue(page([order]));
    api.fetchCombinedAdminAuditLog.mockReset().mockResolvedValue(page([auditEntry]));
    api.submitUserAccessDecision.mockReset().mockResolvedValue({
      user_id: "user-1",
      is_blocked: true,
      audit: { ...auditEntry, target_user_id: "user-1" },
    });
  });

  it("shows real backend overview counts and recent platform activity", async () => {
    render(<AdminDashboard accessToken="test-token" />);

    expect(await screen.findByText("101")).toBeInTheDocument();
    expect(screen.getByText("Не заблокированы")).toBeInTheDocument();
    expect(screen.getByText("Это не показатель online")).toBeInTheDocument();
    expect(screen.getByText("пользователь заблокирован")).toBeInTheDocument();
    expect(api.fetchAdminOverview).toHaveBeenCalledWith("test-token", expect.any(AbortSignal));
  });

  it("supports server-side search and opens a user detail panel", async () => {
    const { container } = render(<AdminDashboard accessToken="test-token" />);
    fireEvent.click(screen.getByRole("button", { name: "Users" }));

    expect(await screen.findAllByText("123456789")).not.toHaveLength(0);
    fireEvent.change(screen.getByLabelText("Поиск по username или Telegram ID"), {
      target: { value: "@beta_user" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Найти" }));

    await waitFor(() => expect(api.fetchAdminUsers).toHaveBeenLastCalledWith(
      "test-token",
      expect.objectContaining({ q: "@beta_user", limit: 25, offset: 0 }),
      expect.any(AbortSignal),
    ));
    const detailButton = container.querySelector(".ad-table-wrap .ad-link-button");
    expect(detailButton).not.toBeNull();
    fireEvent.click(detailButton!);

    expect(await screen.findByRole("heading", { name: "Карточка пользователя" })).toBeInTheDocument();
    expect(await screen.findByText("0:abcdef…123456")).toBeInTheDocument();
    expect(await screen.findAllByText("Moon Lantern")).not.toHaveLength(0);
    expect(screen.getByRole("heading", { name: "Сделки" })).toBeInTheDocument();
    expect(screen.getByText(/Доставка: Проверяется/)).toBeInTheDocument();
  });

  it("requires a reason before confirming a block and sends an idempotent decision", async () => {
    const { container } = render(<AdminDashboard accessToken="test-token" />);
    fireEvent.click(screen.getByRole("button", { name: "Users" }));
    await screen.findByText("123456789");
    fireEvent.click(container.querySelector(".ad-table-wrap .ad-link-button")!);
    await screen.findByRole("heading", { name: "Карточка пользователя" });

    fireEvent.click(screen.getByRole("button", { name: "Заблокировать пользователя" }));
    expect(screen.getByRole("heading", { name: "Заблокировать пользователя?" })).toBeInTheDocument();

    const confirm = screen.getByRole("button", { name: "Подтвердить блокировку" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Причина решения (5–500 символов)"), {
      target: { value: "Repeated abuse confirmed" },
    });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);

    await waitFor(() => expect(api.submitUserAccessDecision).toHaveBeenCalledWith(
      "test-token", "user-1", "block", "Repeated abuse confirmed",
    ));
    expect(await screen.findByText("Аккаунт заблокирован, решение записано в журнал.")).toBeInTheDocument();
  });

  it("shows read-only order status and never invents payment controls", async () => {
    render(<AdminDashboard accessToken="test-token" />);
    fireEvent.click(screen.getByRole("button", { name: "Orders" }));

    expect(await screen.findAllByText("Moon Lantern")).not.toHaveLength(0);
    expect(container.querySelector(".ad-status-observing_transfer")).toHaveTextContent("Проверка перевода");
    expect(screen.getByText("Проверяется")).toBeInTheDocument();
    expect(screen.getByText("Только чтение · резервирование не является оплатой")).toBeInTheDocument();
    expect(screen.queryByText(/оплачен|payment|refund|payout/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /завершить сделку|refund|payout/i })).not.toBeInTheDocument();
  });

  it("preserves the existing listing moderation workflow in its own tab", async () => {
    render(<AdminDashboard accessToken="test-token" />);
    fireEvent.click(screen.getByRole("button", { name: "Listings" }));

    expect(screen.getByTestId("moderation-section")).toHaveTextContent("Moderation mounted");
  });

  it("loads combined audit actions from the backend", async () => {
    render(<AdminDashboard accessToken="test-token" />);
    fireEvent.click(screen.getByRole("button", { name: "Audit Log" }));

    expect(await screen.findAllByText("Policy review confirmed")).not.toHaveLength(0);
    expect(api.fetchCombinedAdminAuditLog).toHaveBeenCalledWith(
      "test-token",
      expect.objectContaining({ limit: 25, offset: 0 }),
      expect.any(AbortSignal),
    );
  });
});
