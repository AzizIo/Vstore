import { expect, test } from "@playwright/test";
import { mockMarketplaceApi } from "./fixtures/marketplace";

const adminUserId = "11111111-1111-4111-8111-111111111111";
const adminUser = {
  id: adminUserId,
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
const adminOverview = {
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
  recent_registrations: [adminUser],
  recent_platform_events: [],
};
const adminOrder = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  listing_id: "22222222-2222-4222-8222-222222222222",
  listing_title: "Moon Lantern",
  asset_name: "Lantern NFT",
  buyer_id: adminUserId,
  buyer_name: "Beta User",
  buyer_username: "beta_user",
  seller_id: "33333333-3333-4333-8333-333333333333",
  seller_name: "Seller",
  seller_username: "seller",
  price_amount: "12.5",
  price_currency: "TON",
  status: "observing_transfer",
  created_at: "2026-11-12T10:00:00Z",
  updated_at: "2026-11-12T10:15:00Z",
  delivery_status: "observing",
  delivery_verified_at: null,
};

async function mockAdminApi(page: import("@playwright/test").Page) {
  await page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const json = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
    if (path === "/api/admin/access" && method === "GET") {
      return json({ is_admin: true });
    }
    if (path === "/api/admin/overview" && method === "GET") {
      return json(adminOverview);
    }
    if (path === "/api/admin/users" && method === "GET") {
      return json({ items: [adminUser], total: 1, limit: 25, offset: 0 });
    }
    if (path === `/api/admin/users/${adminUserId}` && method === "GET") {
      return json({
        ...adminUser,
        verified_wallets: [{
          address_short: "0:abcdef…123456",
          network: "testnet",
          is_primary: true,
        }],
      });
    }
    if (path === `/api/admin/users/${adminUserId}/listings` && method === "GET") {
      return json({ items: [{
        id: "22222222-2222-4222-8222-222222222222",
        status: "active",
        title: "Moon Lantern",
        asset_name: "Lantern NFT",
        price_amount: "12.5",
        price_currency: "TON",
        created_at: "2026-11-01T10:00:00Z",
        updated_at: "2026-11-01T10:00:00Z",
        expires_at: null,
      }], total: 1, limit: 10, offset: 0 });
    }
    if (path === `/api/admin/users/${adminUserId}/orders` && method === "GET") {
      return json({ items: [{
        id: adminOrder.id,
        role: "buyer",
        status: adminOrder.status,
        listing_id: adminOrder.listing_id,
        listing_title: adminOrder.listing_title,
        asset_name: adminOrder.asset_name,
        counterparty_name: "Seller",
        counterparty_username: "seller",
        price_amount: adminOrder.price_amount,
        price_currency: adminOrder.price_currency,
        created_at: adminOrder.created_at,
        updated_at: adminOrder.updated_at,
        delivery_status: adminOrder.delivery_status,
        delivery_verified_at: null,
      }], total: 1, limit: 10, offset: 0 });
    }
    if (path === `/api/admin/users/${adminUserId}/audit` && method === "GET") {
      return json({ items: [], total: 0, limit: 10, offset: 0 });
    }
    if (path === "/api/admin/orders" && method === "GET") {
      return json({ items: [adminOrder], total: 1, limit: 25, offset: 0 });
    }
    if (path === "/api/admin/audit-log" && method === "GET") {
      return json({ items: [], total: 0, limit: 25, offset: 0 });
    }
    if (path === `/api/admin/users/${adminUserId}/block` && method === "POST") {
      return json({
        user_id: adminUserId,
        is_blocked: true,
        audit: {
          id: "audit-1",
          actor_id: "admin-1",
          target_user_id: adminUserId,
          action: "blocked",
          reason: "Policy review confirmed",
          before_snapshot: { is_blocked: false },
          after_snapshot: { is_blocked: true },
          request_id: null,
          idempotency_key: request.headers()["idempotency-key"],
          occurred_at: "2026-11-13T10:00:00Z",
        },
      });
    }
    return json({ detail: `No admin fixture for ${method} ${path}` }, 404);
  });
}

test("admin dashboard stays within mobile viewport and user details are usable", async ({ page }) => {
  await mockMarketplaceApi(page, { authenticated: true });
  await mockAdminApi(page);
  await page.goto("/admin");

  await expect(page.getByRole("heading", { name: "Admin Dashboard" })).toBeVisible();
  await expect(page.getByText("101")).toBeVisible();

  for (const width of [320, 360, 390, 430]) {
    await page.setViewportSize({ width, height: 844 });
    const dimensions = await page.evaluate(() => ({
      viewport: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      dashboardWidth: document.querySelector(".admin-dashboard")?.getBoundingClientRect().width ?? Infinity,
    }));
    expect(dimensions.documentWidth, `admin route horizontally overflows at ${width}px`).toBeLessThanOrEqual(width);
    expect(dimensions.dashboardWidth).toBeLessThanOrEqual(width);
  }

  await page.getByRole("button", { name: "Users", exact: true }).click();
  await expect(page.getByText("123456789")).toBeVisible();
  const userCard = page.locator(".ad-user-card").first();
  await userCard.click();
  await expect(page.getByRole("heading", { name: "Карточка пользователя" })).toBeVisible();
  await expect(page.getByText("0:abcdef…123456")).toBeVisible();
  await expect(page.locator(".ad-user-panel")).toBeVisible();

  const panelDimensions = await page.locator(".ad-user-panel").evaluate((element) => ({
    viewport: window.innerWidth,
    right: element.getBoundingClientRect().right,
    left: element.getBoundingClientRect().left,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(panelDimensions.left).toBeGreaterThanOrEqual(0);
  expect(panelDimensions.right).toBeLessThanOrEqual(panelDimensions.viewport);
  expect(panelDimensions.scrollWidth).toBeLessThanOrEqual(panelDimensions.viewport);
});

test("admin Orders remains read-only and shows real delivery status without payment status", async ({ page }) => {
  await mockMarketplaceApi(page, { authenticated: true });
  await mockAdminApi(page);
  await page.goto("/admin");

  await page.getByRole("button", { name: "Orders", exact: true }).click();
  await expect(page.getByText("Moon Lantern").first()).toBeVisible();
  await expect(page.locator(".ad-status-observing_transfer").first()).toHaveText("Проверка перевода");
  await expect(page.getByText("Проверяется").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /завершить сделку|refund|payout/i })).toHaveCount(0);
  await expect(page.getByText(/payment status|refund|payout/i)).toHaveCount(0);
});
