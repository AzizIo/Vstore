import { createHmac } from "node:crypto";

import { expect, test } from "@playwright/test";
import { Address, Cell } from "@ton/core";

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

async function installTonConnectTestBoundary(
  page: import("@playwright/test").Page,
  walletAddress: string,
): Promise<void> {
  await page.addInitScript((address) => {
    const boundary = {
      wallet: { account: { address, chain: "-239" } },
      sendTransaction: async (request: {
        validUntil: number;
        network: string;
        messages: Array<{ address: string; amount: string; payload: string }>;
      }) => {
        localStorage.setItem("viltara-e2e-wallet-request", JSON.stringify(request));
        return { boc: btoa("isolated-e2e-signed-external-message") };
      },
    };
    (window as Window & { __VILTARA_TON_CONNECT_TEST__?: typeof boundary })
      .__VILTARA_TON_CONNECT_TEST__ = boundary;
  }, walletAddress);
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
    await installTonConnectTestBoundary(sellerPage, "0:" + "11".repeat(32));
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

    const queueResponse = await sellerContext.request.get(
      "http://127.0.0.1:8000/api/admin/moderation",
      { headers: { Authorization: "Bearer " + bootstrapSession.access_token } },
    );
    const queueBody = await queueResponse.json() as { items: Array<{ title: string | null }>; total: number; detail?: string };
    expect(queueResponse.status(), JSON.stringify(queueBody)).toBe(200);
    expect(queueBody.items.some((item) => item.title === "E2E Published NFT"), JSON.stringify(queueBody)).toBe(true);

    // Open the isolated admin route; marketplace navigation remains untouched.
    await sellerPage.goto("/admin");
    await expect(sellerPage.getByRole("heading", { name: "Moderation & Audit" })).toBeVisible();
    const moderationCard = sellerPage.locator(".admin-listing").filter({ hasText: "E2E Published NFT" });
    await expect(moderationCard).toBeVisible();
    await moderationCard.getByRole("button", { name: "Suspend", exact: true }).click();
    const suspendDialog = sellerPage.getByRole("dialog", { name: "Suspend listing" });
    await suspendDialog.getByLabel("Explanation (5–500 characters)").fill("API-backed moderation acceptance");
    await suspendDialog.getByRole("button", { name: "Confirm suspend" }).click();
    await expect(moderationCard.getByText("suspended", { exact: true })).toBeVisible();
    await moderationCard.getByRole("button", { name: "Audit history" }).click();
    await expect(moderationCard.getByText("suspended", { exact: true }).first()).toBeVisible();
    await moderationCard.getByRole("button", { name: "Restore", exact: true }).click();
    const restoreDialog = sellerPage.getByRole("dialog", { name: "Restore listing" });
    await restoreDialog.getByLabel("Explanation (5–500 characters)").fill("Ownership rechecked for restoration");
    await restoreDialog.getByRole("button", { name: "Confirm restore" }).click();
    await expect(moderationCard.getByText("active", { exact: true })).toBeVisible();
    await sellerPage.goto("/");
    await expect(sellerPage.getByRole("button", { name: "Orders", exact: true })).toBeVisible();
    await sellerPage.getByRole("button", { name: "Orders", exact: true }).click();


    // The buyer's separate browser context will prove public catalog visibility
    // from a fresh API request after the seller has published the listing.

    const buyerInitData = await installTelegramBridge(buyerPage, buyer);
    const buyerBootstrap = await buyerContext.request.post(
      "http://127.0.0.1:5173/api/auth/telegram",
      { data: { init_data: buyerInitData } },
    );
    expect(buyerBootstrap.status()).toBe(200);
    const buyerSession = await buyerBootstrap.json() as { access_token: string };
    const forbiddenAdminQueue = await buyerContext.request.get(
      "http://127.0.0.1:5173/api/admin/moderation",
      { headers: { Authorization: "Bearer " + buyerSession.access_token } },
    );
    expect(forbiddenAdminQueue.status()).toBe(403);

    await buyerPage.goto("/");
    await expect(buyerPage.getByText(/Signed in as E2E Buyer/)).toBeVisible();

    await buyerPage.getByRole("button", { name: /E2E Published NFT/ }).click();
    await expect(buyerPage.getByRole("heading", { name: "E2E Published NFT" })).toBeVisible();
    await expect(buyerPage.getByText(/^15\.75(?:0+)? TON$/)).toBeVisible();
    await buyerPage.getByRole("button", { name: "Place order", exact: true }).click();
    const reservationDialog = buyerPage.getByRole("dialog", { name: "Reserve this listing?" });
    await expect(reservationDialog).toContainText("E2E Published NFT");
    await expect(reservationDialog).toContainText("15.75 TON");
    await expect(reservationDialog).toContainText("E2E Seller");
    await expect(reservationDialog).toContainText("Payment is not enabled and no funds will be collected");
    expect(buyerApiRequests.some((item) => item === "POST /api/orders")).toBe(false);

    await reservationDialog.getByRole("button", { name: "Confirm reservation" }).click();
    const reservationSuccess = buyerPage.getByRole("dialog", { name: "Reservation confirmed" });
    await expect(reservationSuccess).toContainText("Payment is not enabled, no funds were collected");
    await reservationSuccess.getByRole("button", { name: "View Orders" }).click();

    await expect(buyerPage.getByRole("heading", { name: "Order workspace" })).toBeVisible();
    await expect(buyerPage.getByText("Reservation pending", { exact: true })).toBeVisible();
    await expect(buyerPage.getByText(/^15\.75(?:0+)? TON$/)).toBeVisible();
    await buyerPage.getByRole("button", { name: /Open order E2E Published NFT/ }).click();
    await expect(buyerPage.getByRole("heading", { name: "Lifecycle" })).toBeVisible();
    await expect(buyerPage.getByText(/Payments are not enabled/)).toBeVisible();

    // Continue through the real delivery APIs. Only the external TON Connect
    // wallet boundary and loopback TON Center provider are simulated.
    const buyerOrdersResponse = await buyerContext.request.get(
      "http://127.0.0.1:5173/api/orders?role=buyer&limit=100",
      { headers: { Authorization: `Bearer ${buyerSession.access_token}` } },
    );
    expect(buyerOrdersResponse.status()).toBe(200);
    const buyerOrders = await buyerOrdersResponse.json() as {
      items: Array<{ id: string; title: string | null }>;
    };
    const persistedOrder = buyerOrders.items.find((item) => item.title === "E2E Published NFT");
    expect(persistedOrder).toBeTruthy();
    const orderId = persistedOrder!.id;

    await sellerPage.getByRole("button", { name: "Orders", exact: true }).click();
    await sellerPage.getByRole("tab", { name: /Sales/ }).click();
    await sellerPage.getByRole("button", { name: /Open order E2E Published NFT/ }).click();
    await expect(sellerPage.getByRole("heading", { name: "NFT transfer" })).toBeVisible();
    await sellerPage.getByRole("button", { name: "Prepare transfer" }).click();
    await expect(sellerPage.getByRole("button", { name: "Review and sign in wallet" })).toBeVisible();

    const deliveryStateResponse = await sellerContext.request.get(
      `http://127.0.0.1:5173/api/orders/${orderId}/delivery`,
      { headers: { Authorization: `Bearer ${bootstrapSession.access_token}` } },
    );
    expect(deliveryStateResponse.status()).toBe(200);
    const deliveryState = await deliveryStateResponse.json() as {
      attempt: {
        item_address: string;
        seller_address: string;
        buyer_address: string;
        query_id: string;
        network: string;
        deadline: string;
      };
    };
    const preparedAttempt = deliveryState.attempt;
    expect(preparedAttempt.network).toBe("mainnet");

    const submissionResponsePromise = sellerPage.waitForResponse((response) =>
      response.url().includes(`/api/orders/${orderId}/delivery/submissions`) &&
      response.request().method() === "POST",
    );
    await sellerPage.getByRole("button", { name: "Review and sign in wallet" }).click();
    const submissionResponse = await submissionResponsePromise;
    expect(submissionResponse.status()).toBe(200);

    const walletRequest = await sellerPage.evaluate(() => JSON.parse(
      localStorage.getItem("viltara-e2e-wallet-request") ?? "null",
    ) as {
      validUntil: number;
      network: string;
      messages: Array<{ address: string; amount: string; payload: string }>;
    } | null);
    expect(walletRequest).toBeTruthy();
    expect(walletRequest!.network).toBe("-239");
    expect(walletRequest!.validUntil).toBe(Math.floor(Date.parse(preparedAttempt.deadline) / 1000));
    expect(walletRequest!.messages).toHaveLength(1);
    expect(walletRequest!.messages[0].address).toBe(Address.parse(preparedAttempt.item_address).toString({
      urlSafe: true, bounceable: true, testOnly: false,
    }));
    expect(walletRequest!.messages[0].amount).toBe("50000000");
    const transfer = Cell.fromBase64(walletRequest!.messages[0].payload).beginParse();
    expect(transfer.loadUint(32)).toBe(0x5fcc3d14);
    expect(transfer.loadUintBig(64)).toBe(BigInt(preparedAttempt.query_id));
    expect(transfer.loadAddress()?.toRawString()).toBe(Address.parse(preparedAttempt.buyer_address).toRawString());
    expect(transfer.loadAddress()?.toRawString()).toBe(Address.parse(preparedAttempt.seller_address).toRawString());

    const providerFixture = await sellerContext.request.post(
      "http://127.0.0.1:8999/__e2e__/delivery",
      { data: preparedAttempt },
    );
    expect(providerFixture.status()).toBe(200);

    await expect.poll(async () => {
      const response = await sellerContext.request.get(
        `http://127.0.0.1:5173/api/orders/${orderId}`,
        { headers: { Authorization: `Bearer ${bootstrapSession.access_token}` } },
      );
      const order = await response.json() as { status: string };
      return order.status;
    }, { timeout: 45_000, intervals: [500, 1000, 2000] }).toBe("completed");

    await sellerPage.getByRole("button", { name: "Refresh verification status" }).click();
    await expect(sellerPage.getByText("Transfer independently verified", { exact: true })).toBeVisible();
    await buyerPage.getByRole("button", { name: "Refresh verification status" }).click();
    await expect(buyerPage.getByText("Transfer independently verified", { exact: true })).toBeVisible();
    await expect(buyerPage.getByText("Completed", { exact: true }).first()).toBeVisible();

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

  const catalog = await page.evaluate(async () => {
    const response = await fetch("/api/listings");
    return {
      status: response.status,
      body: await response.json() as {
        items?: Array<{ title?: string | null; asset?: { name?: string | null } }>;
        total?: number;
        limit?: number;
        offset?: number;
      },
    };
  });
  expect(catalog.status).toBe(200);
  expect(Array.isArray(catalog.body.items)).toBe(true);
  expect(Number.isInteger(catalog.body.total)).toBe(true);
  expect(catalog.body.limit).toBe(24);
  expect(catalog.body.offset).toBe(0);

  // If another active listing exists, prove the public UI renders data returned
  // by the real catalog endpoint. The seller journey above reserves its fixture.
  const firstListing = catalog.body.items?.[0];
  const visibleTitle = firstListing?.title ?? firstListing?.asset?.name;
  if (visibleTitle) {
    await expect(page.getByText(visibleTitle, { exact: true })).toBeVisible();
  }

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
