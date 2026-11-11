import { createHmac } from "node:crypto";

import { expect, test } from "@playwright/test";

interface TelegramTestUser {
  id: number;
  first_name: string;
  last_name: string;
  username: string;
  language_code: string;
}

function signedTelegramInitData(user: TelegramTestUser): string {
  const botToken = process.env.BOT_TOKEN;
  if (!botToken) throw new Error("BOT_TOKEN is required only by the isolated API-backed E2E job.");

  const params = new URLSearchParams({
    auth_date: String(Math.floor(Date.now() / 1000)),
    query_id: `e2e-query-${user.id}`,
    user: JSON.stringify(user),
  });
  const dataCheckString = [...params.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${value}`)
    .join("\n");
  const secretKey = createHmac("sha256", "WebAppData").update(botToken).digest();
  const hash = createHmac("sha256", secretKey).update(dataCheckString).digest("hex");
  params.set("hash", hash);
  return params.toString();
}

async function installTelegramBridge(
  page: import("@playwright/test").Page,
  user: TelegramTestUser,
): Promise<string> {
  const initData = signedTelegramInitData(user);
  await page.addInitScript((signedData) => {
    const webApp = {
      initData: signedData,
      initDataUnsafe: {},
      ready: () => undefined,
      expand: () => undefined,
    };
    (window as Window & { Telegram?: { WebApp?: typeof webApp } }).Telegram = {
      WebApp: webApp,
    };
  }, initData);
  return initData;
}

const seller: TelegramTestUser = {
  id: 990000001,
  first_name: "E2E Seller",
  last_name: "Fixture",
  username: "e2e_seller",
  language_code: "en",
};

const buyer: TelegramTestUser = {
  id: 990000002,
  first_name: "E2E Buyer",
  last_name: "Fixture",
  username: "e2e_buyer",
  language_code: "en",
};

test(
  "real seller publishes a verified NFT and buyer reserves it through FastAPI",
  async ({ browser }) => {
  const sellerContext = await browser.newContext();
  const buyerContext = await browser.newContext();
  const sellerPage = await sellerContext.newPage();
  const buyerPage = await buyerContext.newPage();
  const sellerApiRequests: string[] = [];
  const buyerApiRequests: string[] = [];

  sellerPage.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/")) sellerApiRequests.push(`${request.method()} ${path}`);
  });
  buyerPage.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/")) buyerApiRequests.push(`${request.method()} ${path}`);
  });

  try {
    const sellerInitData = await installTelegramBridge(sellerPage, seller);
    const bootstrapAuth = await sellerContext.request.post(
      "http://127.0.0.1:5173/api/auth/telegram",
      { data: { init_data: sellerInitData } },
    );
    expect(bootstrapAuth.status()).toBe(200);
    const bootstrapSession = await bootstrapAuth.json() as { access_token: string };
    const redisChallenge = await sellerContext.request.post(
      "http://127.0.0.1:5173/api/wallets/proof/challenge",
      { headers: { Authorization: `Bearer ${bootstrapSession.access_token}` } },
    );
    expect(redisChallenge.status()).toBe(200);
    expect(typeof (await redisChallenge.json()).payload).toBe("string");

    await sellerPage.goto("/");
    await expect(sellerPage.getByText(/Signed in as E2E Seller/)).toBeVisible();

    await sellerPage.getByRole("button", { name: "My Listings", exact: true }).click();
    await sellerPage.getByRole("button", { name: "Create listing", exact: true }).click();
    await expect(sellerPage.getByRole("heading", { name: "Create listing draft" })).toBeVisible();

    const inventoryAsset = sellerPage.getByRole("button", { name: /E2E Verified NFT/ });
    await expect(inventoryAsset).toBeVisible();
    await inventoryAsset.click();

    await sellerPage.getByRole("spinbutton", { name: "Price amount" }).fill("15.75");
    await sellerPage.locator(".draft-form input[maxlength='200']").fill("E2E Published NFT");
    await sellerPage.getByRole("button", { name: "Create private draft" }).click();
    await expect(sellerPage.getByRole("heading", { name: "Draft created" })).toBeVisible();
    await sellerPage.getByRole("button", { name: "View My Listings" }).click();

    const draftCard = sellerPage.getByRole("button", { name: /E2E Published NFT/ });
    await expect(draftCard).toBeVisible();
    await draftCard.click();
    await sellerPage.getByRole("button", { name: "Publish listing", exact: true }).click();
    await sellerPage.getByRole("button", { name: "Confirm publish", exact: true }).click();
    await expect(sellerPage.locator(".listing-status-active")).toHaveText("Active");

    // The buyer's separate browser context will prove public catalog visibility
    // from a fresh API request after the seller has published the listing.

    await installTelegramBridge(buyerPage, buyer);
    await buyerPage.goto("/");
    await expect(buyerPage.getByText(/Signed in as E2E Buyer/)).toBeVisible();

    await buyerPage.getByRole("button", { name: /E2E Published NFT/ }).click();
    await expect(buyerPage.getByRole("heading", { name: "E2E Published NFT" })).toBeVisible();
    await expect(buyerPage.getByText(/^15\.75(?:0+)? TON$/)).toBeVisible();
    await buyerPage.getByRole("button", { name: "Place order", exact: true }).click();
    await expect(
      buyerPage.getByText("Order created. Payment is not enabled; check its status in Orders."),
    ).toBeVisible();

    await buyerPage.getByRole("button", { name: "Orders", exact: true }).click();
    await expect(buyerPage.getByRole("heading", { name: "My Orders" })).toBeVisible();
    await expect(buyerPage.getByText("Payment pending", { exact: true })).toBeVisible();
    await expect(buyerPage.getByText(/^15\.75(?:0+)? TON$/)).toBeVisible();
    await expect(buyerPage.getByText(/Payment processing is not enabled/)).toBeVisible();

    expect(sellerApiRequests).toContain("POST /api/auth/telegram");
    expect(sellerApiRequests).toContain("GET /api/assets/me");
    expect(sellerApiRequests).toContain("POST /api/listings");
    expect(
      sellerApiRequests.some(
        (item) => item.startsWith("POST /api/listings/") && item.endsWith("/publish"),
      ),
    ).toBe(true);
    expect(buyerApiRequests).toContain("POST /api/auth/telegram");
    expect(buyerApiRequests).toContain("POST /api/orders");
    expect(buyerApiRequests.some((item) => item.startsWith("GET /api/orders"))).toBe(true);
  } finally {
    await sellerContext.close();
    await buyerContext.close();
  }
});

test(
  "anonymous browser can read the public catalog but cannot call protected write endpoints",
  async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Explore listings" })).toBeVisible();
  await expect(page.getByRole("button", { name: "My Listings", exact: true })).toBeVisible();

  const statuses = await page.evaluate(async () => {
    const listing = await fetch("/api/listings/me");
    const draft = await fetch("/api/listings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asset_id: "11111111-1111-4111-8111-111111111111",
        price_amount: "1",
        price_currency: "TON",
      }),
    });
    const order = await fetch("/api/orders", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": "anonymous-e2e-must-not-create-an-order",
      },
      body: JSON.stringify({ listing_id: "11111111-1111-4111-8111-111111111111" }),
    });
    return [listing.status, draft.status, order.status];
  });

  expect(statuses).toEqual([401, 401, 401]);
});
