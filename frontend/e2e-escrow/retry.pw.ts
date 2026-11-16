import { expect, test } from "@playwright/test";

import { mockMarketplaceApi } from "../e2e/fixtures/marketplace";

const dealId = "d252d252-d252-4252-8252-d252d252d252";
const buyerWalletId = "wallet-escrow-retry-e2e";
const buyerWalletAddress = "0:" + "33".repeat(32);
const escrowAddress = "0:" + "66".repeat(32);
const nftItemAddress = "0:" + "44".repeat(32);

const deal = {
  id: dealId,
  listing_id: "l252l252-l252-4252-8252-l252l252l252",
  listing_key: "e2e-escrow-retry-listing",
  buyer_id: "buyer-1",
  seller_id: "seller-1",
  state: "refunded",
  network: "testnet",
  nft: {
    asset_id: null,
    title: "Bounced Retry NFT",
    image_url: null,
    item_address: nftItemAddress,
    collection_address: "0:" + "55".repeat(32),
  },
  escrow_address: escrowAddress,
  seller_wallet_address: "0:" + "77".repeat(32),
  buyer_wallet_address: buyerWalletAddress,
  price_nano: "1000000000",
  fee_bps: 0,
  buyer_review_deadline: null,
  dispute_deadline: null,
  available_actions: [],
  created_at: "2026-11-16T10:00:00Z",
  updated_at: "2026-11-16T10:00:00Z",
  dispute: null,
};

const retryableOutbound = {
  query_id: "424242",
  slot: "first",
  kind: 5,
  recipient_address: buyerWalletAddress,
  amount_nanotons: "1000000000",
  retry_window_seconds: 1800,
  proof_masterchain_seqno: 700,
  proof_masterchain_block_hash: "aa".repeat(32),
  proof_state_data_hash: "bb".repeat(32),
  proof_provider_id: "pytoniq-trust0-testnet-v1",
};

const preparedRetry = {
  action_id: "a252a252-a252-4252-8252-a252a252a252",
  action: "retry_failed_outbound_action",
  network: "testnet",
  factory_address: null,
  escrow_address: escrowAddress,
  nft_item_address: nftItemAddress,
  price_nano: "1000000000",
  fee_bps: 0,
  execution_reserve_nano: "500000000",
  valid_until: "2099-01-01T00:00:00Z",
  messages: [{
    address: escrowAddress,
    amount_nano: "10000000",
    payload_boc: "te6ccgEBAQEA",
    state_init_boc: null,
  }],
  display_purpose: "Повторить bounced refund для query 424242 в TON testnet.",
};

test("recipient can prepare the bounced outbound retry; signing remains disabled", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await mockMarketplaceApi(page, { authenticated: true });

  const apiRequests: Array<{
    method: string;
    path: string;
    body: unknown;
    idempotencyKey: string | null;
  }> = [];

  await page.route(
    (url) => new URL(url).pathname === "/api/wallets/me",
    async (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{
        id: buyerWalletId,
        address: buyerWalletAddress,
        network: "testnet",
        is_verified: true,
        is_primary: true,
      }]),
    }),
  );

  await page.route(
    (url) => {
      const parsed = new URL(url);
      return parsed.pathname === "/api/assets/me"
        && parsed.searchParams.get("wallet_id") === buyerWalletId;
    },
    async (route) => {
      const url = new URL(route.request().url());
      const limit = Number(url.searchParams.get("limit") ?? 24);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [],
          wallet_id: buyerWalletId,
          limit,
          offset,
          next_offset: offset,
          has_more: false,
        }),
      });
    },
  );

  await page.route(
    (url) => new URL(url).pathname.startsWith("/api/escrow/"),
    async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      const method = request.method();

      apiRequests.push({
        method,
        path,
        body: method === "POST" ? request.postDataJSON() : null,
        idempotencyKey: request.headers()["idempotency-key"] ?? null,
      });

      const pageResponse = (items: unknown[]) => route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items, total: items.length, next_cursor: null }),
      });

      if (method === "GET" && path.endsWith("/marketplace/listing-intents")) {
        return pageResponse([]);
      }
      if (method === "GET" && path.endsWith("/listing-intents")) {
        return pageResponse([]);
      }
      if (method === "GET" && path.endsWith("/buyer/deals")) {
        return pageResponse([deal]);
      }
      if (method === "GET" && path.endsWith("/seller/deals")) {
        return pageResponse([]);
      }
      if (method === "GET" && path.endsWith("/seller/withdrawals")) {
        return pageResponse([]);
      }
      if (method === "GET" && path === "/api/escrow/deals/" + dealId + "/retryable-outbound-actions") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([retryableOutbound]),
        });
      }
      if (method === "POST" && path === "/api/escrow/deals/" + dealId + "/prepare/retry-failed-outbound-action") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(preparedRetry),
        });
      }
      return route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "No escrow E2E fixture for " + method + " " + path }),
      });
    },
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Escrow · testnet" }).click();

  await expect(page.getByRole("heading", { name: "TON Escrow" })).toBeVisible();
  expect(pageErrors).toEqual([]);
  await expect(page.getByRole("button", { name: /Открыть сделку Bounced Retry NFT/ })).toBeVisible();

  const retryButton = page.getByRole("button", { name: "Повторить отправку · query 424242" });
  await expect(retryButton).toBeVisible();
  await expect(retryButton).toBeEnabled();
  await retryButton.click();

  const review = page.getByRole("dialog", { name: "Повторить неудавшуюся отправку" });
  await expect(review).toBeVisible();
  await expect(review).toContainText("TON testnet");
  await expect(review).toContainText(escrowAddress);
  await expect(review).toContainText(nftItemAddress);
  await expect(review).toContainText(buyerWalletAddress);
  await expect(review).toContainText("Повторить bounced refund для query 424242 в TON testnet.");
  await expect(review.getByRole("button", { name: "Подписать в TON Connect" })).toBeDisabled();
  await expect(review.getByRole("status")).toContainText("Подписание отключено");

  const retryRequest = apiRequests.find((item) =>
    item.method === "POST"
    && item.path === "/api/escrow/deals/" + dealId + "/prepare/retry-failed-outbound-action",
  );
  expect(retryRequest).toBeTruthy();
  expect(retryRequest?.body).toEqual({ query_id: "424242" });
  expect(retryRequest?.idempotencyKey).toMatch(/^[0-9a-f-]{36}$/i);
  expect(apiRequests.some((item) =>
    item.method === "GET"
    && item.path === "/api/escrow/deals/" + dealId + "/retryable-outbound-actions",
  )).toBe(true);
});
